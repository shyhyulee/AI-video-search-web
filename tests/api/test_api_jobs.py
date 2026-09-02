"""jobs API：關鍵驗收條件——同一 video_id 連發兩次 /analyze 第二次回 409、
兩個不同 video_id 連發時第二個停在 queued 直到第一個變終態、伺服器啟動時
的 zombie job reconciliation，見 docs/archive/09-web-ui-migration-plan.md 4.3 節。

分析／下載本身用假的 analyzer.start_analysis／downloader.start_download
取代，不觸發真的 pipeline／yt-dlp／OpenAI 呼叫；這兩個函式的真實邏輯已經
在 test_analyzer.py／既有測試覆蓋，這裡只測 Job Manager 的序列化與持久化
邏輯本身。
"""
from __future__ import annotations

import threading
import time

from ai_video_search_web import db
from ai_video_search_web.pipeline import analyzer
from ai_video_search_web.services import job_manager

from conftest import make_video


def _fake_start_analysis_never_completes(video_id: int, q) -> threading.Thread:
    """取代 analyzer.start_analysis：立刻回傳一個 Thread（維持跟真實函式
    一樣的回傳型別），但永遠不把結果放進 queue，工作永遠停在 running。用在
    只需要驗證「有東西在跑」、不需要它真的完成的測試。
    """
    thread = threading.Thread(target=lambda: None, daemon=True)
    thread.start()
    return thread


def _make_controllable_fake_start_analysis():
    """回傳 (fake_start, events)：fake_start 每次被呼叫都建立「各自獨立」的
    threading.Event 並依呼叫順序記錄到 events，讓測試可以個別 set() 控制
    哪一個先完成——不能讓多個 job 共用同一個 Event，因為 Event.set() 是
    閂鎖、不會重置，共用會讓後面的 job 一被派發就立刻跟著完成。
    """
    events: list[threading.Event] = []

    def _start(video_id: int, q) -> threading.Thread:
        hold_event = threading.Event()
        events.append(hold_event)

        def _worker() -> None:
            hold_event.wait(timeout=5)
            q.put(analyzer.AnalysisResult(video_id=video_id, segment_count=1, cost_usd=0.01, partial=False))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        return thread

    return _start, events


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_list_jobs_empty(client):
    assert client.get("/api/v1/jobs").json() == []


def test_list_active_jobs_returns_only_unfinished(client, monkeypatch):
    """`?active=true` 是前端重新整理後還原進度追蹤的入口：只能回 queued／
    running，已經到終態的不能混進來，否則畫面會重新掛上早就結束的工作。"""
    monkeypatch.setattr(job_manager.analyzer, "start_analysis", _fake_start_analysis_never_completes)
    running_video = make_video()
    running_job_id = client.post(f"/api/v1/videos/{running_video}/analyze").json()["id"]
    finished_job_id = db.insert_job(job_type=db.JOB_TYPE_ANALYSIS, video_id=make_video())
    db.mark_job_completed(finished_job_id)

    active_ids = [j["id"] for j in client.get("/api/v1/jobs?active=true&job_type=analysis").json()]

    assert active_ids == [running_job_id]
    assert finished_job_id not in active_ids
    # 不帶 active 的查法維持原樣：兩筆都要回。
    assert len(client.get("/api/v1/jobs").json()) == 2


def test_get_job_not_found_returns_404(client):
    resp = client.get("/api/v1/jobs/999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_retry_job_not_found_returns_404(client):
    resp = client.post("/api/v1/jobs/999/retry")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_retry_job_wrong_status_returns_409(client, monkeypatch):
    monkeypatch.setattr(job_manager.analyzer, "start_analysis", _fake_start_analysis_never_completes)
    video_id = make_video()
    job_id = client.post(f"/api/v1/videos/{video_id}/analyze").json()["id"]

    resp = client.post(f"/api/v1/jobs/{job_id}/retry")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INVALID_JOB_STATE"


def test_second_analyze_call_for_same_video_returns_409(client, monkeypatch):
    monkeypatch.setattr(job_manager.analyzer, "start_analysis", _fake_start_analysis_never_completes)
    video_id = make_video()

    first = client.post(f"/api/v1/videos/{video_id}/analyze")
    assert first.status_code == 202

    second = client.post(f"/api/v1/videos/{video_id}/analyze")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_JOB"


def test_second_analysis_job_waits_for_first_to_finish(client, monkeypatch):
    fake_start, events = _make_controllable_fake_start_analysis()
    monkeypatch.setattr(job_manager.analyzer, "start_analysis", fake_start)

    video_id_1 = make_video()
    video_id_2 = make_video()

    job1_id = client.post(f"/api/v1/videos/{video_id_1}/analyze").json()["id"]
    job2_id = client.post(f"/api/v1/videos/{video_id_2}/analyze").json()["id"]

    job1 = client.get(f"/api/v1/jobs/{job1_id}").json()
    job2 = client.get(f"/api/v1/jobs/{job2_id}").json()
    assert job1["status"] == "running"
    assert job2["status"] == "queued"
    assert len(events) == 1  # 第二個 job 還在排隊，還沒真的呼叫到 fake_start

    events[0].set()  # 放行第一個

    def _job2_dispatched() -> bool:
        return client.get(f"/api/v1/jobs/{job2_id}").json()["status"] != "queued"

    assert _wait_until(_job2_dispatched), "第二個工作應該在第一個完成後被鏈式派發"
    assert len(events) == 2  # 第二個 job 現在真的被派發、呼叫到 fake_start 了

    job1 = client.get(f"/api/v1/jobs/{job1_id}").json()
    job2 = client.get(f"/api/v1/jobs/{job2_id}").json()
    assert job1["status"] == "completed"
    assert job2["status"] == "running"

    # 清理：放行第二個，並且「等到它真的完成」才讓測試函式返回——不能放行
    # 後就馬上結束測試，那樣 pump thread 的收尾（mark_job_completed +
    # _release_analysis_slot() 的 db.list_jobs() 查詢）會在背景繼續跑，
    # 可能跨到下一個測試已經 TRUNCATE 測試資料庫之後才執行（SQLite 時期是
    # 換掉 db.DB_PATH，曾經實測炸出 "no such table: jobs"）。跨測試污染，
    # 不是 job_manager 本身的邏輯錯誤，是這個測試沒等背景工作收尾就返回。
    events[1].set()

    def _job2_completed() -> bool:
        return client.get(f"/api/v1/jobs/{job2_id}").json()["status"] == "completed"

    assert _wait_until(_job2_completed), "第二個工作也應該完成，避免殘留背景執行緒跨測試污染"


def test_startup_reconciliation_fails_stale_running_jobs(temp_db):
    """溫: 這個測試不用 client fixture（那個 fixture 進 TestClient 會觸發一次
    lifespan startup，時機點在建立殘留資料「之前」，驗證不到 reconciliation
    本身）；改成先手動塞一筆卡在 running 的 job，再自己建 TestClient 觸發
    lifespan，驗證啟動時真的會把它標記失敗。
    """
    from fastapi.testclient import TestClient

    from ai_video_search_web.api.main import app

    video_id = make_video()
    job_id = db.insert_job(job_type=db.JOB_TYPE_ANALYSIS, video_id=video_id)
    db.mark_job_running(job_id)

    with TestClient(app) as client:
        resp = client.get(f"/api/v1/jobs/{job_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error_message"] == "伺服器重新啟動，任務中斷"
