"""Job Manager：把 Category A（`downloader.start_download()`／
`analyzer.start_analysis()`）既有的「背景 thread ＋ queue.Queue 進度事件」
機制接上 `db.jobs` 表，讓 Web 版能在多個 HTTP request 之間查詢工作狀態，
並把 `docs/02-technical-decisions.md`（Tier 3）「同時只分析一支影片」的
隱性約束變成顯式機制。詳見 docs/09-web-ui-migration-plan.md 3.2 節。

不改動 `analyzer.py`／`downloader.py` 任何一行既有 threading／併發邏輯：
這裡只是起一條 pump thread，把「原本會被 Tk widget 讀走的 queue 事件」
改成「寫進 jobs 表」。

序列化設計：`job_type=analysis` 用一個 process 級的布林旗標＋鎖保證同時
只有一個在 `running`（等效於 `threading.Semaphore(1)`，但額外知道「下一個
該跑哪個 job」，所以用旗標＋DB 查詢實作，不是單純的 Semaphore 物件）；
`job_type=download` 不受限（不呼叫 OpenAI，不消耗 BUDGET_USD，序列化沒有
意義）；search／對話搜尋完全不進 jobs 表，見計畫文件 2.1 節「Category A / B」
的區分。
"""
from __future__ import annotations

import logging
import queue
import threading

from .. import db, downloader
from ..pipeline import analyzer
from . import video_service
from .errors import (
    DuplicateJobError,
    DurationLimitExceededError,
    InvalidJobStateError,
    InvalidUrlError,
    JobNotFoundError,
    VideoNotFoundError,
)

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 查詢
# ----------------------------------------------------------------------
def list_jobs(video_id: int | None = None) -> list[db.JobRecord]:
    return db.list_jobs(video_id=video_id)


def list_active_jobs(job_type: str | None = None) -> list[db.JobRecord]:
    """queued＋running 的工作，給前端重新整理後還原進度追蹤用。"""
    return db.list_active_jobs(job_type=job_type)


def get_job_or_raise(job_id: int) -> db.JobRecord:
    """讀取工作，找不到就丟 JobNotFoundError（API 層對映成 404）。

    API 端點原本各自 `db.get_job()` 之後再自己 `assert job is not None` 或
    自己丟例外——assert 在 `python -O` 下會整個消失、變成 AttributeError，
    而「找不到工作要回 404」本來就是服務層的規則，不是每個端點各自的判斷。
    """
    job = db.get_job(job_id)
    if job is None:
        raise JobNotFoundError(f"找不到工作 {job_id}")
    return job


# ----------------------------------------------------------------------
# 分析工作：序列化 dispatcher
# ----------------------------------------------------------------------
_analysis_lock = threading.Lock()
_analysis_running = False


def submit_analysis(video_id: int, *, reanalysis: bool = False) -> int:
    """驗證後建立一筆 analysis job；驗證邏輯直接搬用既有 video_service 函式，
    不重新實作。回傳 job_id。

    `reanalysis=True` 會在驗證通過後、建立 job 之前把影片切到重新分析的狀態
    （見 `video_service.prepare_reanalysis()`）。狀態變更一定要排在三個驗證
    之後：先改狀態再驗證的話，任何一個驗證失敗都會留下一支狀態已經被改掉、
    卻沒有任何工作在跑的影片，畫面上會永遠停在「等待重新分析」。
    """
    video = video_service.get_video(video_id)
    if video is None:
        raise VideoNotFoundError(f"找不到影片 {video_id}")
    if db.has_active_analysis_job(video_id):
        raise DuplicateJobError(f"影片 {video_id} 已經有排隊中或執行中的分析工作")
    if not video_service.is_within_duration_limit(video.duration_sec):
        raise DurationLimitExceededError(
            f"影片長度超過 {video_service.max_duration_minutes()} 分鐘限制"
        )

    if reanalysis:
        video_service.prepare_reanalysis(video)

    job_id = db.insert_job(job_type=db.JOB_TYPE_ANALYSIS, video_id=video_id)
    _try_dispatch_next_analysis()
    return job_id


def _try_dispatch_next_analysis() -> None:
    """檢查目前有沒有正在跑的分析工作；沒有的話，挑最舊的一筆 queued 分析
    工作開始跑。用鎖保護「檢查＋標記」這一步，避免多個呼叫端同時通過檢查。
    """
    global _analysis_running
    with _analysis_lock:
        if _analysis_running:
            return
        next_job = _oldest_queued_analysis_job()
        if next_job is None:
            return
        _analysis_running = True
    _start_analysis_job(next_job)


def _oldest_queued_analysis_job() -> db.JobRecord | None:
    queued = db.list_jobs(job_type=db.JOB_TYPE_ANALYSIS, status=db.JOB_STATUS_QUEUED)
    if not queued:
        return None
    return min(queued, key=lambda job: job.id)


# pump thread 的名稱前綴：traceback 與 py-spy 看得出這條執行緒在做什麼。
PUMP_THREAD_PREFIX = "job-pump-"


def _start_analysis_job(job: db.JobRecord) -> None:
    if job.video_id is None:
        raise InvalidJobStateError(f"分析工作 {job.id} 沒有記錄 video_id，無法開始")
    db.mark_job_running(job.id)
    internal_queue: "queue.Queue[object]" = queue.Queue()
    analyzer.start_analysis(job.video_id, internal_queue)
    # 取名字：traceback 與 py-spy 看得出這條執行緒在做什麼，測試也能等它收尾
    threading.Thread(
        target=_pump_analysis, args=(job.id, internal_queue), daemon=True,
        name=f"{PUMP_THREAD_PREFIX}analysis-{job.id}",
    ).start()


def _pump_analysis(job_id: int, internal_queue: "queue.Queue[object]") -> None:
    """把 analyzer 送出的事件寫進 jobs 表，收到終端事件就結束。

    釋放 slot 放在 finally：這個迴圈裡的每一次資料庫寫入都可能失敗，而只要
    這條 pump 沒有走到釋放那一步，`_analysis_running` 就會永遠是 True，之後
    所有分析都會卡在 queued。analyzer 那邊保證一定會送出終端事件（見
    `_analyze_worker()`），這裡是第二道防線。
    """
    try:
        while True:
            item = internal_queue.get()
            if isinstance(item, analyzer.AnalysisProgress):
                db.update_job_progress(job_id, stage=item.stage, progress_message=item.detail or None)
            elif isinstance(item, analyzer.AnalysisResult):
                db.mark_job_completed(job_id, cost_usd=item.cost_usd)
                break
            elif isinstance(item, analyzer.AnalysisError):
                db.mark_job_failed(job_id, error_message=item.message)
                break
    except Exception:
        logger.error("分析工作 %s 的進度回報異常結束，標記失敗", job_id, exc_info=True)
        try:
            db.mark_job_failed(job_id, error_message="進度回報異常中斷")
        except Exception:
            logger.error("連標記工作 %s 失敗都寫不進資料庫", job_id, exc_info=True)
    finally:
        _release_analysis_slot()


def _release_analysis_slot() -> None:
    global _analysis_running
    with _analysis_lock:
        _analysis_running = False
    _try_dispatch_next_analysis()


# ----------------------------------------------------------------------
# 下載工作：不序列化，收到請求立即開始
# ----------------------------------------------------------------------
def submit_download(url: str) -> int:
    if not video_service.is_youtube_url(url):
        raise InvalidUrlError(f"不是有效的 YouTube 網址：{url}")
    existing = video_service.find_existing_by_url(url)
    if existing is not None:
        raise DuplicateJobError(f"此影片已經在庫中（狀態：{existing.status}）")
    if db.has_active_download_job(url):
        raise DuplicateJobError("這個網址已經有下載中的工作")

    job_id = db.insert_job(job_type=db.JOB_TYPE_DOWNLOAD, source_url=url)
    db.mark_job_running(job_id)
    internal_queue: "queue.Queue[object]" = queue.Queue()
    dest_dir = downloader.VIDEO_DIR / f"job-{job_id}"
    downloader.start_download(url, internal_queue, dest_dir=dest_dir)
    threading.Thread(
        target=_pump_download, args=(job_id, url, internal_queue), daemon=True,
        name=f"{PUMP_THREAD_PREFIX}download-{job_id}",
    ).start()
    return job_id


def _pump_download(job_id: int, url: str, internal_queue: "queue.Queue[object]") -> None:
    while True:
        item = internal_queue.get()
        if isinstance(item, downloader.DownloadProgress):
            if item.status == "error":
                db.mark_job_failed(job_id, error_message=item.error_message)
                break
            db.update_job_progress(
                job_id,
                stage="下載中",
                progress_percent=round(item.percent) if item.percent else None,
                progress_message=f"{item.speed_text}｜剩餘 {item.eta_text}",
            )
        elif isinstance(item, downloader.DownloadResult):
            video_id = video_service.register_downloaded_video(
                title=item.title, source_url=url, file_path=item.file_path, duration_sec=item.duration_sec,
            )
            db.set_job_video_id(job_id, video_id)
            db.mark_job_completed(job_id)
            break


# ----------------------------------------------------------------------
# Retry（Cancel 沒有實作：pipeline 沒有 checkpoint／取消 token，
# 無法安全中途停止，見模組說明與 docs/09-web-ui-migration-plan.md）
# ----------------------------------------------------------------------
def retry_job(job_id: int) -> int:
    """對失敗的工作建立全新一筆重新 submit（舊列保留當歷史紀錄），回傳新
    job_id。"""
    job = get_job_or_raise(job_id)
    if job.status != db.JOB_STATUS_FAILED:
        raise InvalidJobStateError(f"只有失敗的工作可以重試（目前狀態：{job.status}）")

    if job.job_type == db.JOB_TYPE_ANALYSIS:
        if job.video_id is None:
            raise InvalidJobStateError(f"分析工作 {job_id} 沒有記錄 video_id，無法重試")
        video_service.reset_to_pending(job.video_id)
        return submit_analysis(job.video_id)

    if job.source_url is None:
        raise InvalidJobStateError("這個下載工作沒有記錄原始網址，無法重試")
    return submit_download(job.source_url)



# ----------------------------------------------------------------------
# 伺服器啟動時的 reconciliation
# ----------------------------------------------------------------------
def reconcile_stale_jobs() -> int:
    """把上次異常中止（process 被砍掉）、卡在 running 的工作全部標記失敗，
    回傳受影響筆數。見 docs/09-web-ui-migration-plan.md 3.2 節「Zombie job」。
    """
    count = db.fail_all_running_jobs("伺服器重新啟動，任務中斷")
    if count:
        logger.warning("啟動時發現 %d 個卡在 running 的工作，已標記失敗", count)
    return count
