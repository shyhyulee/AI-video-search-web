"""segment_material.py：片段攤成 LLM 素材的共用格式。

這些行為原本只有 document.py 那一側有測試（測的是 `document._build_content()`），
summary.py 那一側完全沒有——而兩邊本來是各自一份實作。合併之後測試也跟著搬到
共用模組這裡，並補上 `include_ocr=False`（摘要）那條路徑。

用 SimpleNamespace 假造片段（duck typing），跟 test_summary.py／test_document.py
同一套隔離方式，不需要資料庫。
"""
from __future__ import annotations

from types import SimpleNamespace

from ai_video_search_web.pipeline import segment_material


def _segment(
    start_sec: float = 0.0,
    transcript: str | None = None,
    visual_description: str | None = None,
    ocr_text: str | None = None,
):
    return SimpleNamespace(
        start_sec=start_sec,
        transcript=transcript,
        visual_description=visual_description,
        ocr_text=ocr_text,
    )


# ----------------------------------------------------------------------
# format_timestamp()
# ----------------------------------------------------------------------
def test_format_timestamp_pads_to_two_digits():
    assert segment_material.format_timestamp(0.0) == "00:00"
    assert segment_material.format_timestamp(77.0) == "01:17"
    assert segment_material.format_timestamp(9.9) == "00:09"  # 無條件捨去，不四捨五入


def test_format_timestamp_keeps_counting_minutes_past_an_hour():
    """不進位成 HH:MM:SS——分析長度上限是 1 小時，分鐘數最多兩位。"""
    assert segment_material.format_timestamp(3600.0) == "60:00"


# ----------------------------------------------------------------------
# build_material()：共用格式
# ----------------------------------------------------------------------
def test_uses_timestamp_prefix_and_skips_empty_segments():
    content = segment_material.build_material([
        _segment(start_sec=77.0, transcript="第一步"),
        _segment(start_sec=90.0),  # 欄位全空的片段不該產生空行
    ])

    assert content == "[01:17] 字幕：第一步"


def test_joins_fields_in_a_fixed_order_with_a_full_width_semicolon():
    """欄位順序固定（畫面→字幕→畫面文字），順序換掉等於換了餵給模型的素材。"""
    content = segment_material.build_material(
        [_segment(visual_description="產線畫面", transcript="這是第一步", ocr_text="STAGE 3")],
        include_ocr=True,
    )

    assert content == "[00:00] 畫面：產線畫面；字幕：這是第一步；畫面文字：STAGE 3"


def test_one_line_per_segment():
    segments = [_segment(start_sec=float(i * 10), transcript=f"第{i}步") for i in range(250)]

    content = segment_material.build_material(segments)

    assert len(content.splitlines()) == 250
    assert "第249步" in content


# ----------------------------------------------------------------------
# include_ocr：摘要不帶畫面文字，文件要帶
# ----------------------------------------------------------------------
def test_ocr_text_is_left_out_by_default():
    """摘要那一側（include_ocr 預設 False）不吃畫面文字。"""
    content = segment_material.build_material(
        [_segment(visual_description="產線畫面", ocr_text="STAGE 3")]
    )

    assert "畫面：產線畫面" in content
    assert "畫面文字" not in content


def test_ocr_text_is_included_when_asked():
    """實測 1,076/1,156 個片段有畫面文字，對流程類影片特別有價值
    （`STAGE 3` 這種製程階段標示），文件那一側要用。"""
    content = segment_material.build_material(
        [_segment(visual_description="產線畫面", ocr_text="STAGE 3")], include_ocr=True
    )

    assert "畫面文字：STAGE 3" in content


def test_a_segment_with_only_ocr_text_disappears_when_ocr_is_off():
    """只有畫面文字的片段，在摘要那一側整行消失（沒有欄位可寫就不留空行）。"""
    assert segment_material.build_material([_segment(ocr_text="STAGE 3")]) == ""


# ----------------------------------------------------------------------
# 佔位字串過濾
# ----------------------------------------------------------------------
def test_drops_literal_null_placeholders():
    """VLM 偶爾把「沒有畫面文字」寫成字面字串 "null"（實測 1,156 個片段裡有
    21 個）。不濾掉就會餵一堆 null 給模型當畫面文字。"""
    content = segment_material.build_material(
        [_segment(visual_description="產線畫面", ocr_text="null")], include_ocr=True
    )

    assert "畫面文字" not in content
    assert "畫面：產線畫面" in content


def test_placeholder_filtering_is_case_insensitive_and_covers_every_field():
    """過濾套用在三個欄位上，不是只有畫面文字——合併前 summary.py 那一側
    完全沒有這層過濾，實測全庫 1,156 個片段的輸出不受影響（沒有任何字幕或
    畫面描述剛好是佔位字串），但共用之後兩邊行為一致。"""
    content = segment_material.build_material(
        [_segment(visual_description="NULL", transcript="無", ocr_text="N/A")], include_ocr=True
    )

    assert content == ""


def test_strips_surrounding_whitespace():
    content = segment_material.build_material([_segment(transcript="  第一步  ")])

    assert content == "[00:00] 字幕：第一步"
