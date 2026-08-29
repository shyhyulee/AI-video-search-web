"""document.py 的文件整理與 prompt 組裝測試：mock OpenAI client，不呼叫真實 API。

跟 test_summary.py 同一套隔離方式（MagicMock client + SimpleNamespace 假
response + duck-typed segments）。這裡多測的是三件跟摘要不一樣的行為：
會帶 ocr_text、會濾掉 VLM 產生的字面佔位字串、不做片段數硬截斷。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_video_search_web.pipeline import document


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


def _document(doc_type: str = "sop") -> document.VideoDocument:
    return document.VideoDocument(
        doc_type=doc_type,
        title="主板生產流程",
        overview="這份文件整理了主板產線的製程步驟。",
        sections=[
            document.DocumentSection(
                heading="表面貼裝",
                steps=[
                    document.DocumentStep(timestamp_sec=77.0, heading="塗矽膏", detail="用刷子把矽膏刷過鋼板。")
                ],
            )
        ],
        uncovered=["迴焊爐的溫度曲線影片沒有交代"],
    )


def _fake_response(parsed, prompt_tokens: int, completion_tokens: int):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def test_generate_document_returns_parsed_and_computes_cost():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        _document(), prompt_tokens=20000, completion_tokens=3000,
    )

    result = document.generate_document(client, "技嘉主板工廠", [_segment(transcript="哈囉")])

    assert result.document.doc_type == "sop"
    assert result.document.sections[0].steps[0].timestamp_sec == 77.0
    expected = (
        20000 * document.PRICE_INPUT_PER_TOKEN_USD + 3000 * document.PRICE_OUTPUT_PER_TOKEN_USD
    )
    assert result.cost_usd == pytest.approx(expected)


def test_generate_document_missing_usage_returns_zero_cost():
    client = MagicMock()
    response = _fake_response(_document(), prompt_tokens=0, completion_tokens=0)
    response.usage = None
    client.chat.completions.parse.return_value = response

    result = document.generate_document(client, "影片", [_segment(transcript="哈囉")])

    assert result.cost_usd == 0.0


def test_generate_document_raises_without_segments():
    with pytest.raises(ValueError):
        document.generate_document(MagicMock(), "影片", [])


def test_generate_document_raises_when_parsed_is_none():
    """refusal 或輸出被截斷時 parsed 會是 None。這裡沒有合理的空文件可退，
    要丟錯而不是把空殼存進資料庫。"""
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(None, 100, 10)

    with pytest.raises(ValueError):
        document.generate_document(client, "影片", [_segment(transcript="哈囉")])


def test_generate_document_rejects_absurd_segment_count_instead_of_truncating():
    """刻意不學摘要的 `segments[:200]` 硬截斷：SOP 少掉尾段等於少掉最後幾個
    製程步驟，比直接失敗更糟。"""
    client = MagicMock()
    too_many = [_segment(start_sec=float(i), transcript="x") for i in range(document._MAX_SEGMENTS + 1)]

    with pytest.raises(ValueError, match="超過上限"):
        document.generate_document(client, "影片", too_many)


# ----------------------------------------------------------------------
# _build_content()：素材怎麼攤成 prompt
# ----------------------------------------------------------------------


def test_build_content_includes_ocr_text_unlike_summary():
    """實測 1,076/1,156 個片段有畫面文字，而且對流程類影片特別有價值
    （`STAGE 3` 這種製程階段標示），摘要沒用它、這裡要用。"""
    content = document._build_content(
        [_segment(start_sec=0.0, visual_description="產線畫面", transcript="這是第一步", ocr_text="STAGE 3")]
    )

    assert "畫面：產線畫面" in content
    assert "字幕：這是第一步" in content
    assert "畫面文字：STAGE 3" in content


def test_build_content_drops_literal_null_placeholders():
    """VLM 偶爾把「沒有畫面文字」寫成字面字串 "null"（實測 1,156 個片段裡有
    21 個）。不濾掉就會餵一堆 null 給模型當畫面文字。"""
    content = document._build_content(
        [_segment(start_sec=0.0, visual_description="產線畫面", ocr_text="null")]
    )

    assert "畫面文字" not in content
    assert "畫面：產線畫面" in content


def test_build_content_uses_timestamp_prefix_and_skips_empty_segments():
    content = document._build_content([
        _segment(start_sec=77.0, transcript="第一步"),
        _segment(start_sec=90.0),  # 三個欄位都空的片段不該產生空行
    ])

    assert content == "[01:17] 字幕：第一步"


def test_build_content_keeps_every_segment():
    """摘要會截到 200 段，這裡全部保留。"""
    segments = [_segment(start_sec=float(i * 10), transcript=f"第{i}步") for i in range(250)]

    content = document._build_content(segments)

    assert len(content.splitlines()) == 250
    assert "第249步" in content


def test_prompt_carries_video_title_and_material():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(_document(), 100, 10)

    document.generate_document(client, "技嘉主板工廠", [_segment(transcript="塗矽膏")])

    prompt = client.chat.completions.parse.call_args.kwargs["messages"][0]["content"]
    assert "技嘉主板工廠" in prompt
    assert "字幕：塗矽膏" in prompt
    # 三條硬要求要真的在 prompt 裡
    assert "以畫面描述為準" in prompt
    assert "content_log" in prompt


def test_prompt_asks_overview_to_read_as_a_video_summary():
    """overview 一稿兩用——它會被寫回 videos.summary，然後餵給搜尋的影片層級
    篩選與影片庫的主題分類。所以 prompt 必須要求它寫成「影片在講什麼」，
    不能是「本文件涵蓋什麼」，否則那三條下游都會吃到走味的文字。"""
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(_document(), 100, 10)

    document.generate_document(client, "影片", [_segment(transcript="x")])

    prompt = client.chat.completions.parse.call_args.kwargs["messages"][0]["content"]
    assert "這支影片**主要在講什麼" in prompt
    assert "不要用「本文件」" in prompt


def test_doc_type_labels_cover_every_document_type():
    """DOC_TYPE_LABELS 是前端顯示的來源，漏一個就會出現空白標籤。"""
    from typing import get_args

    assert set(DOC_TYPES := get_args(document.DocumentType)) == set(document.DOC_TYPE_LABELS)
    assert "content_log" in DOC_TYPES  # 不適合的影片要有退路
