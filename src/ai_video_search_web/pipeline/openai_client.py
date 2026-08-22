"""共用的 OpenAI client 建構：載入專案根目錄 .env 的金鑰。"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from ..db import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    return OpenAI()


def chat_completion_cost(usage: Any, price_input_per_token: float, price_output_per_token: float) -> float:
    """依 chat completion 回應的 usage（prompt_tokens／completion_tokens）與呼叫端
    自己的定價常數算費用；usage 是 None（例如例外情況下讀不到）就回傳 0。
    vlm.py／summary.py／translation.py 共用同一個公式，這裡只抽公式，不合併
    各模組自己的定價常數——三者現在剛好都用 gpt-4o-mini，之後若分開演進不用
    被迫綁在一起。
    """
    if usage is None:
        return 0.0
    return usage.prompt_tokens * price_input_per_token + usage.completion_tokens * price_output_per_token
