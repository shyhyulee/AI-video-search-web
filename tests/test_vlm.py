"""vlm.py 的畫面描述與成本計算測試：mock OpenAI client／frames.extract_frame，
不呼叫真實 API、不需要真的影片檔案。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_video_search_web.pipeline import vlm


def _fake_response(description: str, on_screen_text: str | None, prompt_tokens: int, completion_tokens: int):
    parsed = SimpleNamespace(description=description, on_screen_text=on_screen_text)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


@pytest.fixture(autouse=True)
def _fake_frame(monkeypatch, tmp_path):
    # 每次呼叫都寫一個新檔案（不是重複回傳同一個路徑）：describe_segment()
    # 讀完一張畫面就會 unlink，多幀情境下如果每次都回傳同一個路徑，第二次
    # 讀取會因為檔案已經被前一次刪除而噴 FileNotFoundError。
    counter = iter(range(10_000))

    def _extract_frame(video_path, at_sec):
        frame_path = tmp_path / f"frame_{next(counter)}.jpg"
        frame_path.write_bytes(b"fake-jpeg-bytes")
        return frame_path

    monkeypatch.setattr(vlm.frames, "extract_frame", _extract_frame)


def test_describe_segment_computes_cost_from_usage():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        "一個人在講話", "STOP", prompt_tokens=1000, completion_tokens=100,
    )

    result = vlm.describe_segment(client, Path("video.mp4"), 0.0, 2.0)

    assert result.description == "一個人在講話"
    assert result.ocr_text == "STOP"
    expected_cost = 1000 * vlm.PRICE_INPUT_PER_TOKEN_USD + 100 * vlm.PRICE_OUTPUT_PER_TOKEN_USD
    assert result.cost_usd == pytest.approx(expected_cost)


def test_describe_segment_no_on_screen_text_returns_none():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        "空景", None, prompt_tokens=500, completion_tokens=50,
    )

    result = vlm.describe_segment(client, Path("video.mp4"), 0.0, 2.0)

    assert result.ocr_text is None


def test_describe_segment_missing_usage_returns_zero_cost():
    client = MagicMock()
    response = _fake_response("畫面", None, prompt_tokens=0, completion_tokens=0)
    response.usage = None
    client.chat.completions.parse.return_value = response

    result = vlm.describe_segment(client, Path("video.mp4"), 0.0, 2.0)

    assert result.cost_usd == 0.0


def test_describe_segment_default_frame_fractions_is_single_midpoint_frame():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        "畫面", None, prompt_tokens=100, completion_tokens=10,
    )

    result = vlm.describe_segment(client, Path("video.mp4"), 0.0, 2.0)

    assert result.frame_count == 1
    content = client.chat.completions.parse.call_args.kwargs["messages"][0]["content"]
    image_blocks = [block for block in content if block["type"] == "image_url"]
    assert len(image_blocks) == 1


def test_describe_segment_multi_frame_sends_one_image_per_fraction():
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        "兩張畫面內容", "TEXT", prompt_tokens=6000, completion_tokens=100,
    )

    result = vlm.describe_segment(
        client, Path("video.mp4"), 100.0, 110.0, frame_fractions=(0.3, 0.7),
    )

    assert result.frame_count == 2
    content = client.chat.completions.parse.call_args.kwargs["messages"][0]["content"]
    image_blocks = [block for block in content if block["type"] == "image_url"]
    assert len(image_blocks) == 2
    # 多幀 prompt 要提到張數，跟單幀版的措辭不同
    text_block = content[0]["text"]
    assert "2 張畫面" in text_block


def test_describe_segment_multi_frame_extracts_at_correct_timestamps(monkeypatch):
    client = MagicMock()
    client.chat.completions.parse.return_value = _fake_response(
        "畫面", None, prompt_tokens=6000, completion_tokens=100,
    )
    seen_timestamps: list[float] = []
    original = vlm.frames.extract_frame

    def _spy(video_path, at_sec):
        seen_timestamps.append(at_sec)
        return original(video_path, at_sec)

    monkeypatch.setattr(vlm.frames, "extract_frame", _spy)

    vlm.describe_segment(client, Path("video.mp4"), 100.0, 110.0, frame_fractions=(0.3, 0.7))

    assert seen_timestamps == pytest.approx([103.0, 107.0])
