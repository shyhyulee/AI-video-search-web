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
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI, RateLimitError

from .. import db
from . import asr, embedding, ocr_service, scene_detect, vlm
from . import document as document_pipeline
from . import summary as summary_pipeline
from .openai_client import get_client

logger = logging.getLogger(__name__)

# 原本 $0.20，VLM 條件式多幀取樣上線後調高到 $0.30：用真實 7 支影片費用
# 反推，溶接式排行榜內容（觸發率 88~98%）換算後單支費用最高約 $0.2015，
# 超過原本上限；$0.30 讓這類影片留有餘裕，見
# docs/02-technical-decisions.md「VLM 條件式多幀取樣」。
BUDGET_USD = 0.80
# 原本 20 分鐘，2026-08-26 依使用者要求放寬到 1 小時；BUDGET_USD 同時由 $0.30
# 調到 $0.80 配合它。$0.80 是依實測 10 支影片（1.0~18.6 分鐘）反推的：
#
#   成本 ≈ ASR($0.006/分，asr.PRICE_PER_MINUTE_USD 固定值)
#          + 每片段 $0.00050~$0.00090（VLM＋embedding＋摘要，實測區間）
#
# 60 分鐘影片：實測密度下平均約 $0.55、最壞觀測費率約 $0.70。片段密度不會失控
# ——scene_detect 會把場景正規化成 8~12 秒（MERGE_BELOW_SEC／SPLIT_ABOVE_SEC），
# 所以密度的結構上限是 60/8 = 7.5 個/分，快剪內容也一樣。用「結構上限密度 ×
# 最高觀測每片段費率」算出的最壞情況是 $0.765，仍在 $0.80 內（餘裕僅 4.6%）。
#
# 注意：$0.80 不是 60 分鐘影片真正的瓶頸。asr._extract_audio() 固定輸出 64kbps
# 單聲道 mp3（實測 7,998 bytes/s），Whisper 的 25MB 上傳上限換算後約 52~55
# 分鐘，且 ASR 例外會讓整支分析失敗（不是略過字幕）。所以超過約 52 分鐘的影片
# 會先卡在 ASR，不會走到預算判斷。完整推導與實測資料見 docs/11 §8.12。
MAX_DURATION_SEC = 60 * 60

# source_raw_duration（scene_detect.NormalizedScene，這個場景所屬、切分前
# 的原始長度）超過這個秒數，代表場景偵測器在這段長度裡完全沒抓到任何切點，
# 觸發多幀 VLM 取樣（見下方 MULTI_FRAME_FRACTIONS）而不是預設中點單幀。
# 校準過程：全 corpus 537 個既有場景重跑一次原始場景偵測比較 12s／20s 兩個
# 門檻，20s 對連續動作型內容（NBA／BMW／動物／棒球）有實質過濾效果（觸發率
# 18.5%→7.7%），對溶接式排行榜內容幾乎沒差（原始場景長度本來就遠超過
# 20 秒）。只用這批 7 支影片校準過，不是嚴謹調校的結果，見
# docs/02-technical-decisions.md「VLM 條件式多幀取樣」。
MULTI_FRAME_TRIGGER_SEC = 20.0

# 觸發後取兩幀，分別在片段 30%／70% 時間點——不是中點單幀，讓兩幀盡量分散
# 到片段前後段，各自代表性更高。幀數與位置沒有掃過其他選項（例如 3 幀／
# 25%-50%-75%），已知在最極端案例（一個場景塞了 4 張快速切換的名卡）只能
# 抓到其中 2 張，不保證完全覆蓋，見 docs/02-technical-decisions.md 已知限制。
MULTI_FRAME_FRACTIONS = (0.3, 0.7)

# Phase B 批次平行的批次大小。原本 =5 的推導依據（見下方保留的舊註解）
# 其實用錯了 gpt-4o-mini「low」解析度圖片的 token 成本——假設固定 85
# tokens（一般 gpt-4o 的公式），但實測單幀呼叫真實 prompt tokens 是 2960
# （圖片本身就佔了約 2880 tokens，比假設值高了一個數量級），比原本估的
# 「單次呼叫最差情況約 550 tokens」高出約 5.4 倍。這個落差沒有造成實際問題
# （Tier 2 上線後的 20 場景測試 0 次撞 rate limit），研判是因為真實 API
# 呼叫的延遲本身就有節流效果，不是 token 預算公式在把關。條件式多幀上線後
# 觸發場景的 call 用量再乘上約 1.9 倍（2 幀），同一批次如果剛好混到多個
# 觸發場景，風險又更高一階；沒有足夠把握重新推導一個精確數字，保守把批次
# 大小降到 3（原本的約 60%），實際會不會撞 429 要等真的重新分析 video 1
# 才能驗證，見 docs/02-technical-decisions.md「VLM 條件式多幀取樣」。
#
# 舊註解（batch_size=5 時的推導依據，已知有誤，保留供對照）：用帳號實測
# 撞過的 gpt-4o-mini TPM 上限（200,000/分鐘）回推：單次呼叫最差情況約
# 550 tokens（含輸出上限），只讓 Phase B 自己的併發用量控制在上限的一半
# 以內（~100,000 tokens/分鐘）換算出保守起點，見
# docs/02-technical-decisions.md#分析流程平行化「Tier 2」。
VLM_BATCH_SIZE = 3

# 批次平行後同一批內同時打多個請求，撞到 429 的機率比循序執行時更高；
# 帳號已經實測撞過 TPM 上限，這裡的等待秒數／重試次數是合理預設，不是
# 實測校準值。
VLM_RATE_LIMIT_MAX_RETRIES = 2
VLM_RATE_LIMIT_RETRY_WAIT_SEC = 8.0


@dataclass
class AnalysisProgress:
    stage: str
    detail: str = ""


@dataclass
class AnalysisResult:
    video_id: int
    segment_count: int
    cost_usd: float
    partial: bool
    vlm_failed_count: int = 0


@dataclass
class AnalysisError:
    video_id: int
    message: str


@dataclass
class _SceneAnalysisRow:
    """Phase B（VLM 逐片段畫面分析）單一場景的輸出，Phase C（建立向量）逐筆
    處理。用具名 dataclass、一個場景一筆，不是好幾個平行陣列——避免「新增一
    個欄位要同步改宣告／Phase B 的 append／Phase C 的 zip 解構三處，任一處
    漏改都是不會報錯但資料錯位」的風險，跟 _SegmentRow 採用同一個理由。
    """
    start_sec: float
    end_sec: float
    transcript_text: str
    description: str
    ocr_text: str | None
    scores: asr.SegmentScores
    frame_count: int  # 這個片段的畫面描述用了幾張畫面（1=單幀，2=條件式多幀）


@dataclass
class _SegmentRow:
    """Phase C（建立向量）的輸出，Phase D（`_write_segments()`，寫入 segments 表）
    與 Phase E（`_run_local_ocr()`，判斷哪些場景還缺 OCR 文字）逐一讀取；用
    具名 dataclass 取代先前的無型別 9-tuple，避免位置索引（例如本地 OCR 用來
    判斷要不要複掃的欄位）失去意義、欄位順序一改就悄悄壞掉不會有型別檢查提醒。
    """
    start_sec: float
    end_sec: float
    transcript_text: str
    description: str
    ocr_text: str | None
    transcript_embedding: bytes | None
    visual_embedding: bytes | None
    ocr_embedding: bytes | None
    scores: asr.SegmentScores
    frame_count: int


class _AnalysisContext:
    """一次分析從頭到尾共用的東西：固定的輸入（video_id／video_path／video_title／
    client），加上兩個橫切關注點——進度回報與累計花費／預算判斷。

    抽出來的理由：這兩件事原本靠參數手工穿過每個 phase 函式（`progress_queue`
    一路往下傳、`total_cost` 進出每個簽名），新增或調整一個 phase 就要同時記得
    三件事——更新 videos.pipeline_stage、送出 AnalysisProgress、累加並回傳花費
    ——漏掉任何一件都不會報錯，只會安靜地少一個進度或少算一筆錢。
    """

    def __init__(
        self,
        video_id: int,
        video_path: Path,
        client: OpenAI,
        progress_queue: "queue.Queue[object]",
        video_title: str = "",
        initial_cost: float = 0.0,
    ) -> None:
        self.video_id = video_id
        self.video_path = video_path
        # Phase F 整理文件時要把影片標題放進 prompt（`document.generate_document()`
        # 的必要輸入）。放進 context 而不是一路傳參數，理由跟 video_path 一樣：
        # 它是「這次分析的固定輸入」，不是某個 phase 算出來的中間結果。
        self.video_title = video_title
        self.client = client
        self._progress_queue = progress_queue
        self._initial_cost = initial_cost
        self._cost = initial_cost
        # 好幾個 phase 是在背景執行緒裡累加花費（音訊轉錄、本地 OCR），用鎖
        # 讓 spend() 本身就是安全的，呼叫端不用各自想同步問題。
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 花費與預算
    # ------------------------------------------------------------------
    @property
    def total_cost(self) -> float:
        with self._lock:
            return self._cost

    @property
    def spent(self) -> float:
        """這個 context 自己花掉的金額（不含起始基準），給 merge_branch() 用。"""
        with self._lock:
            return self._cost - self._initial_cost

    def spend(self, amount: float) -> None:
        with self._lock:
            self._cost += amount

    @property
    def over_budget(self) -> bool:
        return self.total_cost > BUDGET_USD

    # ------------------------------------------------------------------
    # 進度回報
    # ------------------------------------------------------------------
    def enter_stage(self, stage: str) -> None:
        """階段切換：同時寫進 videos.pipeline_stage（重新整理頁面也看得到目前
        跑到哪）與送出 AnalysisProgress 事件（Job Manager 的 pump thread 會把它
        寫進 jobs 表）。兩者用同一段文字。"""
        db.update_video_status(self.video_id, db.STATUS_ANALYZING, stage)
        self._progress_queue.put(AnalysisProgress(stage=stage))

    def report_progress(self, stage: str, detail: str, *, persist_as: str | None = None) -> None:
        """階段內的百分比回報。預設只送事件、不寫 DB——這種事件很密集（場景
        切分／音訊轉錄／本地 OCR 都是），沒必要每次都寫一次資料庫。

        Phase B（畫面分析）是唯一會順便更新 pipeline_stage 的，而且兩邊的文字
        格式本來就不一樣（DB 寫「畫面分析 40%」一整串，事件是 stage／detail
        分開兩欄），所以用 persist_as 明確指定要寫進 DB 的字串，不假設兩者相同。
        """
        if persist_as is not None:
            db.update_video_status(self.video_id, db.STATUS_ANALYZING, persist_as)
        self._progress_queue.put(AnalysisProgress(stage=stage, detail=detail))

    # ------------------------------------------------------------------
    # 平行分支
    # ------------------------------------------------------------------
    def budget_branch(self) -> "_AnalysisContext":
        """給「互相平行、而且各自都要判斷預算」的 phase 用：回傳一個從目前金額
        起算、獨立累加的 context。兩個分支互相看不到對方的花費——這正是
        _run_local_ocr_and_document() 既有的取捨（兩者合計可能比 BUDGET_USD 多出
        一點點），用 budget_branch() 把它變成明講的機制而不是靠傳參數傳出來的
        副作用。跑完用 merge_branch() 把增量併回主帳。
        """
        return _AnalysisContext(
            video_id=self.video_id,
            video_path=self.video_path,
            client=self.client,
            progress_queue=self._progress_queue,
            video_title=self.video_title,
            initial_cost=self.total_cost,
        )

    def merge_branch(self, branch: "_AnalysisContext") -> None:
        """把分支自己花掉的增量併回主帳（不是把分支的總額覆蓋上來）。"""
        self.spend(branch.spent)


def is_within_duration_limit(duration_sec: int | None) -> bool:
    return duration_sec is not None and duration_sec <= MAX_DURATION_SEC


def start_analysis(video_id: int, progress_queue: "queue.Queue[object]") -> threading.Thread:
    thread = threading.Thread(target=_analyze_worker, args=(video_id, progress_queue), daemon=True)
    thread.start()
    return thread


def _analyze_worker(video_id: int, progress_queue: "queue.Queue[object]") -> None:
    """分析執行緒的最外層。唯一的職責是保證「不管發生什麼事，都會送出剛好一個
    終端事件」（AnalysisResult 或 AnalysisError）。

    這件事是硬需求不是防禦性程式碼：job_manager 的 pump thread 用
    `queue.get()` 等終端事件、收到才會 break 並釋放分析 slot。少送一次，
    pump 就永遠停在那裡、slot 永遠不會釋放，**之後每一支影片的分析都會卡在
    queued，只能重啟伺服器**。實際踩得到的路徑是 `_run_analysis()` 進到自己
    的 try 之前那幾行（讀影片紀錄、更新狀態、`get_client()`——缺 API 金鑰時
    OpenAI() 會直接拋）。
    """
    try:
        _run_analysis(video_id, progress_queue)
    except Exception as exc:
        # 走到這裡代表 _run_analysis() 內層的 except 沒接到（例如例外發生在它
        # 自己的 try 之前，或連內層處理本身都失敗了）。訊息用最原始的形式，
        # 不假設任何前置資料（例如影片標題）拿得到。
        logger.error("分析執行緒異常結束（video_id=%s）：%s", video_id, exc, exc_info=True)
        try:
            db.update_video_status(video_id, db.STATUS_FAILED, f"分析失敗：{exc}")
        except Exception:
            logger.error("連標記分析失敗都寫不進資料庫（video_id=%s）", video_id, exc_info=True)
        progress_queue.put(AnalysisError(video_id=video_id, message=str(exc)))


def _run_analysis(video_id: int, progress_queue: "queue.Queue[object]") -> None:
    video = db.get_video(video_id)
    if video is None:
        progress_queue.put(AnalysisError(video_id=video_id, message="找不到這支影片的紀錄"))
        return

    video_path = Path(video.file_path)
    if not video_path.exists():
        db.update_video_status(video_id, db.STATUS_FAILED, "找不到影片檔案")
        progress_queue.put(AnalysisError(video_id=video_id, message="找不到影片檔案"))
        return

    # 這個階段切換刻意不透過 ctx：建立 context 需要 client，而 get_client()
    # 必須留在「場景切分中」寫進 DB／送出事件之後——維持重構前的順序，
    # get_client() 失敗（例如缺 API 金鑰）時的可觀察狀態才會跟以前一致。
    db.update_video_status(video_id, db.STATUS_ANALYZING, "場景切分中")
    progress_queue.put(AnalysisProgress(stage="場景切分中"))

    ctx = _AnalysisContext(
        video_id=video_id, video_path=video_path, client=get_client(), progress_queue=progress_queue,
        video_title=video.title,
    )

    try:
        duration_sec = float(video.duration_sec or 0)

        scenes, transcribe_result = _run_scene_detection_and_transcription(ctx, duration_sec)

        scene_rows, vlm_failed_count = _run_vlm_phase(ctx, scenes, transcribe_result)

        segment_rows = _run_embedding_phase(ctx, scene_rows)

        segment_ids = _write_segments(ctx, segment_rows)

        segment_count = len(segment_rows)
        partial = segment_count < len(scenes)
        # 預算截斷跟「單一場景 VLM 失敗」是兩件互相獨立的事，各自有各自的訊息，
        # 可能同時發生，用「；」串起來——不能共用同一個 partial 判斷或同一句
        # 文字，不然使用者會看到誤導的原因（例如明明是內容審查拒絕，卻顯示
        # 「已達預算上限」），見 docs/00-overview.md#33-整體資料流。
        stage_notes = []
        if partial:
            stage_notes.append(f"已達預算上限（US${BUDGET_USD:.2f}），完成 {segment_count}/{len(scenes)} 片段")
        if vlm_failed_count:
            stage_notes.append(f"{vlm_failed_count} 個場景畫面分析失敗，已略過（保留字幕，無畫面描述）")
        pipeline_stage = "；".join(stage_notes) or None

        # Phase E（本地 OCR）／Phase F（整理文件與摘要）互不依賴，同時起跑縮短
        # 耗時，見 docs/02-technical-decisions.md#分析流程平行化。本地 OCR 整段
        # 失敗只記 log、不能讓已經成功的分析結果被判定為失敗，見
        # docs/02-technical-decisions.md#vlm-與-ocr。
        document_output = _run_local_ocr_and_document(ctx, segment_rows, segment_ids)

        db.mark_video_analyzed(
            video_id=video_id,
            segment_count=segment_count,
            cost_usd=ctx.total_cost,
            asr_model=asr.MODEL_NAME,
            vlm_model=vlm.MODEL_NAME,
            embedding_model=embedding.MODEL_NAME,
            pipeline_stage=pipeline_stage,
            # 文件的花費已經透過 ctx.spend() 進了上面的 cost_usd，所以文件三欄
            # 跟著這一句一起寫，不能改呼叫 db.update_video_document()——那支是
            # 累加語意，會把同一次呼叫的錢算兩次。
            summary=document_output.summary,
            summary_model=document_output.summary_model,
            document_json=document_output.document_json,
            document_type=document_output.document_type,
            document_model=document_output.document_model,
        )
        progress_queue.put(
            AnalysisResult(
                video_id=video_id, segment_count=segment_count, cost_usd=ctx.total_cost, partial=partial,
                vlm_failed_count=vlm_failed_count,
            )
        )

    except Exception as exc:  # 分析過程各種例外統一攔截，避免背景執行緒讓整支程式崩潰
        current = db.get_video(video_id)  # 必須在下面 STATUS_FAILED 覆蓋 pipeline_stage 之前先讀
        stage_label = (current.pipeline_stage if current else None) or "分析"
        logger.error("「%s」在「%s」階段分析失敗：%s", video.title, stage_label, exc, exc_info=True)
        db.update_video_status(video_id, db.STATUS_FAILED, f"分析失敗：{exc}")
        progress_queue.put(AnalysisError(video_id=video_id, message=str(exc)))


def _run_scene_detection(ctx: _AnalysisContext, duration_sec: float) -> list[scene_detect.NormalizedScene]:
    """Phase A：場景切分。"""

    def _on_scene_progress(percent: int) -> None:
        ctx.report_progress("場景切分中", f"{percent}%（預估）")

    return scene_detect.detect_scenes_with_progress(
        ctx.video_path, duration_sec, on_progress=_on_scene_progress
    )


def _run_transcription(ctx: _AnalysisContext, duration_sec: float) -> asr.TranscribeResult:
    """整支影片的音訊轉錄（原本無獨立 Phase 字母，緊接在 Phase A 場景切分之後、
    Phase B 逐片段畫面分析之前）。花費直接記進 ctx。"""
    ctx.enter_stage("音訊轉錄中")

    def _on_transcribe_progress(percent: int) -> None:
        ctx.report_progress("音訊轉錄中", f"{percent}%（預估）")

    transcribe_result = asr.transcribe_with_progress(
        ctx.client, ctx.video_path, duration_sec, on_progress=_on_transcribe_progress
    )
    ctx.spend(transcribe_result.cost_usd)
    ctx.enter_stage("音訊轉錄完成")

    return transcribe_result


def _run_scene_detection_and_transcription(
    ctx: _AnalysisContext, duration_sec: float
) -> tuple[list[scene_detect.NormalizedScene], asr.TranscribeResult]:
    """Phase A（場景切分）跟音訊轉錄互不依賴——一個看畫面、一個聽聲音，改成
    同時起跑縮短總耗時；`_run_scene_detection()`／`_run_transcription()` 本身
    不動，只是呼叫順序從循序改成併發，見
    docs/02-technical-decisions.md#分析流程平行化。
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        transcribe_future = pool.submit(_run_transcription, ctx, duration_sec)
        # 場景切分萬一拋例外，離開這個 with 區塊時 executor 的
        # shutdown(wait=True) 仍然會等轉錄跑完——不會留下一個脫離這個函式
        # 生命週期、還在背景花錢的 API 呼叫。
        scenes = _run_scene_detection(ctx, duration_sec)

    # 取轉錄結果刻意排在場景切分「之後」而且不放進 finally：場景切分失敗時
    # 例外會在上一行就往外拋，根本不會走到這裡，往外傳的因此一定是場景切分
    # 自己的例外。放進 finally 的話，轉錄如果也失敗就會反過來蓋掉它，使用者
    # 看到的失敗原因會是錯的（有測試鎖住這個情況）。
    return scenes, transcribe_future.result()


def _frame_fractions_for(scene: scene_detect.NormalizedScene) -> tuple[float, ...]:
    """依 NormalizedScene.source_raw_duration 決定這個場景要用單幀還是條件式
    多幀取樣，見 MULTI_FRAME_TRIGGER_SEC／MULTI_FRAME_FRACTIONS 旁的說明。
    拆成獨立函式方便不用真的跑 VLM／場景偵測就能測門檻判斷本身。
    """
    if scene.source_raw_duration > MULTI_FRAME_TRIGGER_SEC:
        return MULTI_FRAME_FRACTIONS
    return vlm.DEFAULT_FRAME_FRACTIONS


def _run_vlm_phase(
    ctx: _AnalysisContext,
    scenes: list[scene_detect.NormalizedScene],
    transcribe_result: asr.TranscribeResult,
) -> tuple[list[_SceneAnalysisRow], int]:
    """Phase B：逐片段畫面分析（VLM，成本主要來源）。場景分批平行送出縮短耗時
    （Tier 2 平行化，見 docs/02-technical-decisions.md#分析流程平行化）：同一批
    內用 thread pool 並發呼叫，用「送出順序」收集結果（不是完成順序），確保
    回傳的 list[_SceneAnalysisRow] 順序仍然精確對應 scenes 的順序；budget
    檢查從「每個場景後」放寬成「每個批次後」。

    每個場景先依 `_frame_fractions_for()` 判斷要不要觸發條件式多幀取樣（見
    docs/02-technical-decisions.md「VLM 條件式多幀取樣」），再送進 VLM。

    單一場景的 VLM 呼叫失敗（內容審查拒絕、API 錯誤等 rate limit 以外的例外）
    只跳過那個場景的畫面描述／OCR，不讓整支分析失敗，比照 Phase E／F 的失敗
    隔離原則；字幕不受影響，因為是從已經抓好的逐字稿本機切出來的，跟 VLM
    呼叫成不成功無關。失敗場景數用回傳值 vlm_failed_count 往外傳，讓呼叫端
    可以把這個原因獨立顯示給使用者，不能跟預算截斷共用同一個訊息（見
    docs/00-overview.md#33-整體資料流）。失敗場景的 cost_usd 一律算 0——內容審查
    拒絕的呼叫實務上可能還是有算到一點輸入 token 費用，但例外是在讀到
    response.usage 之前就被拋出，程式拿不到那個數字，這是已知、暫不處理的
    誤差；失敗場景的 frame_count 記 0（沒有任何畫面真的產生描述）。
    """
    scene_rows: list[_SceneAnalysisRow] = []
    vlm_failed_count = 0

    completed = 0

    def _report_progress() -> None:
        nonlocal completed
        completed += 1
        percent = round(completed / len(scenes) * 100)
        ctx.report_progress("畫面分析", f"{percent}%", persist_as=f"畫面分析 {percent}%")

    with ThreadPoolExecutor(max_workers=VLM_BATCH_SIZE) as pool:
        for batch_start in range(0, len(scenes), VLM_BATCH_SIZE):
            batch = scenes[batch_start : batch_start + VLM_BATCH_SIZE]
            futures = [
                pool.submit(
                    _describe_segment_with_retry,
                    ctx.client, ctx.video_path, scene.start_sec, scene.end_sec, _frame_fractions_for(scene),
                )
                for scene in batch
            ]

            for scene, future in zip(batch, futures):
                start_sec, end_sec = scene.start_sec, scene.end_sec
                try:
                    describe_result = future.result()
                except Exception:
                    logger.warning(
                        "VLM 畫面分析失敗，跳過這個場景（%.1fs~%.1fs），保留字幕、不產生畫面描述",
                        start_sec, end_sec, exc_info=True,
                    )
                    describe_result = None
                    vlm_failed_count += 1

                _report_progress()

                if describe_result is not None:
                    ctx.spend(describe_result.cost_usd)
                scene_rows.append(
                    _SceneAnalysisRow(
                        start_sec=start_sec,
                        end_sec=end_sec,
                        transcript_text=asr.text_for_range(transcribe_result.segments, start_sec, end_sec),
                        description=describe_result.description if describe_result else "",
                        ocr_text=describe_result.ocr_text if describe_result else None,
                        scores=asr.scores_for_range(transcribe_result.segments, start_sec, end_sec),
                        frame_count=describe_result.frame_count if describe_result else 0,
                    )
                )

            if ctx.over_budget:
                break

    return scene_rows, vlm_failed_count


def _describe_segment_with_retry(
    client: OpenAI, video_path: Path, start_sec: float, end_sec: float, frame_fractions: tuple[float, ...]
) -> vlm.DescribeResult:
    """包一層 rate limit 重試。批次平行送出後，同一批內同時打多個請求，撞到
    OpenAI 429（gpt-4o-mini TPM 上限）的機率比循序執行時更高——帳號實測撞過
    這個上限（見 docs/02-technical-decisions.md#分析流程平行化「Tier 2」），
    這裡補上重試，不然平行化反而會讓整支影片分析比現在更容易失敗。非
    rate-limit 的例外不重試，直接往外拋，維持跟現有版本一樣的失敗語意。
    """
    attempt = 0
    while True:
        try:
            return vlm.describe_segment(client, video_path, start_sec, end_sec, frame_fractions)
        except RateLimitError:
            attempt += 1
            if attempt > VLM_RATE_LIMIT_MAX_RETRIES:
                raise
            logger.warning(
                "VLM 呼叫撞到 rate limit，%.0f 秒後重試（第 %d/%d 次）",
                VLM_RATE_LIMIT_RETRY_WAIT_SEC, attempt, VLM_RATE_LIMIT_MAX_RETRIES,
            )
            time.sleep(VLM_RATE_LIMIT_RETRY_WAIT_SEC)


def _run_embedding_phase(ctx: _AnalysisContext, scene_rows: list[_SceneAnalysisRow]) -> list[_SegmentRow]:
    """Phase C：建立向量（字幕、畫面描述、OCR 文字分開 embed）。同一片段內的三個
    embedding 互相獨立，用 thread pool 平行送出縮短耗時；片段仍然照原順序一個一個
    處理，budget 檢查時機（一個片段的三個 embedding 都做完才檢查一次）不變，見
    docs/02-technical-decisions.md#分析流程平行化。

    字幕疑似是幻覺時不建立字幕 embedding，避免污染搜尋；`segments.transcript`
    仍然照實際 Whisper 輸出寫入，不隱藏原始內容，只是不讓它可被搜尋到，見
    docs/02-technical-decisions.md#asrwhisper-幻覺字幕過濾。兩種互補的判斷：模式 A
    （asr.is_hallucinated_transcript()，no_speech_prob 偏高）逐場景判斷；
    模式 B（asr.find_repetitive_transcript_indices()，連續場景被同一個詞
    主導）跨場景判斷，要先對整支影片的字幕算一次。
    """
    ctx.enter_stage("建立向量中")

    repetitive_indices = asr.find_repetitive_transcript_indices(
        [row.transcript_text for row in scene_rows]
    )

    segment_rows: list[_SegmentRow] = []
    for index, row in enumerate(scene_rows):
        is_hallucinated = asr.is_hallucinated_transcript(row.scores) or index in repetitive_indices
        transcript_for_embedding = row.transcript_text if row.transcript_text and not is_hallucinated else None
        embed_results = _embed_segment_texts(
            ctx.client, transcript=transcript_for_embedding, visual=row.description, ocr=row.ocr_text
        )

        # 三個模態的處理完全一樣（累加花費＋編碼成 bytes），照固定順序跑一次
        # 迴圈；沒有 embed 到的模態就不會出現在 blobs 裡，取值是 None。
        blobs: dict[str, bytes] = {}
        for kind in ("transcript", "visual", "ocr"):
            embed_result = embed_results.get(kind)
            if embed_result is None:
                continue
            ctx.spend(embed_result.cost_usd)
            blobs[kind] = embedding.encode_embedding(embed_result.vector)

        segment_rows.append(
            _SegmentRow(
                start_sec=row.start_sec,
                end_sec=row.end_sec,
                transcript_text=row.transcript_text,
                description=row.description,
                ocr_text=row.ocr_text,
                transcript_embedding=blobs.get("transcript"),
                visual_embedding=blobs.get("visual"),
                ocr_embedding=blobs.get("ocr"),
                scores=row.scores,
                frame_count=row.frame_count,
            )
        )

        if ctx.over_budget:
            break

    return segment_rows


def _embed_segment_texts(
    client: OpenAI, *, transcript: str | None, visual: str | None, ocr: str | None
) -> dict[str, embedding.EmbedResult]:
    """把一個片段裡存在的文字（字幕／畫面描述／OCR）平行送出 embedding 呼叫，
    回傳 {種類: EmbedResult}；呼叫端逐一累加花費，跟循序呼叫的結果完全一樣，
    只是三個獨立的網路呼叫改成同時發生。"""
    texts = {kind: text for kind, text in (("transcript", transcript), ("visual", visual), ("ocr", ocr)) if text}
    if not texts:
        return {}
    if len(texts) == 1:
        kind, text = next(iter(texts.items()))
        return {kind: embedding.embed_text(client, text)}

    with ThreadPoolExecutor(max_workers=len(texts)) as pool:
        futures = {kind: pool.submit(embedding.embed_text, client, text) for kind, text in texts.items()}
        return {kind: future.result() for kind, future in futures.items()}


def _write_segments(ctx: _AnalysisContext, segment_rows: list[_SegmentRow]) -> list[int]:
    """Phase D：把所有片段一次寫入 segments 表，回傳依序對應的 segment_id 清單。

    寫入前先清掉這支影片既有的片段。第一次分析時是沒有作用的 no-op；重新分析
    時它是「換掉舊索引」的那一刻——舊片段刻意留到這裡才刪，影片在重新分析的
    整段期間都還搜得到舊結果，而不是變成一支查不到東西的空殼。

    刪除與後面的 insert 不在同一個交易裡（`insert_segment()` 逐筆各自開連線），
    中間那個空窗只有寫入索引這幾百毫秒。真的在這中間爆掉的話，影片會被標記成
    failed、片段殘缺，跟既有的分析中途失敗是同一種結果，一樣靠重新分析復原。
    """
    ctx.enter_stage("寫入索引")
    db.clear_analysis_output(ctx.video_id)

    segment_ids: list[int] = []
    for row in segment_rows:
        segment_id = db.insert_segment(
            video_id=ctx.video_id,
            start_sec=row.start_sec,
            end_sec=row.end_sec,
            transcript=row.transcript_text or None,
            visual_description=row.description or None,
            ocr_text=row.ocr_text,
            transcript_embedding=row.transcript_embedding,
            visual_embedding=row.visual_embedding,
            ocr_embedding=row.ocr_embedding,
            asr_model=asr.MODEL_NAME,
            vlm_model=vlm.MODEL_NAME,
            embedding_model=embedding.MODEL_NAME,
            no_speech_prob=row.scores.no_speech_prob,
            avg_logprob=row.scores.avg_logprob,
            compression_ratio=row.scores.compression_ratio,
            vlm_frame_count=row.frame_count,
        )
        segment_ids.append(segment_id)
    return segment_ids


def _run_local_ocr(
    ctx: _AnalysisContext, segment_rows: list[_SegmentRow], segment_ids: list[int]
) -> None:
    """跑本地 OCR 掃描並把結果 embed、寫入 ocr_events；花費記進 ctx。
    只掃描 VLM-OCR 沒抓到文字的場景（segment_rows 的 ocr_text 為空）——本地 OCR
    的目的是補 VLM 單幀取樣漏掉的文字，不是重複掃描 VLM 已經找到文字的場景；
    用真實影片校準過，多數影片 VLM 已覆蓋 98~100% 場景，全面依序掃描只會把
    60 秒時間預算耗在早就有答案的前幾個場景上，反而讓真正需要補的場景完全
    沒被掃到（取樣策略的除錯過程見 docs/02-technical-decisions.md#vlm-與-ocr，
    尚未校準的參數見 docs/05-known-limitations-and-open-items.md）。
    本地辨識本身免費，但 embedding 是真的 OpenAI 呼叫，一樣受 BUDGET_USD 節制，
    避免本地 OCR 找到大量文字時不受控地把預算榨乾。
    """
    scenes_with_segment_id = [
        (row.start_sec, row.end_sec, segment_id)
        for row, segment_id in zip(segment_rows, segment_ids)
        if not row.ocr_text  # VLM-OCR 已經有文字的場景不用本地 OCR 複掃
    ]
    if not scenes_with_segment_id:
        return

    def _on_ocr_progress(percent: int) -> None:
        ctx.report_progress("本地 OCR 掃描中", f"{percent}%")

    ocr_events = ocr_service.scan_scenes(
        ctx.video_id, ctx.video_path, scenes_with_segment_id, on_progress=_on_ocr_progress
    )

    for event in ocr_events:
        if ctx.over_budget:
            break
        embed_result = embedding.embed_text(ctx.client, event.resolved_text)
        ctx.spend(embed_result.cost_usd)
        db.insert_ocr_event(
            video_id=event.video_id,
            segment_id=event.segment_id,
            start_sec=event.start_sec,
            end_sec=event.end_sec,
            frame_sec=event.frame_sec,
            raw_text=event.raw_text,
            resolved_text=event.resolved_text,
            confidence=event.confidence,
            bbox=json.dumps(event.bbox) if event.bbox else None,
            primary_engine=event.primary_engine,
            ocr_pipeline_version=ocr_service.PIPELINE_VERSION,
            embedding=embedding.encode_embedding(embed_result.vector),
        )


@dataclass
class _DocumentPhaseOutput:
    """Phase F 的產出，直接對應 `db.mark_video_analyzed()` 的五個可選欄位。

    全部是 None ＝這個 phase 什麼都沒產出（超支、沒有片段，或兩條路都失敗）；
    那種情況下 `mark_video_analyzed()` 的 COALESCE 會保留影片上原本的值。
    """
    summary: str | None = None
    summary_model: str | None = None
    document_json: str | None = None
    document_type: str | None = None
    document_model: str | None = None


def _run_document_phase(ctx: _AnalysisContext) -> _DocumentPhaseOutput:
    """Phase F：把全部片段整理成一份結構化文件，順便拿到摘要。

    **文件優先、摘要當退路**。原本這個 phase 只產摘要（`summary.generate_summary()`），
    文件要使用者自己去按「整理成文件」。兩者其實是同一件事的兩種輸出——
    `VideoDocument.overview` 的 prompt 就是照摘要的規格寫的，手動整理文件時本來
    就會一併覆蓋 `videos.summary`（見 `services/video_service.generate_document()`）
    ——所以這裡直接產文件，摘要當成它的副產品，省掉一次 LLM 呼叫。

    退路不能省：`videos.summary` 不只是顯示用的欄位，搜尋的影片層級篩選
    （pipeline/search/dense.py）與影片庫的主題分類（frontend lib/videoCategory.ts）
    都在讀它。文件整理失敗就整支沒有摘要的話，那支影片會在搜尋端被降權——那比
    「文件沒整理出來」嚴重得多，所以文件失敗時退回原本的 `generate_summary()`。

    兩條路都失敗只記 log、不影響其他分析結果，跟本地 OCR 同樣的失敗隔離原則；
    budget 已經超支就整段跳過，維持原本的行為。
    """
    ctx.enter_stage("整理文件與摘要中")

    if ctx.over_budget:
        return _DocumentPhaseOutput()

    fresh_segments = db.list_segments_for_video(ctx.video_id)
    if not fresh_segments:
        return _DocumentPhaseOutput()

    try:
        result = document_pipeline.generate_document(ctx.client, ctx.video_title, fresh_segments)
        ctx.spend(result.cost_usd)
        return _DocumentPhaseOutput(
            # summary_model 填文件的模型而不是 summary_pipeline 的：這段文字真的
            # 是它產的。手動整理文件那條路也是這樣寫的（db.update_video_document()
            # 把 document_model 同時寫進 summary_model），兩條路要一致。
            summary=result.document.overview,
            summary_model=document_pipeline.MODEL_NAME,
            document_json=result.document.model_dump_json(),
            document_type=result.document.doc_type,
            document_model=document_pipeline.MODEL_NAME,
        )
    except Exception:
        logger.warning("自動整理文件失敗，退回只產生摘要", exc_info=True)

    try:
        summary_result = summary_pipeline.generate_summary(ctx.client, fresh_segments)
        ctx.spend(summary_result.cost_usd)
        return _DocumentPhaseOutput(
            summary=summary_result.summary, summary_model=summary_pipeline.MODEL_NAME
        )
    except Exception:
        logger.warning("自動產生摘要也失敗，跳過（不影響其他分析結果）", exc_info=True)

    return _DocumentPhaseOutput()


def _run_local_ocr_and_document(
    ctx: _AnalysisContext, segment_rows: list[_SegmentRow], segment_ids: list[int]
) -> _DocumentPhaseOutput:
    """Phase E（本地 OCR）跟 Phase F（整理文件與摘要）互不依賴——F 只讀 Phase D
    寫入的 segments，不碰 Phase E 寫的 ocr_events 表——改成同時起跑縮短耗時。兩者
    各拿一個 `ctx.budget_branch()`：都以「進入這個函式那一刻」的金額當預算判斷
    基準，互相看不到對方的花費。`_run_document_phase()` 判斷要不要花這筆錢的依據
    因此是「本地 OCR 開始前」的金額而不是「跑完後」——極端情況下兩者合計可能讓
    總花費比 BUDGET_USD 多出一點點，是刻意接受的已知取捨，見
    docs/02-technical-decisions.md#分析流程平行化。
    """
    ocr_ctx = ctx.budget_branch()
    document_ctx = ctx.budget_branch()

    def _do_local_ocr() -> bool:
        """回傳有沒有成功跑完。本地 OCR 整段失敗只記 log、不往外拋——已經成功的
        分析結果不能因為它而被判定失敗，見
        docs/02-technical-decisions.md#vlm-與-ocr。"""
        ocr_ctx.enter_stage("本地 OCR 掃描中")
        try:
            _run_local_ocr(ocr_ctx, segment_rows, segment_ids)
            return True
        except Exception:
            logger.warning("本地 OCR 掃描階段失敗，跳過（不影響其他分析結果）", exc_info=True)
            return False

    with ThreadPoolExecutor(max_workers=1) as pool:
        ocr_future = pool.submit(_do_local_ocr)
        document_output = _run_document_phase(document_ctx)

    # 本地 OCR 整段失敗時不併回它的花費：維持重構前的語意（舊版把累加中的
    # 金額放在區域變數裡，例外一拋就整個丟掉，已經花掉的 embedding 錢不會被
    # 算進總額）。這其實是個小小的低估，但屬於行為，不在這次重構的範圍內改。
    if ocr_future.result():
        ctx.merge_branch(ocr_ctx)
    ctx.merge_branch(document_ctx)
    return document_output
