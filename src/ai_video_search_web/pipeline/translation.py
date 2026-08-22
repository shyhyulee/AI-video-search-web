"""查詢翻譯：把搜尋查詢同時轉換成繁體中文與英文兩個版本，讓 search.py 能
兩個語言各自比對、取較高分——不完全依賴 embedding 模型本身的跨語言對齊
能力（實測 text-embedding-3-small 對同義中英文配對的 cosine 相似度平均
0.65，對不相關語句平均只有 0.11，跨語言比對本身有訊號，但明確翻譯後同
語言比對可以再提升排序品質，見 docs/changelog/2026-08-19-ocr-and-search.md
「搜尋支援中英文雙語查詢」）。

V0 只接 OpenAI，對外只暴露 provider 無關的介面，之後要加其他供應商，在
這個模組內部加實作分支即可，不用動呼叫端。
"""
from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI
from pydantic import BaseModel

from .openai_client import chat_completion_cost

MODEL_NAME = "gpt-4o-mini"
PRICE_INPUT_PER_TOKEN_USD = 0.15 / 1_000_000
PRICE_OUTPUT_PER_TOKEN_USD = 0.60 / 1_000_000

_PROMPT_TEMPLATE = (
    "請把以下搜尋查詢分別轉換成繁體中文版本與英文版本：如果原文已經是繁體"
    "中文，chinese 欄位可以直接填原文；如果原文已經是英文，english 欄位"
    "可以直接填原文；不要額外解釋，只要語意相同的查詢字串。\n\n查詢：{query}"
)


class _QueryTranslation(BaseModel):
    chinese: str
    english: str


@dataclass
class TranslateResult:
    chinese: str
    english: str
    cost_usd: float


def translate_query(client: OpenAI, query: str) -> TranslateResult:
    """把查詢轉換成中英文兩個版本。呼叫端要自行處理例外（例如 API 失敗時
    退回只用原始查詢搜尋），這個函式不吞例外。
    """
    response = client.chat.completions.parse(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(query=query)}],
        response_format=_QueryTranslation,
        max_completion_tokens=200,
    )
    parsed = response.choices[0].message.parsed
    cost_usd = chat_completion_cost(response.usage, PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD)

    chinese = (parsed.chinese.strip() if parsed and parsed.chinese else "") or query
    english = (parsed.english.strip() if parsed and parsed.english else "") or query
    return TranslateResult(chinese=chinese, english=english, cost_usd=cost_usd)
