"""ASR：語音轉文字。V0 只接 OpenAI Whisper，對外只暴露 provider 無關的介面，
之後要加其他供應商，在這個模組內部加實作分支即可，不用動呼叫端。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from openai import OpenAI

from . import media, progress_estimation

MODEL_NAME = "whisper-1"
PRICE_PER_MINUTE_USD = 0.006

# Whisper API 不會回報處理進度，這個係數是實測校準值：
# 602 秒音訊實際約需 42 秒處理（約 7%），估計用音訊長度的 12% 留安全邊際，
# 避免預估跑到 100% 但 API 還沒回應。顯示上限（95%）交給 progress_estimation 處理。
_ESTIMATED_PROCESSING_RATIO = 0.12
_MIN_ESTIMATED_SEC = 3.0

# 幻覺字幕過濾門檻：用真實 app.db 資料校準（6 支已分析影片、560 筆片段），
# 詳見 docs/02-technical-decisions.md#asrwhisper-幻覺字幕過濾。分兩種互補的偵測模式：
#
# 模式 A（is_hallucinated_transcript）：no_speech_prob 偏高（模型自己認為這段
# 大概沒有語音）卻還是生成文字，是背景音樂被誤判成重複亂碼最常見的模式——
# 真實資料顯示這個訊號乾淨可分：真實對白影片的 no_speech_prob 最高值只有
# 0.264～0.487，幻覺片段（例如背景音樂被誤判成「ក្រាមំ ក្រាមំ」）集中在
# 0.7～0.985，中間有明顯空隙，0.7 不會誤殺。
NO_SPEECH_PROB_THRESHOLD = 0.7

# 模式 B（find_repetitive_transcript_indices）：整段被誤判成單字重複（例如
# 「Music Music」），no_speech_prob／avg_logprob／compression_ratio 三個信心
# 分數的範圍都跟真實對白重疊，模式 A 抓不到，需要換一個訊號——連續多個場景
# 都被同一個詞主導。真實資料顯示：真實內容（NBA 對白、動物教學）最長連續
# 符合「主導詞佔比 ≥ 0.5 且跟前一場景主導詞相同」只到 2，幻覺案例最低是 4，
# 中間有清楚空隙，門檻定 3 留緩衝。單獨用「主導詞佔比」或單獨用「連續同一
# 主導詞」都各自會誤殺真實內容（前者誤殺短促的動物教學內容、後者誤殺英文
# 長句裡 the 這種高頻虛詞造成的巧合），兩個條件要同時成立。
DOMINANCE_RATIO_THRESHOLD = 0.5
MIN_REPETITION_RUN_LENGTH = 3


@dataclass
class TranscriptSegment:
    start_sec: float
    end_sec: float
    text: str
    no_speech_prob: float
    avg_logprob: float
    compression_ratio: float


@dataclass
class TranscribeResult:
    segments: list[TranscriptSegment]
    cost_usd: float


@dataclass
class SegmentScores:
    """跟 text_for_range() 對應：某個時間範圍內，底下逐句 Whisper 片段信心分數的彙總值。
    範圍內沒有任何 Whisper 片段時三個值都是 None（例如純畫面、完全沒聲音的片段）。
    """
    no_speech_prob: float | None
    avg_logprob: float | None
    compression_ratio: float | None


def transcribe_with_progress(
    client: OpenAI,
    video_path: Path,
    duration_sec: float,
    on_progress: Callable[[int], None] | None = None,
) -> TranscribeResult:
    """語音轉文字，等待 API 回應期間會依校準過的預估時間定期回報百分比
    （不是真的伺服器端進度，Whisper API 沒有提供）。
    """
    audio_path = _extract_audio(video_path)
    estimated_total = max(_MIN_ESTIMATED_SEC, duration_sec * _ESTIMATED_PROCESSING_RATIO)
    try:
        response = progress_estimation.run_with_estimated_progress(
            lambda: _call_whisper(client, audio_path), estimated_total, on_progress
        )
    finally:
        audio_path.unlink(missing_ok=True)

    return _parse_response(response)


def text_for_range(segments: list[TranscriptSegment], start_sec: float, end_sec: float) -> str:
    """取出跟 [start_sec, end_sec] 有重疊的逐句文字，串成該片段的字幕內容。"""
    parts = [seg.text for seg in segments if seg.start_sec < end_sec and seg.end_sec > start_sec]
    return " ".join(parts).strip()


def scores_for_range(segments: list[TranscriptSegment], start_sec: float, end_sec: float) -> SegmentScores:
    """彙總跟 [start_sec, end_sec] 有重疊的 Whisper 片段信心分數：
    no_speech_prob／avg_logprob 取平均，compression_ratio 取最大值
    （範圍內只要有一段重複，就該被看見，用平均會被較長的正常內容稀釋掉）。
    """
    overlapping = [seg for seg in segments if seg.start_sec < end_sec and seg.end_sec > start_sec]
    if not overlapping:
        return SegmentScores(no_speech_prob=None, avg_logprob=None, compression_ratio=None)
    return SegmentScores(
        no_speech_prob=sum(s.no_speech_prob for s in overlapping) / len(overlapping),
        avg_logprob=sum(s.avg_logprob for s in overlapping) / len(overlapping),
        compression_ratio=max(s.compression_ratio for s in overlapping),
    )


def is_hallucinated_transcript(scores: SegmentScores) -> bool:
    """判斷這段字幕是不是背景音樂被誤判成重複亂碼的幻覺（模式 A，見
    NO_SPEECH_PROB_THRESHOLD 校準說明）。範圍內沒有任何 Whisper 片段
    （no_speech_prob 是 None）不算可疑，不能因為沒資料就當作幻覺。"""
    return scores.no_speech_prob is not None and scores.no_speech_prob > NO_SPEECH_PROB_THRESHOLD


def _dominant_word_ratio(text: str) -> tuple[str | None, float]:
    """回傳這段文字裡出現次數最多的詞（小寫）與它占全部詞數的比例。空字串
    回傳 (None, 0.0)。"""
    words = re.findall(r"\S+", text.lower())
    if not words:
        return None, 0.0
    word, count = Counter(words).most_common(1)[0]
    return word, count / len(words)


def find_repetitive_transcript_indices(transcripts: list[str]) -> set[int]:
    """判斷哪些場景的字幕是「整段被誤判成單字重複」的幻覺（模式 B，見
    DOMINANCE_RATIO_THRESHOLD／MIN_REPETITION_RUN_LENGTH 校準說明）。跟模式 A
    不同，這個判斷跨場景——同一個詞連續主導好幾個場景，才視為幻覈；`transcripts`
    要照場景實際順序傳入（例如 analyzer._SceneAnalysisRow 逐筆取出的 transcript_text），
    回傳的 index
    才會對應正確的場景。單一場景（不管內容多短促重複）或真實內容裡偶爾出現的
    高頻虛詞（例如英文 the）造成的巧合連續，都不會被算進來——這兩種各自都是
    單獨使用「主導詞佔比」或單獨使用「連續同一主導詞」會誤殺真實內容的已知
    陷阱，見 docs/02-technical-decisions.md#asrwhisper-幻覺字幕過濾。
    """
    hallucinated: set[int] = set()
    run_start: int | None = None
    run_word: str | None = None

    for index, text in enumerate(transcripts):
        word, ratio = _dominant_word_ratio(text)
        qualifies = word is not None and ratio >= DOMINANCE_RATIO_THRESHOLD

        if qualifies and word == run_word:
            pass  # 延續現有的連續段
        elif qualifies:
            run_start, run_word = index, word  # 開一段新的連續段
        else:
            run_start, run_word = None, None  # 這筆自己就不夠格，不能當連續段的起點
            continue

        if index - run_start + 1 >= MIN_REPETITION_RUN_LENGTH:
            hallucinated.update(range(run_start, index + 1))

    return hallucinated


def _call_whisper(client: OpenAI, audio_path: Path):
    with open(audio_path, "rb") as f:
        return client.audio.transcriptions.create(
            file=f,
            model=MODEL_NAME,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )


def _parse_response(response) -> TranscribeResult:
    segments = [
        TranscriptSegment(
            start_sec=seg.start,
            end_sec=seg.end,
            text=seg.text.strip(),
            no_speech_prob=seg.no_speech_prob,
            avg_logprob=seg.avg_logprob,
            compression_ratio=seg.compression_ratio,
        )
        for seg in (response.segments or [])
    ]
    duration_sec = response.usage.seconds if response.usage else 0.0
    cost_usd = (duration_sec / 60.0) * PRICE_PER_MINUTE_USD
    return TranscribeResult(segments=segments, cost_usd=cost_usd)


def _extract_audio(video_path: Path) -> Path:
    """抽出單聲道 16kHz 64kbps 的 mp3；呼叫端負責刪除。

    位元率不是隨便選的：它決定 Whisper 25MB 上傳上限換算成幾分鐘影片
    （實測 7,998 bytes/s ≈ 52 分鐘），見 analyzer.MAX_DURATION_SEC 的推導。
    """
    audio_path = media.new_temp_path(".mp3")
    media.run_ffmpeg(
        [
            "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
            str(audio_path),
        ],
        timeout=media.AUDIO_TIMEOUT_SEC,
    )
    return audio_path
