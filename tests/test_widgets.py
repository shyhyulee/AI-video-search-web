"""ui/widgets.py 的純邏輯格式化函式測試（不需要 Tk）：
format_analysis_result_note() 要把「預算截斷」跟「場景畫面分析失敗」兩種
互相獨立的原因分開組字，不能誤導使用者看到錯的原因。"""
from __future__ import annotations

from ai_video_search_web.pipeline.analyzer import AnalysisResult
from ai_video_search_web.ui.widgets import format_analysis_result_note


def _result(partial: bool, vlm_failed_count: int = 0) -> AnalysisResult:
    return AnalysisResult(
        video_id=1, segment_count=10, cost_usd=0.1, partial=partial,
        vlm_failed_count=vlm_failed_count,
    )


def test_format_analysis_result_note_no_issues_returns_empty_string():
    assert format_analysis_result_note(_result(partial=False)) == ""


def test_format_analysis_result_note_budget_partial_only():
    note = format_analysis_result_note(_result(partial=True))
    assert note == "（已達預算上限，僅完成部分片段）"


def test_format_analysis_result_note_vlm_failure_only():
    note = format_analysis_result_note(_result(partial=False, vlm_failed_count=3))
    assert note == "（3 個場景畫面分析失敗，已略過）"
    assert "預算上限" not in note  # 不能把場景失敗誤標成預算問題


def test_format_analysis_result_note_both_combined():
    note = format_analysis_result_note(_result(partial=True, vlm_failed_count=2))
    assert note == "（已達預算上限，僅完成部分片段；2 個場景畫面分析失敗，已略過）"
