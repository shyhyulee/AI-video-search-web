"""本地 OCR 掃描：在既有場景邊界內多取樣幾張畫面，補上 VLM 單幀取樣（每個場景只
在中點抽一張畫面，見 vlm.py）可能漏掉的文字。純本機運算、不佔 BUDGET_USD，但有
自己的時間上限，超過就提早結束（best-effort，不是全有全無）。任何一張畫面抽取
或辨識失敗都只跳過那張，不影響其他畫面或整支影片分析——這個模組不碰資料庫、
不呼叫 OpenAI，embedding 與寫入 db 由 analyzer.py 負責（跟 vlm.py／asr.py 的
責任邊界一致）。

取樣採「回合制」廣度優先：第 1 輪讓每個場景都先拿到 1 張畫面，全部場景輪過
一次之後才進第 2 輪回頭補第 2 張……時間預算用完就跳出。這樣不管預算夠不夠，
場景覆蓋的廣度永遠優先於單一場景取樣的深度——用真實影片校準過，VLM 覆蓋率低
的內容（例如體育賽事）缺口場景可能有幾十個，舊版依場景順序、每個場景先抽完
全部張數才換下一個場景的做法，只有最前面幾個場景吃得到取樣，後面完全沒被掃到
（見 docs/02-technical-decisions.md#vlm-與-ocr 的取樣策略除錯過程）。時間預算逐張畫面檢查（不是逐場景
或逐輪次），因為單一輪（例如第 1 輪要掃過全部場景各 1 張）本身就可能超過整個
預算，需要更細的中止點才擋得住。

**已實測並放棄同一輪內用執行緒平行處理抽幀＋辨識**：EasyOCR 底層是共用同一個
PyTorch 量化 LSTM 模型（Reader 單例），多個執行緒同時呼叫 recognize() 會互搶
運算資源，即使把每次呼叫的 intra-op thread 數壓低也一樣——用真實 NBA 影片
（52 個缺口場景）實測，4 個 worker 平行版本耗時 165.6 秒，反而比循序版的
68.1 秒慢 2.4 倍。故意留這段紀錄，避免之後又重新嘗試同一條已經量測過行不通
的路線（見 docs/02-technical-decisions.md#vlm-與-ocr 的取樣策略除錯過程）。

詳細設計見 docs/02-technical-decisions.md#vlm-與-ocr。
"""
from __future__ import annotations

import logging
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import frames
from .ocr_adapters import ENGINE_EASYOCR, OcrCandidate, get_easyocr_engine

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "local-ocr-v1"

# 每個場景內的取樣間隔與張數上限——先用簡單的固定間隔取樣驗證有沒有用，
# 不做文件規劃裡完整的 scene-change/burst-mode 動態抽幀（見規劃文件設計決策 1）。
SAMPLE_INTERVAL_SEC = 2.0
MAX_FRAMES_PER_SCENE = 5

# 信心分數低於此門檻的候選直接捨棄（目前沒有 Tesseract 複核可以救回來，
# 先過濾避免雜訊污染搜尋索引）。
MIN_CONFIDENCE = 0.3

# 整支影片本地 OCR 掃描的時間上限（秒）。初始值為保守預估，尚未實測校準，
# 見 docs/05-known-limitations-and-open-items.md 的本地 OCR 項。超過就跳出、回傳目前已收集的結果。
TIME_BUDGET_SEC = 60.0


@dataclass
class OcrEventResult:
    """一個場景內、去重合併後的一筆本地 OCR 事件，供 analyzer.py 產生 embedding
    並寫入 ocr_events 表。
    """
    segment_id: int | None
    video_id: int
    start_sec: float
    end_sec: float
    frame_sec: float
    raw_text: str
    resolved_text: str
    confidence: float
    bbox: list[tuple[float, float]] | None
    primary_engine: str


def scan_scenes(
    video_id: int,
    video_path: Path,
    scenes: list[tuple[float, float, int | None]],
    on_progress: Callable[[int], None] | None = None,
) -> list[OcrEventResult]:
    """對每個場景（start_sec, end_sec, segment_id）多取樣幾張畫面跑 EasyOCR，
    回傳合併去重後的事件清單。廣度優先、按輪次取樣，見模組上方說明；時間上限
    逐張畫面檢查，超過就立刻停止（不會等目前輪次跑完）。
    """
    events: list[OcrEventResult] = []
    if not scenes:
        return events

    schedules = [_sample_timestamps(start, end) for start, end, _ in scenes]
    total_slots = sum(len(schedule) for schedule in schedules)
    if total_slots == 0:
        return events

    max_rounds = max(len(schedule) for schedule in schedules)
    frame_hits_by_scene: list[list[tuple[float, OcrCandidate]]] = [[] for _ in scenes]

    start_time = time.monotonic()
    done_slots = 0
    scenes_attempted: set[int] = set()
    budget_exceeded = False

    for round_index in range(max_rounds):
        if budget_exceeded:
            break

        for scene_index, schedule in enumerate(schedules):
            if round_index >= len(schedule):
                continue

            if time.monotonic() - start_time > TIME_BUDGET_SEC:
                budget_exceeded = True
                break

            at_sec = schedule[round_index]
            scenes_attempted.add(scene_index)
            for candidate in _recognize_frame(video_path, at_sec):
                if candidate.confidence >= MIN_CONFIDENCE:
                    frame_hits_by_scene[scene_index].append((at_sec, candidate))

            done_slots += 1
            if on_progress is not None:
                on_progress(round((done_slots / total_slots) * 100))

    if budget_exceeded:
        logger.info(
            "本地 OCR 已達時間上限，提前結束（完成 %d/%d 個取樣點，%d/%d 場景至少取到 1 張）",
            done_slots, total_slots, len(scenes_attempted), len(scenes),
        )

    for (scene_start, scene_end, segment_id), hits in zip(scenes, frame_hits_by_scene):
        events.extend(_merge_candidates(video_id, segment_id, scene_start, scene_end, hits))

    return events


def normalize_text(text: str) -> str:
    """Unicode 正規化（含全形／半形統一）＋收斂多餘空白／換行。"""
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.split()).strip()


def _sample_timestamps(start_sec: float, end_sec: float) -> list[float]:
    """場景內固定間隔取樣時間點；場景長度小於一個間隔時至少取中點那一張。"""
    if end_sec <= start_sec:
        return [start_sec]

    timestamps: list[float] = []
    at_sec = start_sec
    while at_sec < end_sec and len(timestamps) < MAX_FRAMES_PER_SCENE:
        timestamps.append(at_sec)
        at_sec += SAMPLE_INTERVAL_SEC
    return timestamps


def _recognize_frame(video_path: Path, at_sec: float) -> list[OcrCandidate]:
    try:
        frame_path = frames.extract_frame(video_path, at_sec)
    except Exception:
        logger.warning("本地 OCR 抽幀失敗（%.2fs），跳過這張畫面", at_sec, exc_info=True)
        return []

    try:
        engine = get_easyocr_engine()
        return engine.recognize(frame_path)
    except Exception:
        logger.warning("本地 OCR 辨識失敗（%.2fs），跳過這張畫面", at_sec, exc_info=True)
        return []
    finally:
        frame_path.unlink(missing_ok=True)


def _merge_candidates(
    video_id: int,
    segment_id: int | None,
    scene_start: float,
    scene_end: float,
    frame_hits: list[tuple[float, OcrCandidate]],
) -> list[OcrEventResult]:
    """同一場景內，正規化後文字相同的候選視為同一個事件：時間範圍取偵測到的
    影格時間再各加一半取樣間隔的緩衝（clamp 在場景範圍內），代表文字候選取
    信心分數最高的那筆。這是簡化版合併，不是文件規劃裡完整的 edit-similarity／
    bbox IoU／多數投票演算法（見規劃文件設計決策 3、10）。
    """
    groups: dict[str, list[tuple[float, OcrCandidate]]] = {}
    for frame_sec, candidate in frame_hits:
        normalized = normalize_text(candidate.text)
        if not normalized:
            continue
        groups.setdefault(normalized, []).append((frame_sec, candidate))

    pad = SAMPLE_INTERVAL_SEC / 2
    results: list[OcrEventResult] = []
    for normalized_text, hits in groups.items():
        frame_secs = [frame_sec for frame_sec, _ in hits]
        best_frame_sec, best_candidate = max(hits, key=lambda hit: hit[1].confidence)
        results.append(
            OcrEventResult(
                segment_id=segment_id,
                video_id=video_id,
                start_sec=max(scene_start, min(frame_secs) - pad),
                end_sec=min(scene_end, max(frame_secs) + pad),
                frame_sec=best_frame_sec,
                raw_text=best_candidate.text,
                resolved_text=normalized_text,
                confidence=best_candidate.confidence,
                bbox=best_candidate.bbox,
                primary_engine=ENGINE_EASYOCR,
            )
        )
    return results
