"""分析 pipeline orchestrator：串起場景切分→ASR→逐片段 VLM→建立向量→寫入索引，
背景執行緒執行、透過 Queue 回報進度（由 services/job_manager.py 的 pump
thread 讀走、寫進 jobs 表）。

只呼叫 asr/vlm/embedding 模組暴露的 provider 無關介面，不直接碰 OpenAI SDK，
方便之後在各模組內部加入其他供應商實作。

_analyze_worker() 是整支流程的 orchestrator，呼叫下面幾個具名的
_run_*()／_write_segments() phase 函式，對應 Phase A~F 的邏輯區塊
（B~F 原本就有對應註解，A／音訊轉錄步驟原本沒有獨立標記，這次一併補上），
拆出來是為了每個階段的邏輯可以獨立閱讀，不是要改變流程本身。每個 phase 都
需要的三件事——這次分析的固定輸入（video_id／video_path／client）、進度回報、
累計花費與預算判斷——集中在 _AnalysisContext，phase 函式只收 `ctx` 加上自己
真正需要的參數（原本是把 `progress_queue` 一路傳下去、`total_cost` 進出每個
簽名手工穿線，新增一個 phase 就要記得同時處理三件事才不會漏）。

其中三組互不依賴的 phase 改成同時起跑縮短耗時（Tier 1 平行化，不改變任何
判斷邏輯／輸出結果，見 docs/02-technical-decisions.md#分析流程平行化）：
場景切分＋音訊轉錄（_run_scene_detection_and_transcription()）、Phase C
片段內三個 embedding（_embed_segment_texts()）、本地 OCR＋整理文件
（_run_local_ocr_and_document()）。其餘 phase 仍然照順序一個一個處理。

Phase B（VLM 逐場景畫面分析）另外做了 Tier 2 平行化：改成逐批次平行送出
（見 _run_vlm_phase() 與 docs/02-technical-decisions.md#分析流程平行化「Tier 2」）。
budget 檢查粒度從「每個場景後」放寬成「每個批次後」，是刻意接受的已知取捨；
批次平行會提高短時間內撞到 OpenAI rate limit 的機率，_describe_segment_with_retry()
補上重試機制，這是這次平行化的必要配套，不是額外功能。

**這個模組是套件的門面**（第五輪重構拆的，見 docs/refactor-board.html）：

    events.py   進度／結果／錯誤三個 dataclass，與 job_manager 的契約（葉）
    context.py  _AnalysisContext 與 BUDGET_USD
    phases.py   六個 phase、它們的常數與中間資料列
    worker.py   執行緒入口、流程順序、長度上限

依賴是單向的 events ← context ← phases ← worker，沒有環。對外的名字（
`analyzer.start_analysis`／`analyzer.BUDGET_USD`／三個事件 dataclass 等）
全部在這裡再匯出，呼叫端的 import 路徑跟拆分前完全一樣。

`db`／`asr`／`vlm` 這些協作者模組也照舊掛在這裡（`analyzer.db` 之類的路徑拆分
前就存在，測試也一直是這樣 patch 的）。patch 它們的屬性等於 patch 那個模組本身，
跟 analyzer 怎麼拆無關。

真正跟拆分有關的是 patch **analyzer 自己的屬性**時，位址要指向**讀那個名字的模組**——例如
`analyzer.worker.get_client`、`analyzer.phases.VLM_BATCH_SIZE`、
`analyzer.context.BUDGET_USD`。patch 到門面上不會生效（子模組讀的是自己的
global），這是 Python 模組屬性的既有行為，不是這次拆分引入的問題。
"""
from __future__ import annotations

from ... import db  # noqa: F401
from .. import asr, embedding, media, ocr_service, scene_detect, vlm  # noqa: F401
from .. import document as document_pipeline  # noqa: F401
from .. import summary as summary_pipeline  # noqa: F401
from . import context, events, phases, worker
from .context import BUDGET_USD, _AnalysisContext
from .events import AnalysisError, AnalysisProgress, AnalysisResult
from .phases import (
    FRAME_FRACTIONS,
    VLM_BATCH_SIZE,
    VLM_RATE_LIMIT_MAX_RETRIES,
    VLM_RATE_LIMIT_RETRY_WAIT_SEC,
    _DocumentPhaseOutput,
    _describe_segment_with_retry,
    _embed_segment_texts,
    _run_document_phase,
    _run_embedding_phase,
    _run_local_ocr,
    _run_local_ocr_and_document,
    _run_scene_detection,
    _run_scene_detection_and_transcription,
    _run_transcription,
    _run_vlm_phase,
    _SceneAnalysisRow,
    _SegmentRow,
    _write_segments,
)
from .worker import (
    MAX_DURATION_SEC,
    _analyze_worker,
    _run_analysis,
    is_within_duration_limit,
    start_analysis,
)

__all__ = [
    "AnalysisError",
    "AnalysisProgress",
    "AnalysisResult",
    "BUDGET_USD",
    "FRAME_FRACTIONS",
    "MAX_DURATION_SEC",
    "VLM_BATCH_SIZE",
    "context",
    "events",
    "is_within_duration_limit",
    "phases",
    "start_analysis",
    "worker",
]
