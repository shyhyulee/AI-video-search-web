"""frame_qa.py 的停格畫面問答測試：mock OpenAI client／frames.extract_frame，
不呼叫真實 API、不需要真的影片檔案。

跟 test_vlm.py 同一套隔離方式。這裡多測的是**追問的上下文**與**暫存檔有沒有
清掉**——前者是這個功能跟 vlm.describe_segment() 最大的差別，後者踩過一次
（describe_segment 讀完就 unlink，測試裡重複回傳同一個路徑會 FileNotFound）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_video_search_web.pipeline import frame_qa


def _fake_response(content: str | None, prompt_tokens: int = 2880, completion_tokens: int = 20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


@pytest.fixture
def fake_frame(monkeypatch, tmp_path):
    """假的抽幀：回傳一個真的暫存檔，讓「用完要刪」這件事測得到。"""
    made: list[Path] = []

    def _extract_frame(video_path, at_sec):
        frame_path = tmp_path / f"frame_{len(made)}.jpg"
        frame_path.write_bytes(b"fake-jpeg-bytes")
        made.append(frame_path)
        return frame_path

    monkeypatch.setattr(frame_qa.frames, "extract_frame", _extract_frame)
    return made


def _messages(client) -> list[dict]:
    return client.chat.completions.create.call_args.kwargs["messages"]


def test_answer_carries_the_frame_the_question_and_the_timestamp(fake_frame):
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response("畫面中有三個箱子。")

    result = frame_qa.answer_about_frame(
        client, Path("video.mp4"), 252.0, "畫面中有幾個箱子？"
    )

    assert result.answer == "畫面中有三個箱子。"
    blocks = _messages(client)[-1]["content"]
    text = next(b["text"] for b in blocks if b["type"] == "text")
    assert "畫面中有幾個箱子？" in text
    # 時間點同時給秒數與 MM:SS，跟素材那邊同一個理由：只給一種格式時模型會自己換算
    assert "第 252 秒" in text and "04:12" in text
    image = next(b for b in blocks if b["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_detail_stays_low(fake_frame):
    """detail 不是可有可無的預設值。同一張 1280×720 畫面，low 是 2,880 prompt
    tokens（US$0.00045）、high 是 36,882（US$0.00554，12.6 倍），而實測 high 沒
    有換到正確答案——籃球場那張 low 答「四個人」、high 答「五個人」，真值是 10
    以上。改成 high 要先有新的實測數據，見 docs/archive/19 §4.2／§4.3。"""
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response("好的。")

    frame_qa.answer_about_frame(client, Path("video.mp4"), 10.0, "這是什麼？")

    image = next(b for b in _messages(client)[-1]["content"] if b["type"] == "image_url")
    assert image["image_url"]["detail"] == "low"


def test_prompt_does_not_tell_the_model_to_refuse_when_unsure(fake_frame):
    """**這一條是防退步用的。** 第一版探針照抄文件產生器那套防幻覺句子（「看不
    出來就說看不出來，不要推測」），結果六題全部回「看不出來。」，包括一張一望
    即知的籃球場全景。在「整理文件」裡寧可少寫，在「使用者問了一個問題」裡少寫
    就等於功能壞掉——兩個情境的護欄不能共用。見 docs/archive/19 §4.4。"""
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response("好的。")

    frame_qa.answer_about_frame(client, Path("video.mp4"), 10.0, "這是什麼？")

    text = next(b["text"] for b in _messages(client)[-1]["content"] if b["type"] == "text")
    assert "看不出來就說" not in text
    assert "不要推測" not in text
    # 只保留最低限度的那一句：不要編畫面上沒有的東西
    assert "不要編" in text


def test_history_becomes_alternating_turns_before_the_question(fake_frame):
    """追問要帶上下文，否則「那箱子呢？」沒有意義。"""
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response("有兩個箱子。")

    frame_qa.answer_about_frame(
        client, Path("video.mp4"), 252.0, "那箱子呢？",
        history=[("畫面中有幾個人？", "畫面中有三個人。")],
    )

    messages = _messages(client)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "畫面中有幾個人？"
    assert messages[1]["content"] == "畫面中有三個人。"


def test_history_is_capped_so_the_prompt_cannot_grow_without_bound(fake_frame):
    """畫面本身每次都重送，帶太多輪只是讓 prompt 變長。"""
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response("好的。")
    long_history = [(f"問 {i}", f"答 {i}") for i in range(20)]

    frame_qa.answer_about_frame(
        client, Path("video.mp4"), 10.0, "最後一題", history=long_history
    )

    messages = _messages(client)
    assert len(messages) == frame_qa.MAX_HISTORY_TURNS * 2 + 1
    # 留下的要是最近的幾輪，不是最早的
    assert messages[0]["content"] == f"問 {20 - frame_qa.MAX_HISTORY_TURNS}"


def test_the_extracted_frame_is_deleted_even_though_it_was_read(fake_frame):
    """暫存檔用完就刪，跟 vlm.describe_segment() 同一個約定。"""
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response("好的。")

    frame_qa.answer_about_frame(client, Path("video.mp4"), 10.0, "這是什麼？")

    assert fake_frame and not fake_frame[0].exists()


def test_the_frame_is_deleted_even_when_the_model_call_fails(fake_frame):
    """呼叫掛掉也不能留下暫存檔——每問一題留一張，磁碟會慢慢被吃掉。"""
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("上游 429")

    with pytest.raises(RuntimeError):
        frame_qa.answer_about_frame(client, Path("video.mp4"), 10.0, "這是什麼？")

    assert fake_frame and not fake_frame[0].exists()


def test_empty_answer_raises_instead_of_returning_a_blank(fake_frame):
    """內容審查拒絕或輸出被截斷時 content 會是空的。跟 document.py 一樣沒有
    合理的空答案可退，直接丟錯讓前端顯示失敗。"""
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response("   ")

    with pytest.raises(ValueError, match="沒有回傳可用的答案"):
        frame_qa.answer_about_frame(client, Path("video.mp4"), 10.0, "這是什麼？")


def test_cost_comes_from_usage(fake_frame):
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response(
        "好的。", prompt_tokens=2880, completion_tokens=20,
    )

    result = frame_qa.answer_about_frame(client, Path("video.mp4"), 10.0, "這是什麼？")

    assert result.cost_usd == pytest.approx(
        2880 * frame_qa.PRICE_INPUT_PER_TOKEN_USD + 20 * frame_qa.PRICE_OUTPUT_PER_TOKEN_USD
    )


def test_missing_usage_returns_zero_cost(fake_frame):
    client = MagicMock()
    response = _fake_response("好的。")
    response.usage = None
    client.chat.completions.create.return_value = response

    assert frame_qa.answer_about_frame(client, Path("video.mp4"), 10.0, "x").cost_usd == 0.0
