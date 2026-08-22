"""本地 OCR（ocr_service.py）的正規化、取樣邊界與去重合併邏輯測試。
不下載真實 EasyOCR 模型——這裡只測試不需要模型的純邏輯部分，
adapter 本身的 mock 測試在 test_ocr_adapters.py。
"""
from __future__ import annotations

from pathlib import Path

from ai_video_search_web.pipeline import ocr_service
from ai_video_search_web.pipeline.ocr_adapters import OcrCandidate

_DUMMY_VIDEO_PATH = Path("unused/path.mp4")


def test_normalize_text_collapses_whitespace_and_newlines():
    assert ocr_service.normalize_text("  ABC \n  1234  ") == "ABC 1234"


def test_normalize_text_full_width_to_half_width():
    assert ocr_service.normalize_text("ABC－１２３４") == "ABC-1234"


def test_normalize_text_empty_and_whitespace_only():
    assert ocr_service.normalize_text("   ") == ""
    assert ocr_service.normalize_text("") == ""


def test_sample_timestamps_scene_shorter_than_interval_returns_single_frame():
    # 場景長度（1.0s）小於取樣間隔（2.0s）：至少要有一張畫面，不能是空清單
    assert ocr_service._sample_timestamps(10.0, 11.0) == [10.0]


def test_sample_timestamps_zero_length_scene():
    assert ocr_service._sample_timestamps(5.0, 5.0) == [5.0]


def test_sample_timestamps_respects_interval_and_cap():
    # 20 秒場景、2 秒間隔，理論上有 10 個點，但要被 MAX_FRAMES_PER_SCENE 上限擋住
    timestamps = ocr_service._sample_timestamps(0.0, 20.0)
    assert len(timestamps) == ocr_service.MAX_FRAMES_PER_SCENE
    assert timestamps[0] == 0.0
    assert timestamps[1] - timestamps[0] == ocr_service.SAMPLE_INTERVAL_SEC


def test_merge_candidates_groups_same_normalized_text():
    hits = [
        (10.0, OcrCandidate(text="ABC-1234", confidence=0.6, bbox=[(0.0, 0.0)])),
        (12.0, OcrCandidate(text="ABC-1234", confidence=0.9, bbox=[(1.0, 1.0)])),
    ]
    events = ocr_service._merge_candidates(
        video_id=1, segment_id=99, scene_start=9.0, scene_end=14.0, frame_hits=hits
    )
    assert len(events) == 1
    event = events[0]
    assert event.resolved_text == "ABC-1234"
    assert event.confidence == 0.9  # 取信心分數最高的那筆代表
    assert event.bbox == [(1.0, 1.0)]
    assert event.segment_id == 99
    assert event.video_id == 1
    assert 9.0 <= event.start_sec <= event.frame_sec <= event.end_sec <= 14.0


def test_merge_candidates_keeps_distinct_texts_separate():
    hits = [
        (10.0, OcrCandidate(text="ABC-1234", confidence=0.6, bbox=None)),
        (12.0, OcrCandidate(text="XYZ-9999", confidence=0.7, bbox=None)),
    ]
    events = ocr_service._merge_candidates(
        video_id=1, segment_id=None, scene_start=9.0, scene_end=14.0, frame_hits=hits
    )
    assert {e.resolved_text for e in events} == {"ABC-1234", "XYZ-9999"}


def test_merge_candidates_clamps_event_range_to_scene_bounds():
    # 場景很短、pad 會把範圍推出場景邊界，必須 clamp 回場景範圍內
    hits = [(10.0, OcrCandidate(text="X", confidence=0.5, bbox=None))]
    events = ocr_service._merge_candidates(
        video_id=1, segment_id=None, scene_start=9.9, scene_end=10.1, frame_hits=hits
    )
    assert events[0].start_sec >= 9.9
    assert events[0].end_sec <= 10.1


def test_merge_candidates_empty_input_returns_no_events():
    assert ocr_service._merge_candidates(1, None, 0.0, 5.0, []) == []


def test_scan_scenes_empty_input_returns_no_events():
    assert ocr_service.scan_scenes(1, "unused/path.mp4", []) == []


def test_scan_scenes_breadth_first_round_order(monkeypatch):
    """每一輪要先讓全部場景都拿到那一輪的畫面，才能進下一輪——不能有場景在
    別的場景還沒拿到第 1 張畫面時，就先被抽第 2、3 張。"""
    calls: list[float] = []

    def fake_recognize_frame(video_path, at_sec):
        calls.append(at_sec)
        return []

    monkeypatch.setattr(ocr_service, "_recognize_frame", fake_recognize_frame)

    # 3 個場景各 10 秒長，2 秒間隔、上限 5 張 → 每個場景都會有 5 個取樣點，
    # 相對位移分別是 0/2/4/6/8 秒。
    scenes = [(0.0, 10.0, None), (100.0, 110.0, None), (200.0, 210.0, None)]
    ocr_service.scan_scenes(1, _DUMMY_VIDEO_PATH, scenes)

    expected_rounds = [
        {0.0, 100.0, 200.0},
        {2.0, 102.0, 202.0},
        {4.0, 104.0, 204.0},
        {6.0, 106.0, 206.0},
        {8.0, 108.0, 208.0},
    ]
    scenes_per_round = len(scenes)
    assert len(calls) == scenes_per_round * len(expected_rounds)
    for round_index, expected in enumerate(expected_rounds):
        chunk = calls[round_index * scenes_per_round : (round_index + 1) * scenes_per_round]
        assert set(chunk) == expected


def test_scan_scenes_stops_between_rounds_when_time_budget_exceeded(monkeypatch):
    """預算在第 1 輪跑完、進入第 2 輪的檢查點才用完：第 2 輪完全不該開始，
    但每個場景仍然至少拿到 1 張畫面，不會有場景是 0 張。"""
    calls: list[float] = []

    def fake_recognize_frame(video_path, at_sec):
        calls.append(at_sec)
        return []

    monkeypatch.setattr(ocr_service, "_recognize_frame", fake_recognize_frame)

    call_count = {"n": 0}

    def fake_monotonic():
        call_count["n"] += 1
        # 第 1 次呼叫記錄 start_time；第 2~4 次呼叫是第 1 輪 3 個場景的逐張檢查
        # （都回傳未超時）；第 5 次呼叫是第 2 輪第一個場景的檢查，回傳已超時。
        return 0.0 if call_count["n"] <= 4 else ocr_service.TIME_BUDGET_SEC + 10.0

    monkeypatch.setattr(ocr_service.time, "monotonic", fake_monotonic)

    scenes = [(0.0, 10.0, None), (100.0, 110.0, None), (200.0, 210.0, None)]
    ocr_service.scan_scenes(1, _DUMMY_VIDEO_PATH, scenes)

    assert calls == [0.0, 100.0, 200.0]


def test_scan_scenes_stops_mid_round_when_time_budget_exceeded(monkeypatch):
    """預算用完的時間點不必等到一輪跑完——同一輪內也要能立刻停止，不會浪費
    時間硬跑完剩下的場景。"""
    calls: list[float] = []

    def fake_recognize_frame(video_path, at_sec):
        calls.append(at_sec)
        return []

    monkeypatch.setattr(ocr_service, "_recognize_frame", fake_recognize_frame)

    call_count = {"n": 0}

    def fake_monotonic():
        call_count["n"] += 1
        # 第 1 次呼叫記錄 start_time；第 2 次呼叫（場景 0 的檢查）回傳未超時；
        # 第 3 次呼叫（場景 1 的檢查）回傳已超時，場景 1、2 都不該被掃到。
        return 0.0 if call_count["n"] <= 2 else ocr_service.TIME_BUDGET_SEC + 10.0

    monkeypatch.setattr(ocr_service.time, "monotonic", fake_monotonic)

    scenes = [(0.0, 10.0, None), (100.0, 110.0, None), (200.0, 210.0, None)]
    ocr_service.scan_scenes(1, _DUMMY_VIDEO_PATH, scenes)

    assert calls == [0.0]


def test_scan_scenes_matches_hits_to_correct_scene(monkeypatch):
    """回合制分派不能把命中結果配對到錯的場景／segment_id。"""

    def fake_recognize_frame(video_path, at_sec):
        return [OcrCandidate(text=f"TXT-{at_sec}", confidence=0.9, bbox=None)]

    monkeypatch.setattr(ocr_service, "_recognize_frame", fake_recognize_frame)

    scenes = [(0.0, 1.0, 11), (50.0, 51.0, 22), (100.0, 101.0, 33)]
    events = ocr_service.scan_scenes(1, _DUMMY_VIDEO_PATH, scenes)

    by_segment = {event.segment_id: event.resolved_text for event in events}
    assert by_segment == {11: "TXT-0.0", 22: "TXT-50.0", 33: "TXT-100.0"}
