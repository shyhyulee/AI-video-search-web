"""停格畫面問答：對影片某一個時間點的那一格畫面回答使用者的問題。

跟 vlm.py 的分工：`describe_segment()` 是**分析流程**的一環——它自己決定要看
哪幾個時間點、產出固定 schema（描述＋畫面文字）寫進資料庫。這裡是**使用者當下
問的一句話**——時間點由使用者停在哪決定，輸出是自由文字、不落地。共用的只有
「抽一格畫面、base64 送給模型」這段，走同一個 frames.extract_frame()。

計畫與動手前的實測見 docs/archive/19-停格畫面問答功能計畫.md。三個數字值得記在這裡：

- **抽幀是逐格準確的**。`-ss` 放在 `-i` 之前是快速 seek，實測同一支影片抽
  409.0／409.4／409.8／410.5／412.0／414.0 六個時間點得到六張不同的畫面，沒有
  吸附到關鍵幀——使用者停在哪就問哪一格，這個前提成立。
- **`detail` 用 low**。同一張 1280×720 畫面，low 是 2,880 prompt tokens
  （US$0.00045），high 是 36,882（US$0.00554，12.6 倍）。而且貴的那個沒有換到
  正確答案，見下一條。
- **計數問題不可靠，兩級都是**。一張約 10 名球員＋滿場觀眾的籃球場全景，low 答
  「四個人」、high 答「五個人」。依使用者決定**不做特別處理**（不加數量護欄、
  不加免責文案），列為已知限制。辨識型問題（有什麼／在做什麼／寫了什麼）實測
  在 low 就答得好。
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from . import frames
from .openai_client import chat_completion_cost, chat_prices

MODEL_NAME = "gpt-4o-mini"
# 單價跟著 MODEL_NAME 走，不再各自寫死一份，見 openai_client._CHAT_PRICES_USD_PER_TOKEN。
PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD = chat_prices(MODEL_NAME)

# 追問時最多帶幾輪舊問答。同一格畫面的追問（「那箱子呢？」）需要上下文，但畫面
# 本身每次都會重送，帶太多輪只是讓 prompt 變長而已。
MAX_HISTORY_TURNS = 6

# **這段 prompt 刻意不寫防幻覺的重話。** 第一版探針照抄文件產生器那套（「看不出
# 來就說看不出來，不要推測」），結果六題全部回「看不出來。」——包括一張一望即知
# 的籃球場全景。在「整理文件」裡寧可少寫，在「使用者問了一個問題」裡少寫就等於
# 功能壞掉，兩個情境的護欄不能共用。詳見 docs/19 §4.4。
_PROMPT_TEMPLATE = """這是一支影片在第 {at_sec} 秒（{stamp}）的那一格畫面。

請根據這張畫面回答使用者的問題，用繁體中文，兩三句話以內講完。畫面上看不到的事情不要編。

問題：{question}"""


@dataclass
class FrameAnswer:
    answer: str
    cost_usd: float


def answer_about_frame(
    client: OpenAI,
    video_path: Path,
    at_sec: float,
    question: str,
    history: "list[tuple[str, str]] | None" = None,
) -> FrameAnswer:
    """抽出 `at_sec` 那一格，連同問題送給模型，回傳答案與這次的花費。

    `history` 是**同一格畫面**先前的問答（`(問, 答)` 序對），呼叫端負責在時間點
    改變時清空——帶著別格畫面的問答會讓模型答錯格。畫面本身每次都重送，所以
    history 只放文字。
    """
    frame_path = frames.extract_frame(video_path, at_sec)
    try:
        image_b64 = base64.b64encode(frame_path.read_bytes()).decode("ascii")
    finally:
        # 抽出來的暫存檔用完就刪，跟 vlm.describe_segment() 同一個約定：呼叫端
        # 負責清，不留檔。
        frame_path.unlink(missing_ok=True)

    messages: list[dict] = []
    for asked, answered in (history or [])[-MAX_HISTORY_TURNS:]:
        messages.append({"role": "user", "content": asked})
        messages.append({"role": "assistant", "content": answered})
    messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": _PROMPT_TEMPLATE.format(
                at_sec=int(at_sec), stamp=_format_timestamp(at_sec), question=question,
            )},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{image_b64}", "detail": "low"}},
        ],
    })

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        # 兩三句話的答案，300 個 token 綽綽有餘（實測最長的一次是 48）。給太寬
        # 只會讓模型有機會寫長篇，這裡的價值就是「一句話回答」。
        max_completion_tokens=300,
    )
    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        # 內容審查拒絕或輸出被截斷時 content 會是空的。跟 document.py 一樣沒有
        # 合理的空答案可退，直接丟錯讓呼叫端顯示失敗。
        raise ValueError("模型沒有回傳可用的答案，請再試一次")

    return FrameAnswer(
        answer=answer,
        cost_usd=chat_completion_cost(
            response.usage, PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD
        ),
    )


def _format_timestamp(sec: float) -> str:
    """秒數轉 `MM:SS`。刻意不重用 segment_material.format_timestamp()——那支是
    「素材長什麼樣子」的一部分，改它要連文件與摘要一起想；這裡只是給模型看的
    一個標記。"""
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"
