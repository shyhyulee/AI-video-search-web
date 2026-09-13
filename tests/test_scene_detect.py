"""場景長度正規化（merge/split）邏輯測試。純測時間區間運算，不需要真的影片檔案。"""
from __future__ import annotations

from ai_video_search_web.pipeline import scene_detect


def test_merge_short_scenes_leaves_long_scenes_untouched():
    scenes = [(0.0, 10.0), (10.0, 20.0)]
    assert scene_detect._merge_short_scenes(scenes) == scenes


def test_merge_short_scenes_combines_until_threshold_reached():
    # 4+4 = 8 秒，剛好達到門檻，應該合併成一個場景
    scenes = [(0.0, 4.0), (4.0, 8.0)]
    assert scene_detect._merge_short_scenes(scenes) == [(0.0, 8.0)]


def test_merge_short_scenes_starts_new_buffer_after_commit():
    # 前 8 秒合併成一個場景後，後面單獨一個 11 秒場景不該被牽連
    scenes = [(0.0, 4.0), (4.0, 8.0), (8.0, 19.0)]
    assert scene_detect._merge_short_scenes(scenes) == [(0.0, 8.0), (8.0, 19.0)]


def test_merge_short_scenes_trailing_remainder_merges_into_previous():
    # 結尾的 1 秒場景永遠湊不到 8 秒門檻，併進前一個已提交的場景
    scenes = [(0.0, 9.0), (9.0, 10.0)]
    assert scene_detect._merge_short_scenes(scenes) == [(0.0, 10.0)]


def test_merge_short_scenes_all_short_with_no_previous_scene():
    # 整支影片累積起來都不到門檻，且沒有前一個場景可以併，保留原樣
    scenes = [(0.0, 1.0), (1.0, 2.0)]
    assert scene_detect._merge_short_scenes(scenes) == [(0.0, 2.0)]


def test_merge_short_scenes_empty_input():
    assert scene_detect._merge_short_scenes([]) == []


# ----------------------------------------------------------------------
# _split_long_scenes()：回傳 NormalizedScene（見 scene_detect.py 的說明），
# 除了 start_sec／end_sec 之外還帶 source_raw_duration（切分前的原始長度）——
# pipeline/analyzer/phases.py 曾用它判斷要不要對這個場景觸發多幀 VLM 取樣（現在一律三幀）。
# ----------------------------------------------------------------------


def test_split_long_scenes_leaves_short_scenes_untouched():
    scenes = [(0.0, 8.0), (8.0, 20.0)]  # 12 秒剛好等於門檻，不切
    result = scene_detect._split_long_scenes(scenes)
    assert [(s.start_sec, s.end_sec) for s in result] == scenes
    # 沒被切過：source_raw_duration 就是自己的長度
    assert result[0].source_raw_duration == 8.0
    assert result[1].source_raw_duration == 12.0


def test_split_long_scenes_divides_evenly():
    # 40 秒場景 -> round(40/10.0)=4 段，每段 10.0 秒
    result = scene_detect._split_long_scenes([(0.0, 40.0)])
    assert len(result) == 4
    assert all(abs((s.end_sec - s.start_sec) - 10.0) < 1e-9 for s in result)
    # 首尾要對齊原始場景邊界，中間銜接處不能有縫隙或重疊
    assert result[0].start_sec == 0.0
    assert result[-1].end_sec == 40.0
    for prev, nxt in zip(result, result[1:]):
        assert prev.end_sec == nxt.start_sec
    # 每一段都要標記自己來自同一個 40 秒的原始場景
    assert all(s.source_raw_duration == 40.0 for s in result)


def test_split_long_scenes_stays_single_piece_when_two_pieces_would_violate_floor():
    # 15.5 秒：round(15.5/10.0)=2，但切 2 段每段 7.75 秒會低於 MERGE_BELOW_SEC
    # (8.0) 下限，while 迴圈把 piece_count 降回 1——寧可保留單一超長片段
    result = scene_detect._split_long_scenes([(0.0, 15.5)])
    assert len(result) == 1
    assert (result[0].start_sec, result[0].end_sec) == (0.0, 15.5)
    # 沒有真的切開，source_raw_duration 等於自己的長度
    assert result[0].source_raw_duration == 15.5


def test_split_long_scenes_splits_when_pieces_still_meet_floor():
    # 20 秒場景切成 2 段、每段 10 秒，仍然 >= 8 秒下限，可以安全切開
    result = scene_detect._split_long_scenes([(0.0, 20.0)])
    assert len(result) == 2
    assert all(abs((s.end_sec - s.start_sec) - 10.0) < 1e-9 for s in result)
    assert all(s.source_raw_duration == 20.0 for s in result)


def test_split_long_scenes_source_raw_duration_distinguishes_multiple_scenes():
    # 兩個各自超長的場景分開處理，不該互相污染 source_raw_duration
    result = scene_detect._split_long_scenes([(0.0, 40.0), (40.0, 100.0)])
    first_group = [s for s in result if s.start_sec < 40.0]
    second_group = [s for s in result if s.start_sec >= 40.0]
    assert all(s.source_raw_duration == 40.0 for s in first_group)
    assert all(s.source_raw_duration == 60.0 for s in second_group)


def test_normalize_scene_lengths_end_to_end_stays_within_bounds():
    # merge 再 split 組合：短場景群 + 一個長場景
    scenes = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 40.0)]
    result = scene_detect._normalize_scene_lengths(scenes)
    assert result[0].start_sec == 0.0
    assert result[-1].end_sec == 40.0
    for s in result:
        assert (s.end_sec - s.start_sec) <= scene_detect.SPLIT_ABOVE_SEC + 1e-6


def test_to_ranges_normalizes_the_no_scene_fallback():
    # 完全沒偵測到切換時，_to_ranges 原本會回傳涵蓋全片的單一場景；
    # 這裡驗證這個 fallback 也會被 split pass 收斂，不會是一個 30 秒的巨大場景
    result = scene_detect._to_ranges([], duration_sec=30.0)
    assert result[0].start_sec == 0.0
    assert result[-1].end_sec == 30.0
    assert all((s.end_sec - s.start_sec) <= scene_detect.SPLIT_ABOVE_SEC + 1e-6 for s in result)
    assert len(result) > 1
