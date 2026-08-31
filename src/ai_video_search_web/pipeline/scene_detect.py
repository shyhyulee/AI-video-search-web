"""場景切分：用 PySceneDetect 找出片段邊界，純本機運算、不花 API 成本。"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from scenedetect import SceneManager, open_video
from scenedetect.detectors import AdaptiveDetector, ContentDetector

from . import media, progress_estimation

# scenedetect 預設的 opencv backend 在這台機器上無法解碼 AV1：沒有硬體加速，
# 軟體解碼路徑直接讀不到任何畫面（回傳 0 frame），會被誤判成「整支影片只有
# 一個場景」，而不是真的偵測不到切換。YouTube 常見的 720p 串流時常是 AV1，
# 所以用 ffprobe 先確認編碼，AV1 才切換成 pyav backend（用 ffmpeg 自己的解碼器，
# 能正確處理但明顯較慢）。

# PySceneDetect 不提供逐步進度（SceneManager 的 callback 只在偵測到場景切換時
# 觸發，分佈不均勻，不適合拿來做平滑的百分比），這裡改用背景執行緒等待期間
# 依經驗校準的預估時間回報百分比。校準數據（602 秒影片實測）：
#   pyav backend（AV1）  約 85 秒，比例 ≈ 0.16（留安全邊際）
#   opencv backend（其他）約 19 秒，比例 ≈ 0.045（留安全邊際）
_ESTIMATED_RATIO_PYAV = 0.16
_ESTIMATED_RATIO_OPENCV = 0.045
_MIN_ESTIMATED_SEC = 2.0

# ContentDetector 單獨使用會漏掉漸進式轉場（例如溶接／crossfade）：實測用
# 「The 100 Most Beautiful Faces of 2019.mp4」前 3 分鐘比對，ContentDetector
# 把 45.88~180.01 秒整整 134 秒判成單一場景，但這段裡其實有至少 5 個不同
# 人物條目（用溶接轉場）。改成 ContentDetector+AdaptiveDetector（聯集：任一個
# 判定切就切）能正確抓出中間漏掉的切點，且實測耗時幾乎沒差（decode 才是瓶頸，
# 不是 detector 運算量）。曾評估加 ThresholdDetector（偵測淡入淡出黑幕），
# 同一支影片實測發現除了抓到片頭真的從黑幕淡入的切點，也在完全靜止的片頭卡
# （前後畫面肉眼看不出差異）誤切出一個假場景，false positive 風險偏高，不採用。
# 要組合多個 detector 必須用底層 SceneManager API，簡化版的 scenedetect.detect()
# 只吃單一 detector。

# 原始場景長度落差很大（實測同一支影片有 0.10 秒到 129.76 秒都有），套用兩個
# pass 收斂到大約 8~12 秒：先合併太短的（避免破碎片段），再切開太長的（避免
# VLM／本地 OCR 只看得到一小段畫面）。SPLIT_TARGET_SEC 用 8~12 秒的中間值，
# 讓切出來的每段盡量落在目標範圍中心，不是卡在 SPLIT_ABOVE_SEC 邊界。
# merge 先、split 後的順序：如果 split 先做，merge 可能把切好的片段黏回去、
# 又超過長度上限；merge 先做、split 當最後一道保險，可以確保最終長度上限。
#
# 常數演進：原本（2026-08-19）目標 6~12 秒（5.0/10.0/9.0，12=2×6，見下段
# 說明），真實影片實測 96% 落在範圍內。2026-08-20 先試 9~12 秒
# （9.0/12.0/10.5），命中率掉到 67.7%~91.1%（因為 12≠2×9=18，見下段
# 「2×下限」限制，落空片段都是超過上限、下限保證仍 100% 沒違反）；改成
# 8~12 秒（8.0/12.0/10.0，12=1.5×8，死區比 9~12 窄）後回升到
# 78.8%~91.4%（同兩支影片：BMW 工廠 1063 秒/296 原始場景、The 100 Most
# Beautiful Faces of 2019 602 秒/33 原始場景），細節見
# docs/02-technical-decisions.md#場景切分。
MERGE_BELOW_SEC = 8.0
SPLIT_ABOVE_SEC = 12.0
SPLIT_TARGET_SEC = 10.0


@dataclass
class NormalizedScene:
    """正規化（merge/split）後的最終場景，多帶一個 `source_raw_duration`——
    這個場景所屬、合併後切分前的長度。`source_raw_duration == end_sec -
    start_sec` 代表這個場景沒有被 `_split_long_scenes()` 硬切過（本來就
    <= SPLIT_ABOVE_SEC）；`source_raw_duration` 明顯更長，代表場景偵測器
    在這段長度裡完全沒抓到任何切點，是被機械式均分出來的其中一段。

    **目前沒有任何呼叫端讀它**。它原本是 analyzer 決定要不要對這個場景觸發多幀
    VLM 取樣的訊號來源（見 docs/02-technical-decisions.md「VLM 條件式多幀取樣」），
    2026-08-31 的 P4 把取樣統一成一律三幀之後那個判斷就不存在了。

    留著而不刪，是因為它是「這個場景是不是被機械式硬切出來的」這件事唯一的紀錄，
    而且幾乎零成本（`_split_long_scenes()` 本來就算得出來，只是順手保留）。之後
    如果要回答「哪些內容值得抽超過三幀」，這是現成而且已經校準過的訊號——當初
    比較過的替代方案（pixel/HSV 差異）已經實測放棄，見
    docs/03-excluded-approaches.md。
    """
    start_sec: float
    end_sec: float
    source_raw_duration: float


def _merge_short_scenes(scenes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """由左到右累積場景，一旦累積長度達到 MERGE_BELOW_SEC 就提交、重新開始累積。
    影片結尾若還有未提交的累積（沒有更多場景可以合併），併進前一個已提交的場景；
    如果連前一個都沒有（整支影片累積起來都不到門檻），就直接當一個場景保留。
    """
    merged: list[tuple[float, float]] = []
    buffer_start: float | None = None
    buffer_end: float | None = None

    for start, end in scenes:
        if buffer_start is None:
            buffer_start, buffer_end = start, end
        else:
            buffer_end = end
        if buffer_end - buffer_start >= MERGE_BELOW_SEC:
            merged.append((buffer_start, buffer_end))
            buffer_start, buffer_end = None, None

    if buffer_start is not None:
        if merged:
            last_start, _ = merged.pop()
            merged.append((last_start, buffer_end))
        else:
            merged.append((buffer_start, buffer_end))

    return merged


def _split_long_scenes(scenes: list[tuple[float, float]]) -> list[NormalizedScene]:
    """長度超過 SPLIT_ABOVE_SEC 的場景均分成 n 段，n 依 SPLIT_TARGET_SEC 決定。

    n 會往下修正到每段長度都不低於 MERGE_BELOW_SEC（下限）為止；如果連切成
    2 段都會低於下限，就保留原始的單一（超長）片段，不勉強切開——寧可片段
    偶爾超過上限，也不要低於下限（下限存在的目的是避免 VLM／OCR 只看到一
    小段畫面，這比切出來的片段稍微超長更傷）。只有當 SPLIT_ABOVE_SEC >=
    2 × MERGE_BELOW_SEC 時，切 2 段才保證兩段都不低於下限；目標帶越窄
    （上限越接近下限的 2 倍以下），落在「切了會低於下限、不切又超過上限」
    這個死區（SPLIT_ABOVE_SEC ~ 2×MERGE_BELOW_SEC 之間）的場景就越多，會
    保留成超長片段，細節與真實影片實測數字見
    docs/02-technical-decisions.md#場景切分。

    回傳 NormalizedScene 而不是純 tuple：每段都帶上 `source_raw_duration`
    （這段場景切分前的原始長度），沒被切過的場景 `source_raw_duration`
    就是自己的長度，見 NormalizedScene 說明。
    """
    result: list[NormalizedScene] = []
    for start, end in scenes:
        length = end - start
        if length <= SPLIT_ABOVE_SEC:
            result.append(NormalizedScene(start, end, source_raw_duration=length))
            continue
        piece_count = max(1, round(length / SPLIT_TARGET_SEC))
        while piece_count > 1 and length / piece_count < MERGE_BELOW_SEC:
            piece_count -= 1
        piece_length = length / piece_count
        result.extend(
            NormalizedScene(start + i * piece_length, start + (i + 1) * piece_length, source_raw_duration=length)
            for i in range(piece_count)
        )
    return result


def _normalize_scene_lengths(scenes: list[tuple[float, float]]) -> list[NormalizedScene]:
    return _split_long_scenes(_merge_short_scenes(scenes))


def _build_detectors() -> list:
    """回傳一組全新的 detector 實例；SceneManager 會持有並消耗掉，不可重用同一個實例。"""
    return [ContentDetector(), AdaptiveDetector()]


def _run_detection(video_path: Path, backend: str):
    video = open_video(str(video_path), backend=backend)
    manager = SceneManager()
    for detector in _build_detectors():
        manager.add_detector(detector)
    manager.detect_scenes(video=video)
    return manager.get_scene_list()


def detect_scenes_with_progress(
    video_path: Path,
    duration_sec: float,
    on_progress: Callable[[int], None] | None = None,
) -> list[NormalizedScene]:
    """場景切分，等待處理期間會依校準過的預估時間定期回報百分比
    （不是真的逐幀進度，PySceneDetect 沒有提供適合做平滑百分比的機制）。
    """
    is_av1 = _is_av1(video_path)
    backend = "pyav" if is_av1 else "opencv"
    ratio = _ESTIMATED_RATIO_PYAV if is_av1 else _ESTIMATED_RATIO_OPENCV
    estimated_total = max(_MIN_ESTIMATED_SEC, duration_sec * ratio)

    scenes = progress_estimation.run_with_estimated_progress(
        lambda: _run_detection(video_path, backend), estimated_total, on_progress
    )
    return _to_ranges(scenes, duration_sec)


def _to_ranges(scenes, duration_sec: float) -> list[NormalizedScene]:
    # 沒偵測到任何切換時，整支影片視為單一片段——這種情況也要正規化，
    # 不然完全靜態的長影片會變成一個涵蓋全片的巨大場景（VLM／本地 OCR
    # 都只看得到其中一小段畫面）。
    ranges = [(start.seconds, end.seconds) for start, end in scenes] if scenes else [(0.0, duration_sec)]
    return _normalize_scene_lengths(ranges)


def _is_av1(video_path: Path) -> bool:
    try:
        codec = media.run_ffprobe(
            [
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ]
        )
    except (subprocess.SubprocessError, OSError):
        # 讀不到編碼就當作不是 AV1（走比較快的 opencv backend），不讓整支分析
        # 失敗在一個「猜錯了頂多慢一點」的判斷上。
        return False
    return codec == "av1"
