"""progress_estimation.py 的單元測試：用假的 work() callable（短暫 sleep），
不呼叫真實 API，跑得很快。

計時上要注意：POLL_INTERVAL_SEC 是 0.4 秒，work() 執行時間短於這個值時，
迴圈只會跑一次就結束（thread.join(timeout=0.4) 會在工作完成當下就提早
返回），沒辦法驗證「多次回報、上限生效」這類需要迴圈跑兩次以上的行為。
要驗證這類行為的測試，work() 刻意 sleep 超過一次 POLL_INTERVAL_SEC。
"""
from __future__ import annotations

import time

import pytest

from ai_video_search_web.pipeline import progress_estimation


def test_run_with_estimated_progress_returns_work_result():
    result = progress_estimation.run_with_estimated_progress(lambda: 42, estimated_total_sec=0.05)
    assert result == 42


def test_run_with_estimated_progress_calls_on_progress_multiple_times():
    def work():
        time.sleep(0.5)  # 超過一次 POLL_INTERVAL_SEC(0.4)，確保迴圈至少跑兩次
        return "done"

    percents: list[int] = []
    result = progress_estimation.run_with_estimated_progress(
        work, estimated_total_sec=0.1, on_progress=percents.append
    )

    assert result == "done"
    assert len(percents) >= 2
    # 百分比應該是遞增（或至少不遞減）的序列
    assert percents == sorted(percents)


def test_run_with_estimated_progress_caps_at_max_display_percent():
    def work():
        time.sleep(0.5)  # 同上，確保迴圈跑第二次時 elapsed 已經遠超過 estimated_total_sec
        return None

    percents: list[int] = []
    # estimated_total_sec 故意設很短，讓 elapsed/estimated 遠超過 100%，
    # 驗證顯示上限確實擋在 MAX_DISPLAY_PERCENT
    progress_estimation.run_with_estimated_progress(work, estimated_total_sec=0.01, on_progress=percents.append)

    assert all(p <= progress_estimation.MAX_DISPLAY_PERCENT for p in percents)
    assert progress_estimation.MAX_DISPLAY_PERCENT in percents


def test_run_with_estimated_progress_without_on_progress_callback():
    # on_progress=None（預設）不應該出錯
    result = progress_estimation.run_with_estimated_progress(lambda: "ok", estimated_total_sec=0.05)
    assert result == "ok"


def test_run_with_estimated_progress_reraises_work_exception():
    def failing_work():
        raise ValueError("模擬工作失敗")

    with pytest.raises(ValueError, match="模擬工作失敗"):
        progress_estimation.run_with_estimated_progress(failing_work, estimated_total_sec=0.05)
