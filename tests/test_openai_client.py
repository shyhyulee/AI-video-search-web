"""openai_client 的成本計算：`chat_completion_cost()` 的公式，以及 `chat_prices()`
這張以模型為 key 的單價表。純算術、不呼叫任何 API。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_video_search_web.pipeline import document, frame_qa, intent, summary, translation, vlm
from ai_video_search_web.pipeline.openai_client import chat_completion_cost, chat_prices


def test_chat_completion_cost_computes_from_usage():
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100)
    assert chat_completion_cost(usage, price_input_per_token=0.15 / 1_000_000, price_output_per_token=0.60 / 1_000_000) == pytest.approx(
        1000 * 0.15 / 1_000_000 + 100 * 0.60 / 1_000_000
    )


def test_chat_completion_cost_none_usage_returns_zero():
    assert chat_completion_cost(None, price_input_per_token=0.15 / 1_000_000, price_output_per_token=0.60 / 1_000_000) == 0.0


def test_chat_prices_pins_the_published_rate():
    """單價寫死在測試裡，不從被測程式讀。

    其餘成本測試都是 `2000 * summary.PRICE_INPUT_PER_TOKEN_USD` 這種寫法——期望
    值跟被測值讀同一個常數，所以**價格本身怎麼改都不會轉紅**（實測把輸入與輸出
    單價對調，463 支照樣全綠）。這一支是唯一釘住真實數字的地方：gpt-4o-mini 的
    公告價是輸入 US$0.15／百萬 token、輸出 US$0.60／百萬 token，輸出比輸入貴。
    """
    price_in, price_out = chat_prices("gpt-4o-mini")
    assert price_in == 0.15 / 1_000_000
    assert price_out == 0.60 / 1_000_000
    assert price_out > price_in


def test_chat_prices_unknown_model_raises():
    """查不到一定要炸，不能回 0。

    回 0 等於那條路徑「免費」，而 `analyzer.BUDGET_USD` 的預算護欄唯一的依據就是
    累加起來的花費——算成 0 等於護欄整個失效，而且不會有任何跡象。
    """
    with pytest.raises(ValueError, match="沒有 gpt-4o-mini-2099 的定價"):
        chat_prices("gpt-4o-mini-2099")


@pytest.mark.parametrize(
    "module", [vlm, intent, translation, summary, document, frame_qa], ids=lambda m: m.__name__.rsplit(".", 1)[-1]
)
def test_module_prices_follow_its_model(module):
    """六個模組的 `PRICE_*` 必須是自己 `MODEL_NAME` 查出來的那一組。

    這條在意的是**接線**：改用別的模型時價格要自己跟著換。原本六個模組各自寫死
    一份單價，改模型卻忘了改價不會有任何東西提醒。
    """
    assert (module.PRICE_INPUT_PER_TOKEN_USD, module.PRICE_OUTPUT_PER_TOKEN_USD) == chat_prices(
        module.MODEL_NAME
    )
