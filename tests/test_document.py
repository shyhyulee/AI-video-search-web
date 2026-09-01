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


def _filled(*, at: float = 300.0, steps: bool = True) -> document._FilledSection:
    return document._FilledSection(
        heading="中段製程",
        steps=(
            [document.DocumentStep(timestamp_sec=at, heading="浸漆", detail="定子浸入油漆槽。")]
            if steps
            else []
        ),
        uncovered=["包裝方式影片沒有交代"],
    )


def _segments_reaching(*seconds: float):
    """一支素材延伸到 seconds[-1] 秒的影片。"""
    return [_segment(start_sec=s, visual_description=f"第 {s:.0f} 秒的畫面") for s in seconds]


# 文件唯一的步驟在 77 秒（見 _document()），素材卻一路到 300 秒——中間那一行沒有
# 任何步驟指到，就是補寫要救的那個洞。
#
# 兩個刻意的設計：素材從 60 秒開始而不是 0，開頭那段才不會構成第二個洞（77 - 60
# 沒超過門檻）；補回來的步驟（`_filled()`）剛好落在 300 秒，把洞裡唯一沒寫過的那
# 行寫掉，迴圈重算時就沒得補了——**補洞是重算式的迴圈**，素材如果還留著沒寫過的
# 行，它會繼續補下去，測試的呼叫次數就不只兩次。
_HAS_A_HOLE = (60.0, 77.0, 300.0)


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
        _fake_response(_filled(), 100, 10),
    ]

    document.generate_document(
        client,
        "影片",
        [_segment(start_sec=12.0, visual_description="開場"), _segment(start_sec=600.0, visual_description="收尾")],
    )

    prompt = client.chat.completions.parse.call_args_list[0].kwargs["messages"][0]["content"]
    assert "共 2 行" in prompt
    assert "從第 12 秒延伸到第 600 秒" in prompt
    assert "最後一個步驟應該落在第 540 秒之後" in prompt  # 600 的九成
    assert "不要跳過超過 60 秒的素材" in prompt


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


def test_a_hole_in_the_middle_gets_filled_and_both_costs_counted():
    """文件跳過的那一段，拿那一段的素材再問一次，把補到的插回時間軸。

    這是第二次撞到「prompt 保證不了」：第四條規則要求寫到片尾，模型就用「寫幾步
    開頭、跳到片尾補兩步」滿足它——v37 用 11 個步驟拿到 97.8% 涵蓋率，中間空了
    514 秒。把「不要跳過超過 60 秒」也寫進規則之後 A/B 各三次，最大空隙
    270/314/226 → 381/302/350 秒，沒有改善。
    """
    client = MagicMock()
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 20000, 3000),
        _fake_response(_filled(), 5000, 500),
    ]

    result = document.generate_document(client, "影片", _segments_reaching(*_HAS_A_HOLE))

    assert client.chat.completions.parse.call_count == 2
    # 補到的步驟併進洞前面那一節（另有測試說明為什麼不自成一節）
    assert [s.timestamp_sec for s in result.document.sections[0].steps] == [77.0, 300.0]
    assert result.document.uncovered == ["迴焊爐的溫度曲線影片沒有交代", "包裝方式影片沒有交代"]
    # 兩次呼叫的費用都要算進去，否則 videos.cost_usd 會少記
    assert result.cost_usd == pytest.approx(
        20000 * document.PRICE_INPUT_PER_TOKEN_USD + 3000 * document.PRICE_OUTPUT_PER_TOKEN_USD
        + 5000 * document.PRICE_INPUT_PER_TOKEN_USD + 500 * document.PRICE_OUTPUT_PER_TOKEN_USD
    )


def test_filled_steps_join_the_section_the_hole_belongs_to():
    """補到的步驟要併進洞前面那一節，不要自成一節接在後面。

    主稿的章節本來就可能橫跨整支影片（實跑看到過一節的步驟是 02:14、04:03、
    10:15），補寫如果自成新章節接在它後面，時間軸就變成 615 秒跳回 140 秒。
    """
    client = MagicMock()
    two_sections = _document().model_copy(update={"sections": [
        document.DocumentSection(heading="開頭", steps=[
            document.DocumentStep(timestamp_sec=77.0, heading="開場", detail="工廠外觀。")]),
        document.DocumentSection(heading="結尾", steps=[
            document.DocumentStep(timestamp_sec=600.0, heading="出貨", detail="成品裝箱。")]),
    ]})
    client.chat.completions.parse.side_effect = [
        _fake_response(two_sections, 100, 10),
        _fake_response(_filled(at=300.0), 100, 10),
    ]

    result = document.generate_document(client, "影片", _segments_reaching(60.0, 77.0, 300.0, 580.0))

    assert [s.heading for s in result.document.sections] == ["開頭", "結尾"]
    assert [s.timestamp_sec for s in result.document.sections[0].steps] == [77.0, 300.0]


def test_a_hole_before_the_first_step_becomes_its_own_section():
    """洞在文件最前面時沒有「前面那一節」可以併，補的是文件根本還沒開始寫的
    一段，自成一節才對。"""
    client = MagicMock()
    starts_late = _document().model_copy(update={"sections": [
        document.DocumentSection(heading="收尾", steps=[
            document.DocumentStep(timestamp_sec=600.0, heading="出貨", detail="成品裝箱。")]),
    ]})
    client.chat.completions.parse.side_effect = [
        _fake_response(starts_late, 100, 10),
        _fake_response(_filled(at=300.0), 100, 10),
    ]

    result = document.generate_document(client, "影片", _segments_reaching(60.0, 300.0, 600.0))

    assert [s.heading for s in result.document.sections] == ["中段製程", "收尾"]


def test_the_fill_only_sees_material_inside_the_hole():
    """補寫只餵那個洞的素材——這是這個設計唯一的防幻覺依據。

    模型手上沒有別的東西，就補不出素材裡沒有的內容；已經有步驟指到的那幾行也要
    排除，否則它會把寫過的再寫一遍。
    """
    client = MagicMock()
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 100, 10),
        _fake_response(_filled(), 100, 10),
    ]

    document.generate_document(client, "影片", _segments_reaching(*_HAS_A_HOLE))

    prompt = client.chat.completions.parse.call_args_list[1].kwargs["messages"][0]["content"]
    assert "第 300 秒的畫面" in prompt  # 素材最後一行也是洞的一部分
    assert "第 60 秒的畫面" not in prompt  # 洞的範圍之外
    assert "第 77 秒的畫面" not in prompt  # 已經有步驟指到
    assert "第 77 秒到第 300 秒這一段沒有被寫進去" in prompt
    assert "不要為了填滿而發明步驟" in prompt


def test_the_token_budget_grows_with_the_size_of_the_hole():
    """預算要跟著洞的大小走，不能給固定值。

    實測一個 96 行的洞會把固定的 4000 撞爆（LengthFinishReasonError），然後靜靜
    退回那份沒補到的文件——v2 因此出現過一次「5 個步驟、涵蓋率 4%」。
    """
    client = MagicMock()
    big = _segments_reaching(60.0, *[float(70 + i * 10) for i in range(90)])
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 100, 10),
        *[_fake_response(_filled(at=float(300 + i * 10)), 100, 10) for i in range(document._MAX_FILL_CALLS)],
    ]

    document.generate_document(client, "影片", big)

    budget = client.chat.completions.parse.call_args_list[1].kwargs["max_completion_tokens"]
    assert budget > 4000


def test_content_log_is_never_filled():
    """時間軸紀錄不補。實測同一套補寫在 SOP 上補了 6 個對得上素材的步驟，在球賽
    精華上補出約 25 個、幾乎一行素材一步，內容是「比賽結束的信號｜最終鳴哨結束
    比賽」這種填充句（棒球沒有鳴哨）。

    差別可以解釋：時間軸紀錄的每一行素材本身就是內容，模型於是全部記成步驟。逼
    一份本來就沒有流程的文件寫到片尾，只會生出看起來完整、實際是湊的東西。
    """
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(_document("content_log"), 100, 10)

    result = document.generate_document(client, "影片", _segments_reaching(*_HAS_A_HOLE))

    assert client.chat.completions.parse.call_count == 1
    assert len(result.document.sections) == 1


def test_a_document_without_holes_makes_no_extra_calls():
    """每一行素材都有步驟指到，就不要多花呼叫。"""
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(_document(), 100, 10)

    # 素材只有 77 與 80 兩行，文件的 77 秒指到第一行，兩行相距 3 秒
    document.generate_document(client, "影片", _segments_reaching(77.0, 80.0))

    assert client.chat.completions.parse.call_count == 1


def test_the_number_of_fills_is_capped():
    """補寫次數有上限，每次補當下最大的那個洞。

    上限一度是 3，實測不夠：v33 重跑時主稿的洞比預算多，一個 232 秒的洞排第四、
    根本沒被嘗試，28% 的素材仍然落在空白裡。改成 5 次，而且**每一輪重算**——補一個
    大洞如果只補回兩三步，那個區間裡剩下的空白仍然要算數。"""
    client = MagicMock()
    sparse = _document().model_copy(update={"sections": [
        document.DocumentSection(heading="零星", steps=[
            document.DocumentStep(timestamp_sec=t, heading=f"第 {t} 秒", detail="…")
            for t in (0.0, 200.0, 400.0, 600.0, 800.0)]),
    ]})
    client.chat.completions.parse.side_effect = [
        _fake_response(sparse, 100, 10),
        *[_fake_response(_filled(at=t), 100, 10)
          for t in (100.0, 300.0, 500.0, 700.0, 850.0)],
    ]

    document.generate_document(
        client, "影片", _segments_reaching(*[float(s) for s in range(0, 900, 10)])
    )

    assert client.chat.completions.parse.call_count == 1 + document._MAX_FILL_CALLS


def test_an_empty_fill_keeps_its_reason_but_adds_no_section():
    """那一段真的沒東西可寫時，回空的 steps 是正確答案，不是失敗。

    那個理由要留在 uncovered——它正是使用者該知道的「為什麼這裡沒有步驟」。
    """
    client = MagicMock()
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 100, 10),
        _fake_response(
            document._FilledSection(heading="片尾", steps=[], uncovered=["這段只剩片尾字卡"]), 100, 10
        ),
    ]

    result = document.generate_document(client, "影片", _segments_reaching(*_HAS_A_HOLE))

    assert len(result.document.sections) == 1
    assert result.document.uncovered[-1] == "這段只剩片尾字卡"


def test_a_failed_fill_keeps_the_document_it_already_has():
    """補寫是加分項，掛掉不要連累已經產好的文件。

    跟 analyzer 那邊「文件失敗退回摘要」同一個取捨：一份有洞的文件仍然有用，
    為了補不到的那一段把它整份丟掉是更糟的結果。
    """
    client = MagicMock()
    client.chat.completions.parse.side_effect = [
        _fake_response(_document(), 100, 10),
        RuntimeError("上游 429"),
    ]

    result = document.generate_document(client, "影片", _segments_reaching(*_HAS_A_HOLE))

    assert [s.heading for s in result.document.sections] == ["表面貼裝"]
    assert result.cost_usd > 0


def test_doc_type_labels_cover_every_document_type():
    """DOC_TYPE_LABELS 是前端顯示的來源，漏一個就會出現空白標籤。"""
    from typing import get_args

    assert set(DOC_TYPES := get_args(document.DocumentType)) == set(document.DOC_TYPE_LABELS)
    assert "content_log" in DOC_TYPES  # 不適合的影片要有退路
