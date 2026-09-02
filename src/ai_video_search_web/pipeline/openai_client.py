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


#: 每個模型的 chat completion 單價（USD／token），(輸入, 輸出)。
#:
#: **價格是模型的屬性，不是呼叫端的**。原本 vlm／intent／translation／summary／
#: document／frame_qa 各自寫一份 `0.15 / 1_000_000`、`0.60 / 1_000_000`，六份完全
#: 相同——改價要改六個檔案，而漏掉一個**不會有任何東西提醒**，只會讓那條路徑的
#: 成本統計悄悄偏掉（`videos.cost_usd` 與 Header 的累計成本都吃這個數字）。
#:
#: 這不牴觸原本「不合併各模組定價」的理由。當時擔心的是「模組之後可能改用不同
#: 模型，不該被迫綁在一起」——用模型當 key 正好保住那件事：模組仍各自宣告
#: `MODEL_NAME`，改用別的模型時價格自己跟著換，而不是像現在這樣要記得同時改兩
#: 個常數。新模型只要在這裡加一列。
_CHAT_PRICES_USD_PER_TOKEN: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15 / 1_000_000, 0.60 / 1_000_000),
}


def chat_prices(model: str) -> tuple[float, float]:
    """查一個模型的 (輸入, 輸出) 單價。

    查不到就丟例外、不回傳 0：0 會讓那條路徑「免費」，而成本是這個專案的預算
    護欄（`analyzer.BUDGET_USD`）唯一的依據——算成 0 等於護欄失效，比 import
    時就炸掉嚴重得多。
    """
    try:
        return _CHAT_PRICES_USD_PER_TOKEN[model]
    except KeyError:
        known = "、".join(sorted(_CHAT_PRICES_USD_PER_TOKEN))
        raise ValueError(f"沒有 {model} 的定價，請先加進 _CHAT_PRICES_USD_PER_TOKEN（目前有：{known}）") from None


def chat_completion_cost(usage: Any, price_input_per_token: float, price_output_per_token: float) -> float:
    """依 chat completion 回應的 usage（prompt_tokens／completion_tokens）與呼叫端
    的單價算費用；usage 是 None（例如例外情況下讀不到）就回傳 0。

    單價仍由呼叫端傳進來、不在這裡查表：呼叫端手上已經有 `chat_prices()` 算好的
    模組常數，多一次查表只是把同一件事做兩遍，而且會讓這個純函式多一個對表的
    依賴，測試要驗公式就得先準備一個模型名稱。
    """
    if usage is None:
        return 0.0
    return usage.prompt_tokens * price_input_per_token + usage.completion_tokens * price_output_per_token
