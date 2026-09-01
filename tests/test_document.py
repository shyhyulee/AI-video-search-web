"""document.py 的文件整理與 prompt 組裝測試：mock OpenAI client，不呼叫真實 API。

跟 test_summary.py 同一套隔離方式（MagicMock client + SimpleNamespace 假
response + duck-typed segments）。

素材本身怎麼攤成逐行文字，已經跟 summary.py 共用，測試搬到
tests/test_segment_material.py；這裡只留 document.py 自己的行為：doc_type
判斷、片段數上限、prompt 組裝與成本計算。
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


def _continuation() -> document._Continuation:
    return document._Continuation(
        heading="成品檢查與出貨",
        steps=[
            document.DocumentStep(timestamp_sec=580.0, heading="出貨前檢查", detail="逐片檢查焊點。")
        ],
        uncovered=["包裝方式影片沒有交代"],
    )


def _segments_reaching(*seconds: float):
    """一支素材延伸到 seconds[-1] 秒的影片。"""
    return [_segment(start_sec=s, visual_description=f"第 {s:.0f} 秒的畫面") for s in seconds]


# 一份只寫到 77 秒、素材卻延伸到 600 秒的文件——補寫要救的就是這一種。
# 門檻是素材的九成（540 秒），77 遠遠不到。
_STOPS_EARLY = (0.0, 77.0, 300.0, 580.0, 600.0)


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


def test_prompt_states_the_material_time_range_and_a_tail_threshold():
    """第四條規則要讓模型知道素材延伸到第幾秒，否則它會寫完前面幾分鐘就停。

    這是 2026-09-01 那輪的修法：同一份素材、同一版程式跑三次，涵蓋率是
    101.6%／31.6%／97.8%——問題不是水準低，是變異大到一次抽樣就能產出一份
    停在前半段的文件。三個秒數必須是**從素材算出來的**，寫死或算錯都會讓規則
    指向錯的地方，所以這裡連數值一起斷言。
    """
    client = MagicMock()
    # 這份素材延伸到 600 秒而 _document() 只寫到 77 秒，會觸發補寫（另有測試涵蓋），
    # 所以第二次呼叫也要餵一個像樣的回應。這裡只看第一次的 prompt。
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 100, 10),
        _fake_response(_continuation(), 100, 10),
    ]

    document.generate_document(
        client,
        "影片",
        [_segment(start_sec=12.0, visual_description="開場"), _segment(start_sec=600.0, visual_description="收尾")],
    )

    prompt = client.chat.completions.parse.call_args_list[0].kwargs["messages"][0]["content"]
    assert "從第 12 秒延伸到第 600 秒" in prompt
    assert "最後一個步驟應該落在第 540 秒之後" in prompt  # 600 的九成


def test_prompt_keeps_the_do_not_invent_guardrail_next_to_the_coverage_rule():
    """涵蓋率規則一定要跟「沒有就寫 uncovered」綁在一起。

    docs/18 §6.2 的教訓：代理指標擋得住退步、擋不住幻覺。單獨要求「寫到片尾」
    會讓涵蓋率全面勝出而尾段是編的——那比停在前半段更糟，因為它看起來是完整的。
    """
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(_document(), 100, 10)

    document.generate_document(client, "影片", [_segment(visual_description="開場")])

    prompt = client.chat.completions.parse.call_args.kwargs["messages"][0]["content"]
    assert "絕對不要發明步驟去填滿" in prompt
    assert "寫進 uncovered" in prompt


def test_generate_document_raises_when_every_segment_is_empty():
    """素材整份是空的時候不要送出去問。

    片段存在但三個欄位都空（VLM 整支失敗，或字幕整欄被判定成幻覺而丟掉）時，
    模型手上沒有任何依據，只會整份編造。跟 parsed is None 一樣沒有合理的空文件
    可退，直接丟錯。
    """
    client = MagicMock()

    with pytest.raises(ValueError, match="沒有任何可用內容"):
        document.generate_document(client, "影片", [_segment(), _segment(start_sec=10.0)])

    client.chat.completions.parse.assert_not_called()


def test_a_document_that_stops_early_gets_the_tail_written_and_both_costs_counted():
    """停在前半段就再問一次，把補到的接成新的一節。

    第四條規則把 v37 的涵蓋率從平均 32.5% 拉到 88.0%，但 12 次裡仍有 3 次落在
    38.6%～70.3%——prompt 改得動分布，保證不了每一次，而使用者拿到的就是「這一次」。
    """
    client = MagicMock()
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 20000, 3000),
        _fake_response(_continuation(), 5000, 500),
    ]

    result = document.generate_document(client, "影片", _segments_reaching(*_STOPS_EARLY))

    assert client.chat.completions.parse.call_count == 2
    assert [s.heading for s in result.document.sections] == ["表面貼裝", "成品檢查與出貨"]
    assert result.document.sections[-1].steps[0].timestamp_sec == 580.0
    assert result.document.uncovered == ["迴焊爐的溫度曲線影片沒有交代", "包裝方式影片沒有交代"]
    # 兩次呼叫的費用都要算進去，否則 videos.cost_usd 會少記
    assert result.cost_usd == pytest.approx(
        20000 * document.PRICE_INPUT_PER_TOKEN_USD + 3000 * document.PRICE_OUTPUT_PER_TOKEN_USD
        + 5000 * document.PRICE_INPUT_PER_TOKEN_USD + 500 * document.PRICE_OUTPUT_PER_TOKEN_USD
    )


def test_the_continuation_only_sees_material_that_was_not_written_yet():
    """補寫只餵沒被寫過的那一段——這是這個設計唯一的防幻覺依據。

    模型手上只有真素材，就補不出素材裡沒有的東西；連同「已經寫到第幾秒」一起
    告訴它，才不會把前面重寫一遍。
    """
    client = MagicMock()
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 100, 10),
        _fake_response(_continuation(), 100, 10),
    ]

    document.generate_document(client, "影片", _segments_reaching(*_STOPS_EARLY))

    prompt = client.chat.completions.parse.call_args_list[1].kwargs["messages"][0]["content"]
    assert "第 300 秒的畫面" in prompt
    assert "第 580 秒的畫面" in prompt
    assert "第 0 秒的畫面" not in prompt  # 已經寫過的不要重餵
    assert "第 77 秒的畫面" not in prompt
    assert "已經整理到第 77 秒" in prompt
    assert "不要為了填滿而發明步驟" in prompt


def test_content_log_is_never_continued():
    """時間軸紀錄不補。實測同一套補寫在 SOP 上補了 6 個對得上素材的步驟，在球賽
    精華上補出約 25 個、幾乎一行素材一步，內容是「比賽結束的信號｜最終鳴哨結束
    比賽」這種填充句（棒球沒有鳴哨）。

    差別可以解釋：時間軸紀錄的每一行素材本身就是內容，模型於是全部記成步驟。逼
    一份本來就沒有流程的文件寫到片尾，只會生出看起來完整、實際是湊的東西。
    """
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(_document("content_log"), 100, 10)

    result = document.generate_document(client, "影片", _segments_reaching(*_STOPS_EARLY))

    assert client.chat.completions.parse.call_count == 1
    assert len(result.document.sections) == 1


def test_a_document_that_already_reaches_the_end_is_not_continued():
    """已經寫到門檻之後就不要多花一次呼叫。"""
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(_document(), 100, 10)

    # 素材只到 80 秒，門檻 72 秒，文件的 77 秒已經越過
    document.generate_document(client, "影片", _segments_reaching(0.0, 77.0, 80.0))

    assert client.chat.completions.parse.call_count == 1


def test_an_empty_continuation_keeps_its_reason_but_adds_no_section():
    """尾段真的沒東西可寫時，回空的 steps 是正確答案，不是失敗。

    那個理由要留在 uncovered——它正是使用者該知道的「為什麼文件到這裡就停了」。
    """
    client = MagicMock()
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 100, 10),
        _fake_response(
            document._Continuation(heading="片尾", steps=[], uncovered=["後面只剩片尾字卡"]), 100, 10
        ),
    ]

    result = document.generate_document(client, "影片", _segments_reaching(*_STOPS_EARLY))

    assert len(result.document.sections) == 1
    assert result.document.uncovered[-1] == "後面只剩片尾字卡"


def test_a_failed_continuation_keeps_the_document_it_already_has():
    """補寫是加分項，掛掉不要連累已經產好的文件。

    跟 analyzer 那邊「文件失敗退回摘要」同一個取捨：一份寫到前半段的文件仍然有用，
    為了補不到的尾段把它整份丟掉是更糟的結果。
    """
    client = MagicMock()
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 100, 10),
        RuntimeError("上游 429"),
    ]

    result = document.generate_document(client, "影片", _segments_reaching(*_STOPS_EARLY))

    assert [s.heading for s in result.document.sections] == ["表面貼裝"]
    assert result.cost_usd > 0


def test_doc_type_labels_cover_every_document_type():
    """DOC_TYPE_LABELS 是前端顯示的來源，漏一個就會出現空白標籤。"""
    from typing import get_args

    assert set(DOC_TYPES := get_args(document.DocumentType)) == set(document.DOC_TYPE_LABELS)
    assert "content_log" in DOC_TYPES  # 不適合的影片要有退路
