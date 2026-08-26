"""job_manager 的特徵測試（characterization tests）：鎖住 Job Manager 目前的
驗證規則、序列化 dispatcher、pump thread 事件對映與 retry 狀態機，
做為之後重構 analyzer.py（進度／成本／執行緒抽象化）的安全網。

跟 tests/api/test_api_jobs.py 的分工：那邊從 HTTP 層驗收「兩次 /analyze 回
409」「第二個 job 停在 queued」等對外行為；這裡直接呼叫 service 函式，測
HTTP 層看不到的內部行為——pump thread 把 queue 事件寫進 jobs 表的**欄位對映**、
失敗路徑是否一樣會釋放分析 slot、下載工作的 dest_dir 命名規則、retry 對
analysis／download 兩種工作的不同處理，以及 worker 異常結束時分析 slot 仍會釋放。

analyzer.start_analysis／downloader.start_download 一律換成假的：測試自己
持有那條 queue，想送什麼事件、什麼時候送，都由測試決定，不觸發真的
pipeline／yt-dlp／OpenAI 呼叫。
"""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import pytest

from ai_video_search_web import db, downloader
from ai_video_search_web.pipeline import analyzer
from ai_video_search_web.services import job_manager

YOUTUBE_URL = "https://www.youtube.com/watch?v=abc12345678"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """獨立的臨時 DB 與影片目錄，並把 process 級的分析旗標重置成 False——
    這個旗標是模組全域狀態，上一個測試如果留下 True，這個測試的 job 會直接
    卡在 queued，看起來像 dispatcher 壞掉。
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(downloader, "VIDEO_DIR", tmp_path / "video")
    monkeypatch.setattr(job_manager, "_analysis_running", False)
    db.init_db()


class _FakeAnalysisStarter:
    """取代 analyzer.start_analysis：記錄每次被呼叫的 video_id 與 queue，讓
    測試可以自己往那條 queue 送進度／完成／失敗事件，驅動真正的 pump thread。
    回傳一個立刻結束的 Thread，維持跟真實函式一樣的回傳型別。
    """

    def __init__(self) -> None:
        self.video_ids: list[int] = []
        self.queues: list["queue.Queue[object]"] = []

    def __call__(self, video_id: int, progress_queue: "queue.Queue[object]") -> threading.Thread:
        self.video_ids.append(video_id)
        self.queues.append(progress_queue)
        thread = threading.Thread(target=lambda: None, daemon=True)
        thread.start()
        return thread


class _FakeDownloadStarter:
    """取代 downloader.start_download，理由同 _FakeAnalysisStarter；額外記錄
    dest_dir，用來驗證「每個 job 各自一個目錄」的命名規則。
    """

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.dest_dirs: list[Path | None] = []
        self.queues: list["queue.Queue[object]"] = []

    def __call__(
        self, url: str, progress_queue: "queue.Queue[object]", dest_dir: Path | None = None
    ) -> threading.Thread:
        self.urls.append(url)
        self.dest_dirs.append(dest_dir)
        self.queues.append(progress_queue)
        thread = threading.Thread(target=lambda: None, daemon=True)
        thread.start()
        return thread


@pytest.fixture
def fake_analysis(monkeypatch) -> _FakeAnalysisStarter:
    starter = _FakeAnalysisStarter()
    monkeypatch.setattr(analyzer, "start_analysis", starter)
    return starter


@pytest.fixture
def fake_download(monkeypatch) -> _FakeDownloadStarter:
    starter = _FakeDownloadStarter()
    monkeypatch.setattr(downloader, "start_download", starter)
    return starter


def _make_video(duration_sec: int = 100, source_url: str | None = None) -> int:
    return db.insert_video(
        title="測試影片", source=db.SOURCE_LOCAL, source_url=source_url,
        file_path="/nonexistent.mp4", duration_sec=duration_sec,
    )


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _live_pump_threads() -> list[threading.Thread]:
    """還活著的 pump thread。名稱前綴由 job_manager 定義，見 PUMP_THREAD_PREFIX。"""
    return [t for t in threading.enumerate() if t.name.startswith(job_manager.PUMP_THREAD_PREFIX)]


def _wait_for_job_status(job_id: int, status: str) -> None:
    assert _wait_until(lambda: db.get_job(job_id).status == status), (
        f"工作 {job_id} 應該變成 {status}，實際是 {db.get_job(job_id).status}"
    )


def _wait_for_analysis_idle() -> None:
    """等 pump thread 真的收尾完畢才讓測試返回。

    只等 job 變成終態不夠：`_pump_analysis()` 是先寫終態、才呼叫
    `_release_analysis_slot()`，而後者會再查一次 `db.list_jobs()`。測試如果
    在這中間就返回，那次查詢會落在 monkeypatch 已經還原 DB_PATH 之後，變成
    對別的資料庫查詢（實測會炸出 "no such table: jobs"）。
    """
    assert _wait_until(lambda: not job_manager._analysis_running), "分析 slot 應該被釋放"
    # 旗標翻回 False 之後，那條 pump thread 還要跑完「鏈式派發」才真的結束。
    # 多數測試刻意讓 pump 停在 queue.get() 不送終端事件，所以不能等「所有
    # pump thread 都結束」（那會等到逾時），只能給收尾一小段寬限。
    _wait_until(lambda: not _live_pump_threads(), timeout=0.3)


# ----------------------------------------------------------------------
# submit_analysis()：驗證規則
# ----------------------------------------------------------------------
def test_submit_analysis_rejects_unknown_video(temp_db, fake_analysis):
    with pytest.raises(job_manager.VideoNotFoundError):
        job_manager.submit_analysis(999)

    assert db.list_jobs() == []  # 驗證失敗不留下 job 列


def test_submit_analysis_rejects_video_over_duration_limit(temp_db, fake_analysis):
    video_id = _make_video(duration_sec=analyzer.MAX_DURATION_SEC + 1)

    with pytest.raises(job_manager.DurationLimitExceededError):
        job_manager.submit_analysis(video_id)

    assert db.list_jobs() == []


def test_submit_analysis_rejects_duplicate_active_job(temp_db, fake_analysis):
    video_id = _make_video()
    job_manager.submit_analysis(video_id)

    with pytest.raises(job_manager.DuplicateJobError):
        job_manager.submit_analysis(video_id)

    assert len(db.list_jobs(video_id=video_id)) == 1


def test_submit_analysis_dispatches_immediately_when_slot_free(temp_db, fake_analysis):
    video_id = _make_video()

    job_id = job_manager.submit_analysis(video_id)

    job = db.get_job(job_id)
    assert job.status == db.JOB_STATUS_RUNNING
    assert job.job_type == db.JOB_TYPE_ANALYSIS
    assert job.started_at is not None
    assert fake_analysis.video_ids == [video_id]


def test_submit_analysis_keeps_second_job_queued_while_one_is_running(temp_db, fake_analysis):
    first_job = job_manager.submit_analysis(_make_video())
    second_job = job_manager.submit_analysis(_make_video())

    assert db.get_job(first_job).status == db.JOB_STATUS_RUNNING
    assert db.get_job(second_job).status == db.JOB_STATUS_QUEUED
    assert len(fake_analysis.video_ids) == 1  # 第二支還沒真的開始跑


# ----------------------------------------------------------------------
# _pump_analysis()：queue 事件 → jobs 表欄位的對映
# ----------------------------------------------------------------------
def test_pump_writes_progress_stage_and_detail(temp_db, fake_analysis):
    job_id = job_manager.submit_analysis(_make_video())

    fake_analysis.queues[0].put(analyzer.AnalysisProgress(stage="畫面分析", detail="40%"))

    assert _wait_until(lambda: db.get_job(job_id).stage == "畫面分析")
    job = db.get_job(job_id)
    assert job.progress_message == "40%"
    assert job.status == db.JOB_STATUS_RUNNING  # 進度事件不改變狀態


def test_pump_writes_empty_detail_as_null_progress_message(temp_db, fake_analysis):
    job_id = job_manager.submit_analysis(_make_video())

    fake_analysis.queues[0].put(analyzer.AnalysisProgress(stage="建立向量中"))

    assert _wait_until(lambda: db.get_job(job_id).stage == "建立向量中")
    assert db.get_job(job_id).progress_message is None


def test_pump_marks_job_completed_with_cost(temp_db, fake_analysis):
    video_id = _make_video()
    job_id = job_manager.submit_analysis(video_id)

    fake_analysis.queues[0].put(
        analyzer.AnalysisResult(video_id=video_id, segment_count=12, cost_usd=0.1234, partial=False)
    )

    _wait_for_job_status(job_id, db.JOB_STATUS_COMPLETED)
    job = db.get_job(job_id)
    assert job.cost_usd == pytest.approx(0.1234)
    assert job.completed_at is not None
    assert job.error_message is None
    _wait_for_analysis_idle()


def test_pump_marks_job_failed_with_message(temp_db, fake_analysis):
    video_id = _make_video()
    job_id = job_manager.submit_analysis(video_id)

    fake_analysis.queues[0].put(analyzer.AnalysisError(video_id=video_id, message="找不到影片檔案"))

    _wait_for_job_status(job_id, db.JOB_STATUS_FAILED)
    job = db.get_job(job_id)
    assert job.error_message == "找不到影片檔案"
    assert job.completed_at is not None
    assert job.cost_usd is None
    _wait_for_analysis_idle()


def test_analysis_slot_is_released_after_failure_not_only_success(temp_db, fake_analysis):
    """失敗路徑一樣要釋放 slot、鏈式派發下一個排隊中的工作——不然一次分析
    失敗就會讓之後所有分析永遠卡在 queued。
    """
    first_video = _make_video()
    first_job = job_manager.submit_analysis(first_video)
    second_job = job_manager.submit_analysis(_make_video())

    fake_analysis.queues[0].put(analyzer.AnalysisError(video_id=first_video, message="分析失敗：boom"))

    _wait_for_job_status(first_job, db.JOB_STATUS_FAILED)
    _wait_for_job_status(second_job, db.JOB_STATUS_RUNNING)
    assert len(fake_analysis.video_ids) == 2

    # 收尾：第二個工作現在正握著 slot（這是對的），要讓它也跑完才能等到 idle。
    fake_analysis.queues[1].put(
        analyzer.AnalysisResult(video_id=fake_analysis.video_ids[1], segment_count=1, cost_usd=0.0, partial=False)
    )
    _wait_for_job_status(second_job, db.JOB_STATUS_COMPLETED)
    _wait_for_analysis_idle()


def test_analysis_slot_is_released_even_when_pump_write_fails(temp_db, fake_analysis, monkeypatch):
    """pump 迴圈裡的資料庫寫入失敗時，slot 仍然要釋放並派發下一個工作——
    否則一次寫入失敗就會讓之後所有分析永遠卡在 queued。
    """
    first_video = _make_video()
    job_manager.submit_analysis(first_video)
    second_job = job_manager.submit_analysis(_make_video())

    # 用旗標控制假實作，不用 monkeypatch.undo()——undo() 會把這個測試的**全部**
    # monkeypatch 一起撤掉，包含 fixture 設的 db.DB_PATH，後半段就會讀到真正的
    # app.db（主目錄剛好有那個檔案，所以這個錯誤一度沒被發現）。
    failing = {"on": True}
    real_mark_completed = db.mark_job_completed

    def _mark_completed(*args, **kwargs):
        if failing["on"]:
            raise RuntimeError("寫不進去")
        return real_mark_completed(*args, **kwargs)

    monkeypatch.setattr(db, "mark_job_completed", _mark_completed)
    fake_analysis.queues[0].put(
        analyzer.AnalysisResult(video_id=first_video, segment_count=1, cost_usd=0.0, partial=False)
    )

    _wait_for_job_status(second_job, db.JOB_STATUS_RUNNING)
    assert len(fake_analysis.video_ids) == 2

    failing["on"] = False
    fake_analysis.queues[1].put(
        analyzer.AnalysisResult(video_id=fake_analysis.video_ids[1], segment_count=1, cost_usd=0.0, partial=False)
    )
    _wait_for_job_status(second_job, db.JOB_STATUS_COMPLETED)
    _wait_for_analysis_idle()


def test_analysis_slot_is_released_even_when_the_failure_fallback_also_fails(temp_db, fake_analysis, monkeypatch):
    """pump 的寫入失敗、連「改標記成失敗」的 fallback 也失敗時，slot 仍然要
    釋放。這是 `finally` 唯一無可取代的情境——只有 except 而沒有 finally 的話，
    這條路徑會讓之後所有分析永遠卡在 queued。
    """
    first_video = _make_video()
    job_manager.submit_analysis(first_video)
    second_job = job_manager.submit_analysis(_make_video())

    failing = {"on": True}
    real_mark_completed, real_mark_failed = db.mark_job_completed, db.mark_job_failed

    def _explode_while_failing(real):
        def _wrapped(*args, **kwargs):
            if failing["on"]:
                raise RuntimeError("資料庫整個壞掉")
            return real(*args, **kwargs)
        return _wrapped

    monkeypatch.setattr(db, "mark_job_completed", _explode_while_failing(real_mark_completed))
    monkeypatch.setattr(db, "mark_job_failed", _explode_while_failing(real_mark_failed))
    fake_analysis.queues[0].put(
        analyzer.AnalysisResult(video_id=first_video, segment_count=1, cost_usd=0.0, partial=False)
    )

    _wait_for_job_status(second_job, db.JOB_STATUS_RUNNING)

    failing["on"] = False
    fake_analysis.queues[1].put(
        analyzer.AnalysisResult(video_id=fake_analysis.video_ids[1], segment_count=1, cost_usd=0.0, partial=False)
    )
    _wait_for_job_status(second_job, db.JOB_STATUS_COMPLETED)
    _wait_for_analysis_idle()


def test_analysis_slot_is_released_when_the_worker_dies_before_its_own_error_handling(
    temp_db, tmp_path, monkeypatch
):
    """C0 缺陷的回歸測試（整合層級，用真的 analyzer.start_analysis()）。

    模擬最實際的觸發路徑：影片檔案存在、流程正常往下走，但 `get_client()`
    因為缺 API 金鑰而拋例外——那行在 `_run_analysis()` 自己的 try 之前，修好
    以前 worker 會無聲死掉、pump 永遠停在 queue.get()、slot 永不釋放，之後
    每一支影片都卡在 queued。
    """
    monkeypatch.setattr(analyzer, "get_client", lambda: (_ for _ in ()).throw(RuntimeError("沒有 API 金鑰")))

    real_video = tmp_path / "real.mp4"
    real_video.write_bytes(b"not really a video")
    first_video = db.insert_video(
        title="有檔案的影片", source=db.SOURCE_LOCAL, source_url=None,
        file_path=str(real_video), duration_sec=100,
    )

    first_job = job_manager.submit_analysis(first_video)
    second_job = job_manager.submit_analysis(_make_video())

    _wait_for_job_status(first_job, db.JOB_STATUS_FAILED)
    assert "沒有 API 金鑰" in db.get_job(first_job).error_message
    assert db.get_video(first_video).status == db.STATUS_FAILED

    # 關鍵斷言：排隊中的第二個工作沒有被卡住，slot 有被釋放
    _wait_for_job_status(second_job, db.JOB_STATUS_FAILED)  # 它的檔案不存在，也會失敗——但有真的跑到
    assert db.get_job(second_job).error_message == "找不到影片檔案"
    _wait_for_analysis_idle()


# ----------------------------------------------------------------------
# submit_download()
# ----------------------------------------------------------------------
def test_submit_download_rejects_non_youtube_url(temp_db, fake_download):
    with pytest.raises(job_manager.InvalidUrlError):
        job_manager.submit_download("https://example.com/video.mp4")

    assert db.list_jobs() == []


def test_submit_download_rejects_url_already_in_library(temp_db, fake_download):
    _make_video(source_url=YOUTUBE_URL)

    with pytest.raises(job_manager.DuplicateJobError):
        job_manager.submit_download(YOUTUBE_URL)

    assert db.list_jobs() == []


def test_submit_download_rejects_url_with_active_download_job(temp_db, fake_download):
    job_manager.submit_download(YOUTUBE_URL)

    with pytest.raises(job_manager.DuplicateJobError):
        job_manager.submit_download(YOUTUBE_URL)

    assert len(db.list_jobs(job_type=db.JOB_TYPE_DOWNLOAD)) == 1


def test_submit_download_starts_running_with_per_job_dest_dir(temp_db, fake_download):
    """下載不序列化（不呼叫 OpenAI、不佔預算），收到請求就直接 running；
    dest_dir 依 job_id 分開，避免兩支標題相同的影片互相覆蓋檔案。
    """
    job_id = job_manager.submit_download(YOUTUBE_URL)

    job = db.get_job(job_id)
    assert job.status == db.JOB_STATUS_RUNNING
    assert job.source_url == YOUTUBE_URL
    assert job.video_id is None  # 下載完成前還不知道 video_id
    assert fake_download.urls == [YOUTUBE_URL]
    assert fake_download.dest_dirs[0] == downloader.VIDEO_DIR / f"job-{job_id}"


def test_pump_download_writes_percent_and_message(temp_db, fake_download):
    job_id = job_manager.submit_download(YOUTUBE_URL)

    fake_download.queues[0].put(
        downloader.DownloadProgress(
            status="downloading", percent=42.6, speed_text="3.2 MB/s", eta_text="00:30"
        )
    )

    assert _wait_until(lambda: db.get_job(job_id).progress_percent is not None)
    job = db.get_job(job_id)
    assert job.stage == "下載中"
    assert job.progress_percent == 43  # round()，不是無條件捨去
    assert job.progress_message == "3.2 MB/s｜剩餘 00:30"


def test_pump_download_error_marks_job_failed(temp_db, fake_download):
    job_id = job_manager.submit_download(YOUTUBE_URL)

    fake_download.queues[0].put(
        downloader.DownloadProgress(status="error", error_message="HTTP Error 403")
    )

    _wait_for_job_status(job_id, db.JOB_STATUS_FAILED)
    assert db.get_job(job_id).error_message == "HTTP Error 403"


def test_pump_download_result_registers_video_and_completes_job(temp_db, fake_download):
    job_id = job_manager.submit_download(YOUTUBE_URL)

    fake_download.queues[0].put(
        downloader.DownloadResult(
            title="下載完成的影片", file_path=Path("/tmp/downloaded.mp4"), duration_sec=321
        )
    )

    _wait_for_job_status(job_id, db.JOB_STATUS_COMPLETED)
    job = db.get_job(job_id)
    assert job.video_id is not None

    video = db.get_video(job.video_id)
    assert video.title == "下載完成的影片"
    assert video.source == db.SOURCE_YOUTUBE
    assert video.source_url == YOUTUBE_URL
    assert video.file_path == "/tmp/downloaded.mp4"
    assert video.duration_sec == 321
    assert video.status == db.STATUS_PENDING  # 下載完只是待分析，不會自動開始分析


# ----------------------------------------------------------------------
# retry_job()
# ----------------------------------------------------------------------
def test_retry_job_rejects_unknown_job(temp_db):
    with pytest.raises(job_manager.JobNotFoundError):
        job_manager.retry_job(999)


def test_retry_job_rejects_non_failed_job(temp_db, fake_analysis):
    job_id = job_manager.submit_analysis(_make_video())

    with pytest.raises(job_manager.InvalidJobStateError):
        job_manager.retry_job(job_id)


def test_retry_analysis_job_resets_video_and_creates_new_job(temp_db, fake_analysis):
    """重試是「建立全新一筆」，舊列保留當歷史紀錄；影片也會被還原成
    pending（清掉上次部分寫入的 segments 與分析欄位）。
    """
    video_id = _make_video()
    old_job = job_manager.submit_analysis(video_id)
    db.insert_segment(
        video_id=video_id, start_sec=0.0, end_sec=1.0, transcript="上一次留下的片段",
        visual_description=None, ocr_text=None, transcript_embedding=None,
        visual_embedding=None, asr_model=None, vlm_model=None, embedding_model=None,
    )
    db.mark_job_failed(old_job, error_message="boom")
    db.update_video_status(video_id, db.STATUS_FAILED, "分析失敗")
    job_manager._analysis_running = False  # 模擬上一輪 pump 已經釋放 slot

    new_job = job_manager.retry_job(old_job)

    assert new_job != old_job
    assert db.get_job(old_job).status == db.JOB_STATUS_FAILED  # 舊列保留
    assert db.get_job(new_job).status == db.JOB_STATUS_RUNNING
    assert db.get_video(video_id).status == db.STATUS_PENDING
    assert db.list_segments_for_video(video_id) == []


def test_retry_download_job_resubmits_source_url(temp_db, fake_download):
    old_job = job_manager.submit_download(YOUTUBE_URL)
    db.mark_job_failed(old_job, error_message="boom")

    new_job = job_manager.retry_job(old_job)

    assert new_job != old_job
    assert db.get_job(new_job).source_url == YOUTUBE_URL
    assert fake_download.urls == [YOUTUBE_URL, YOUTUBE_URL]


def test_retry_download_job_without_source_url_raises(temp_db):
    job_id = db.insert_job(job_type=db.JOB_TYPE_DOWNLOAD)
    db.mark_job_failed(job_id, error_message="boom")

    with pytest.raises(job_manager.InvalidJobStateError):
        job_manager.retry_job(job_id)


# ----------------------------------------------------------------------
# reconcile_stale_jobs()
# ----------------------------------------------------------------------
def test_reconcile_marks_running_jobs_failed_and_returns_count(temp_db):
    stale_analysis = db.insert_job(job_type=db.JOB_TYPE_ANALYSIS, video_id=_make_video())
    stale_download = db.insert_job(job_type=db.JOB_TYPE_DOWNLOAD, source_url=YOUTUBE_URL)
    db.mark_job_running(stale_analysis)
    db.mark_job_running(stale_download)
    untouched = db.insert_job(job_type=db.JOB_TYPE_ANALYSIS, video_id=_make_video())

    count = job_manager.reconcile_stale_jobs()

    assert count == 2
    assert db.get_job(stale_analysis).status == db.JOB_STATUS_FAILED
    assert db.get_job(stale_analysis).error_message == "伺服器重新啟動，任務中斷"
    assert db.get_job(untouched).status == db.JOB_STATUS_QUEUED  # queued 不受影響


def test_reconcile_returns_zero_when_nothing_running(temp_db):
    assert job_manager.reconcile_stale_jobs() == 0
