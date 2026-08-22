"""VLM：畫面描述。V0 只接 OpenAI GPT-4o-mini，對外只暴露 provider 無關的介面，
之後要加其他供應商，在這個模組內部加實作分支即可，不用動呼叫端。
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from . import frames
from .openai_client import chat_completion_cost

MODEL_NAME = "gpt-4o-mini"
PRICE_INPUT_PER_TOKEN_USD = 0.15 / 1_000_000
PRICE_OUTPUT_PER_TOKEN_USD = 0.60 / 1_000_000

# 預設只取片段中點一張畫面。場景偵測器完全沒抓到切點、被 scene_detect.py
# 的 _split_long_scenes() 機械式均分出來的場景（source_raw_duration 明顯
# 超過自己的長度），中點單幀常常漏看場景內其實塞了好幾段不同內容（見
# docs/02-technical-decisions.md「VLM 條件式多幀取樣」的 gs-002 案例）；
# pipeline/analyzer.py 的 Phase B 會依 source_raw_duration 決定要不要改傳
# MULTI_FRAME_FRACTIONS 觸發多幀。
DEFAULT_FRAME_FRACTIONS = (0.5,)

_PROMPT = (
    "請分析這張畫面，用繁體中文回答兩件事："
    "1. description：一到兩句話描述畫面內容（人物、物件、動作、場景，越具體越好，不要加開頭語）。"
    "2. on_screen_text：畫面上實際出現的文字逐字列出（字幕、標題、標語、招牌、螢幕顯示文字等），"
    "維持原本語言，不要翻譯；如果畫面上沒有任何文字，這欄位填 null，不要自己編造。"
)

# 多幀版 prompt：{n}/{duration} 由 describe_segment() 依實際幀數／片段長度
# 填入。跟單幀版分開維護，不是共用同一句話中間插值——單幀版沒有「依時間
# 順序」「綜合所有畫面」這些多幀才需要的措辭，硬共用反而會讓單幀情境的
# prompt 多出不必要的文字。
_MULTI_FRAME_PROMPT_TEMPLATE = (
    "以下 {n} 張畫面依時間順序取自同一個約 {duration:.1f} 秒的短片段，"
    "請綜合所有畫面回答兩件事："
    "1. description：一到兩句話描述這段畫面內容（如果不同畫面之間內容有變化，"
    "簡短點出變化，不用逐張分開描述，不要加開頭語）。"
    "2. on_screen_text：畫面上實際出現的文字逐字列出（涵蓋所有畫面出現過的文字，"
    "不要重複列同一段文字），維持原本語言，不要翻譯；如果所有畫面都沒有任何文字，"
    "這欄位填 null，不要自己編造。"
)


class _SceneAnalysis(BaseModel):
    description: str
    on_screen_text: str | None


@dataclass
class DescribeResult:
    description: str
    ocr_text: str | None
    cost_usd: float
    frame_count: int


def describe_segment(
    client: OpenAI,
    video_path: Path,
    start_sec: float,
    end_sec: float,
    frame_fractions: tuple[float, ...] = DEFAULT_FRAME_FRACTIONS,
) -> DescribeResult:
    """取片段內 `frame_fractions`（相對於片段起訖的比例，例如 0.5 是中點）
    指定的時間點各抽一張畫面，同一次 VLM 呼叫取得畫面描述與畫面上的文字
    （OCR）。預設只取中點一張（`DEFAULT_FRAME_FRACTIONS`），呼叫端要觸發
    多幀時傳入例如 `(0.3, 0.7)`。
    """
    duration = end_sec - start_sec
    timestamps = [start_sec + fraction * duration for fraction in frame_fractions]

    image_blocks = []
    for at_sec in timestamps:
        frame_path = frames.extract_frame(video_path, at_sec)
        try:
            image_b64 = base64.b64encode(frame_path.read_bytes()).decode("ascii")
        finally:
            frame_path.unlink(missing_ok=True)
        image_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}", "detail": "low"},
        })

    prompt = _PROMPT if len(frame_fractions) == 1 else _MULTI_FRAME_PROMPT_TEMPLATE.format(
        n=len(frame_fractions), duration=duration,
    )

    response = client.chat.completions.parse(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, *image_blocks]}],
        response_format=_SceneAnalysis,
        max_completion_tokens=300,
    )
    parsed = response.choices[0].message.parsed
    description = (parsed.description if parsed else "").strip()
    ocr_text = parsed.on_screen_text.strip() if parsed and parsed.on_screen_text else None

    cost_usd = chat_completion_cost(response.usage, PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD)
    return DescribeResult(
        description=description, ocr_text=ocr_text, cost_usd=cost_usd, frame_count=len(frame_fractions),
    )
