"""影片摘要：彙整所有片段的字幕與畫面描述，送 GPT-4o-mini 產生約 100～200 字摘要。

V0 只接 OpenAI，只暴露 provider 無關的介面，之後要加其他供應商在這個模組
內部加實作分支即可。不直接碰 db，片段資料由呼叫端傳入，維持跟 asr/vlm/
embedding 一致的「純函式包 API」設計。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from openai import OpenAI

from . import segment_material
from .openai_client import chat_completion_cost

if TYPE_CHECKING:
    from ..db import SegmentRecord

MODEL_NAME = "gpt-4o-mini"
PRICE_INPUT_PER_TOKEN_USD = 0.15 / 1_000_000
PRICE_OUTPUT_PER_TOKEN_USD = 0.60 / 1_000_000

_MAX_SEGMENTS_IN_PROMPT = 200  # 避免片段數極多時 prompt 過長

_PROMPT_TEMPLATE = (
    "以下是一支影片依時間順序切出的畫面描述與字幕內容。"
    "請用繁體中文寫一段 3～5 句話、約 100～200 個字的摘要，說明這支影片主要在講什麼，"
    "不要逐句覆述時間軸內容、不要加開頭語：\n\n{content}"
)


@dataclass
class SummaryResult:
    summary: str
    cost_usd: float


def generate_summary(client: OpenAI, segments: "list[SegmentRecord]") -> SummaryResult:
    if not segments:
        raise ValueError("這支影片還沒有任何分析片段，無法產生摘要")

    # 截斷留在這裡而不是 segment_material 裡：那是這支自己的 prompt 長度控制，
    # document.py 刻意不做（見那裡的 _MAX_SEGMENTS 說明）。不帶畫面文字。
    content = segment_material.build_material(segments[:_MAX_SEGMENTS_IN_PROMPT])
    prompt = _PROMPT_TEMPLATE.format(content=content)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=600,  # 中文字元常拆成 1~2 個 token，200 字上限要留餘裕避免被截斷
    )
    summary = (response.choices[0].message.content or "").strip()
    cost_usd = chat_completion_cost(response.usage, PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD)
    return SummaryResult(summary=summary, cost_usd=cost_usd)
