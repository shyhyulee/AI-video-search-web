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
def test_timestamp_prefix_carries_both_mmss_and_raw_seconds():
    """兩種格式都給不是裝飾：`VideoDocument.timestamp_sec` 要的是秒，只給
    MM:SS 等於逼模型自己換算——實測它常常把 `[03:18]` 的 18 直接抄過去，
    整份文件的時間戳就塌在一分鐘內。見 segment_material 的 docstring。"""
    content = segment_material.build_material([_segment(start_sec=198.0, transcript="第一步")])

    assert content == "[03:18｜198 秒] 字幕：第一步"


def test_field_newlines_are_flattened_so_one_segment_is_one_line():
    """prompt 開頭宣告「每行是一個片段」。VLM 抓到的畫面文字常常自己帶換行，
    不壓掉的話那些行沒有時間戳前綴，模型無從得知它們屬於哪個片段。"""
    content = segment_material.build_material(
        [_segment(visual_description="第一行\n第二行", ocr_text="AAA\nBBB")],
        include_ocr=True,
    )

    assert len(content.splitlines()) == 1
    assert content == "[00:00｜0 秒] 畫面：第一行 第二行；畫面文字：AAA BBB"


def test_uses_timestamp_prefix_and_skips_empty_segments():
    content = segment_material.build_material([
        _segment(start_sec=77.0, transcript="第一步"),
        _segment(start_sec=90.0),  # 欄位全空的片段不該產生空行
    ])

    assert content == "[01:17｜77 秒] 字幕：第一步"


def test_joins_fields_in_a_fixed_order_with_a_full_width_semicolon():
    """欄位順序固定（畫面→字幕→畫面文字），順序換掉等於換了餵給模型的素材。"""
    content = segment_material.build_material(
        [_segment(visual_description="產線畫面", transcript="這是第一步", ocr_text="STAGE 3")],
        include_ocr=True,
    )

    assert content == "[00:00｜0 秒] 畫面：產線畫面；字幕：這是第一步；畫面文字：STAGE 3"


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

    assert content == "[00:00｜0 秒] 字幕：第一步"


# ----------------------------------------------------------------------
# 幻覺字幕與浮水印：影片層級的重複偵測
# ----------------------------------------------------------------------
def _segments_with_transcripts(texts: list[str]):
    return [
        _segment(start_sec=float(i * 10), transcript=t, visual_description=f"畫面{i}")
        for i, t in enumerate(texts)
    ]


def test_drops_the_whole_transcript_column_when_one_line_dominates():
    """純環境音影片的 Whisper 幻覺：整支一直重複同一句罐頭台詞。實測 BMW 那支
    97 句字幕裡 70 句是 `Thank you for watching.`（72%），而字幕欄是噪音時還會
    稀釋掉真正有訊號的 ocr_text——那支有 67 句各自不同的製程旁白，文件卻只
    寫出 7 個步驟。"""
    segments = _segments_with_transcripts(["Thank you for watching."] * 8 + ["真的內容"] * 2)

    content = segment_material.build_material(segments)

    assert "字幕" not in content
    assert "Thank you for watching." not in content
    # 剩下的兩句雖然不一樣，也一起丟——實測那 28% 是同一類垃圾（BMW 的 9 個
    # unique 全是 thanks-for-watching 的變體），逐句挑不出訊號。
    assert "真的內容" not in content
    assert len(content.splitlines()) == 10  # 畫面描述還在，行數不變


def test_keeps_transcripts_when_repetition_looks_like_real_speech():
    """真實語音也會重複（口頭禪、賽事播報的固定句型），門檻不能訂太低。實測
    全庫有語音的影片重複率最高 26%（video 1，39 句），跟幻覺的 65%～79% 中間
    有一大段空隙。"""
    segments = _segments_with_transcripts(["好的"] * 3 + [f"第{i}句" for i in range(9)])

    content = segment_material.build_material(segments)

    assert "字幕：好的" in content
    assert "字幕：第8句" in content


def test_does_not_judge_junk_on_too_few_samples():
    """整支只有 3 句字幕、其中 2 句剛好一樣就會湊出 67%，那是樣本雜訊不是幻覺
    訊號。壽司那支（5 個片段）就是這種情況——它的字幕確實是 Whisper 幻覺，但
    這裡選擇不判定，寧可漏掉也不要在小樣本上誤殺。"""
    segments = _segments_with_transcripts(["同一句", "同一句", "另一句"])

    content = segment_material.build_material(segments)

    assert "字幕：同一句" in content


def test_drops_only_the_repeated_watermark_from_ocr_not_the_whole_column():
    """OCR 的處理**刻意跟字幕不同**：重複的通常是頻道浮水印（實測 BMW／Intel
    是 `FRAME`、龍隊是 `CPBL TV`、Messi 是 `SPORTS HD`），但同一欄的其他內容
    正是流程類影片的主要訊號，不能整欄丟。"""
    segments = [
        _segment(start_sec=float(i * 10), visual_description=f"畫面{i}", ocr_text=ocr)
        for i, ocr in enumerate(["FRAME"] * 4 + [f"STAGE {i}" for i in range(6)])
    ]

    content = segment_material.build_material(segments, include_ocr=True)

    assert "FRAME" not in content
    assert "畫面文字：STAGE 3" in content


def test_watermark_filtering_is_off_when_ocr_is_off():
    """摘要那一側不帶畫面文字，就不用（也不該）花力氣算浮水印。"""
    segments = [
        _segment(start_sec=float(i * 10), visual_description=f"畫面{i}", ocr_text="FRAME")
        for i in range(10)
    ]

    assert "畫面文字" not in segment_material.build_material(segments)


def test_a_segment_left_with_nothing_after_filtering_disappears():
    """只有幻覺字幕、沒有其他欄位的片段，濾掉之後整行消失而不是留下空前綴。"""
    segments = [_segment(start_sec=float(i * 10), transcript="Thank you.") for i in range(10)]

    assert segment_material.build_material(segments) == ""


# ----------------------------------------------------------------------
# is_transcript_column_junk()：build_material() 與 analyzer._is_visual_only()
# 共用的「這支影片的字幕整欄有沒有用」判斷
# ----------------------------------------------------------------------


def test_transcript_column_junk_when_one_line_dominates():
    texts = ["Thank you for watching."] * 7 + ["真正的內容"] * 3
    assert segment_material.is_transcript_column_junk(texts) is True


def test_transcript_column_not_junk_when_varied():
    assert segment_material.is_transcript_column_junk([f"第 {i} 句話" for i in range(10)]) is False


def test_transcript_column_not_junk_below_sample_floor():
    # 樣本太少不判定：3 句裡重複 2 句就湊得出 67%，那是樣本雜訊不是幻覺訊號
    assert segment_material.is_transcript_column_junk(["一樣", "一樣", "不一樣"]) is False


def test_transcript_column_junk_ignores_empty_and_placeholder_lines():
    """空字串與 VLM 的字面佔位字串不算樣本——否則一支只有兩句真實字幕、
    其餘全空的影片會因為「空字串佔多數」被誤判成整欄幻覺。"""
    texts = ["", None, "null", "無"] * 5 + ["第一句", "第二句"]
    assert segment_material.is_transcript_column_junk(texts) is False


def test_transcript_column_junk_when_no_transcript_at_all():
    """完全沒有字幕（純畫面影片）**不算**整欄幻覺——樣本數是 0，低於下限。

    這是刻意的：analyzer 那邊「沒有音軌」已經另外走 has_audio_stream() 判斷，
    這支只負責「有字幕但整欄是垃圾」那一種。"""
    assert segment_material.is_transcript_column_junk([]) is False


def test_material_time_range_reads_the_first_and_last_line():
    material = segment_material.build_material(
        [_segment(start_sec=12.0, visual_description="開場"),
         _segment(start_sec=198.0, visual_description="收尾")]
    )
    assert segment_material.material_time_range(material) == (12, 198)


def test_material_time_range_ignores_segments_that_never_reached_the_material():
    """範圍要照素材算，不是照片段算。

    最後一個片段三欄全空時它不會出現在素材裡，模型看不到它——這時如果把範圍
    報成 300 秒，document.py 的第四條規則就會叫模型寫到一個素材裡不存在的地方，
    等於親手要求它編造尾段步驟。
    """
    material = segment_material.build_material(
        [_segment(start_sec=12.0, visual_description="開場"),
         _segment(start_sec=198.0, visual_description="收尾"),
         _segment(start_sec=300.0)]
    )
    assert segment_material.material_time_range(material) == (12, 198)


def test_material_time_range_is_none_when_nothing_survived():
    assert segment_material.material_time_range("") is None
