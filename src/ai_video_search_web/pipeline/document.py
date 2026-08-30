"""影片文件整理：把整支影片的畫面描述／字幕／畫面文字彙整成一份結構化文件
（工廠影片 → 生產流程 SOP、烹飪影片 → 教學步驟、課程 → 課堂筆記）。

V0 只接 OpenAI，只暴露 provider 無關的介面，之後要加其他供應商在這個模組
內部加實作分支即可。不直接碰 db，片段資料由呼叫端傳入，維持跟 asr/vlm/
summary 一致的「純函式包 API」設計。

跟 summary.py 的分工：摘要回答「這支影片在講什麼」（100～200 字純文字）；
這裡回答「照著做的話要做哪幾步」（有章節、有步驟、每步帶時間戳的結構化資料）。
三個實作上的差異都是實測資料逼出來的，見各自的註解：**會用 ocr_text**、
**不做片段數硬截斷**、**用 structured output 而不是純文字**。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from openai import OpenAI
from pydantic import BaseModel

from . import segment_material
from .openai_client import chat_completion_cost

if TYPE_CHECKING:
    from ..db import SegmentRecord

MODEL_NAME = "gpt-4o-mini"
PRICE_INPUT_PER_TOKEN_USD = 0.15 / 1_000_000
PRICE_OUTPUT_PER_TOKEN_USD = 0.60 / 1_000_000

# 不是截斷用的，是「這批資料明顯不對勁」的防呆上限。實測片段密度是 5.5～6.2
# 個/分鐘（場景正規化到 8～12 秒），分析的長度上限 1 小時 → 最多約 360 段，
# 所以正常資料永遠碰不到 600。
#
# 刻意**不學 summary.py 的 `segments[:200]` 硬截斷**：摘要截掉尾段只是摘要
# 不完整，SOP 截掉尾段會默默少掉最後幾個製程步驟——使用者拿到一份看起來
# 完整、實際缺了結尾的流程文件，比直接失敗更糟。真的超過就明確丟錯。
_MAX_SEGMENTS = 600

DocumentType = Literal["sop", "tutorial", "lecture_notes", "content_log"]

#: 給前端顯示用的中文標籤，順便當成 DocumentType 的單一事實來源。
DOC_TYPE_LABELS: dict[str, str] = {
    "sop": "流程 SOP",
    "tutorial": "教學步驟",
    "lecture_notes": "課堂筆記",
    "content_log": "內容紀錄",
}

_PROMPT_TEMPLATE = """以下是影片《{title}》依時間順序切出的素材，每行是一個片段，可能包含畫面描述、字幕與畫面上出現的文字。

請把它整理成一份**可以直接交給別人閱讀**的繁體中文文件。

先判斷這支影片屬於哪一類，填進 doc_type：
- sop：內容包含**可依序重現的作業流程**（工廠產線、製程、操作程序）→ 整理成生產流程 SOP
- tutorial：教別人做出某個成品（烹飪、手作、DIY）→ 整理成教學步驟
- lecture_notes：講解知識或概念（課程、教學講解）→ 整理成課堂筆記
- content_log：**最後的退路**，只有在前三類都不成立時才選（球賽、排行榜、風景介紹、剪輯集錦這種本來就沒有流程或知識脈絡的內容）→ 依時間軸整理成內容紀錄

判斷時看**內容**，不要看影片的敘事形式。第一人稱參觀、vlog、開箱、紀錄片這些形式，只要片中交代了一套可重現的步驟或製程，就選 sop 或 tutorial，不要因為它是「參觀紀錄」就選 content_log。反過來，內容真的只是一連串沒有因果順序的畫面時，就老實選 content_log。

三條必須遵守的規則：

1. **每個步驟都要對得上素材裡的某個時間點**，timestamp_sec 填那個片段的秒數。素材裡沒有的內容一律不准寫——寧可少寫，不要補完。你判斷得出「這裡應該還有一步但素材沒交代」的，寫進 uncovered，不要寫進 sections。

2. **素材品質不一致，要自己判斷該信哪個**。字幕來自語音辨識，純音樂或無人聲的片段可能生出完全無意義的文字（包括看起來像字幕製作人員名單的外語）。字幕與畫面描述明顯矛盾時**以畫面描述為準**；看不懂的片段直接略過，不要試圖解釋它。

3. **不適合就不要硬掰**。判斷成 content_log 時就老實做時間軸紀錄，不要為了湊出流程而發明步驟。

其餘欄位：
- title：這份文件的標題（不用照抄影片標題）。
- overview：用 3～5 句話、約 100～200 個字說明**這支影片**主要在講什麼。這一段會直接當成影片摘要顯示，所以要寫成「影片在講什麼」而不是「這份文件涵蓋什麼」——**不要用「本文件」「這份文件」當開頭**，也不要逐句覆述時間軸內容、不要加開頭語。
- sections：依內容分成幾個階段／章節，每節底下是該階段的步驟。

素材：

{content}"""


class DocumentStep(BaseModel):
    # 時間戳是必填的，這是防幻覺的主要手段：講不出「這是影片第幾秒的內容」
    # 的步驟，通常就是模型自己補出來的。
    #
    # 但**反過來不成立**：講得出時間戳也可能是編造的。實測 8 支已整理文件，
    # 3 支有超出影片長度的秒數（18:33 的影片寫出 22:56 的步驟）、2 支步驟時間
    # 戳倒退。這裡刻意**不做夾住或過濾**——處理方式還沒決定，先讓資料照實存下
    # 來，見 docs/05-known-limitations-and-open-items.md。
    timestamp_sec: float
    heading: str
    detail: str


class DocumentSection(BaseModel):
    heading: str
    steps: list[DocumentStep]


class VideoDocument(BaseModel):
    doc_type: DocumentType
    title: str
    #: 一稿兩用：既是文件的概述，也會被 services/video_service.generate_document()
    #: 寫回 videos.summary 當作這支影片的摘要。所以 prompt 要求它寫成「影片在講
    #: 什麼」而不是「這份文件涵蓋什麼」——這段文字接下來會進搜尋的影片層級篩選
    #: （pipeline/search/dense.py）與影片庫的主題分類（lib/videoCategory.ts），
    #: 語氣得跟 summary.py 產生的摘要一致。
    overview: str
    sections: list[DocumentSection]
    #: 素材裡沒交代清楚、讀者需要自己補的事。可以是空的。
    uncovered: list[str]


@dataclass
class DocumentResult:
    document: VideoDocument
    cost_usd: float


def generate_document(
    client: OpenAI, video_title: str, segments: "list[SegmentRecord]"
) -> DocumentResult:
    """把一支影片的全部片段整理成一份結構化文件。

    用 structured output（`client.chat.completions.parse`）而不是讓 LLM 吐
    Markdown：前端沒有任何 Markdown 函式庫，結構化資料可以直接用既有的 React
    元件排版、零新依賴；而且時間戳是獨立欄位，「點時間戳跳到影片」（前端的
    VideoDocumentView／VideoDetailPanel）因此不用回頭解析文字。
    """
    if not segments:
        raise ValueError("這支影片還沒有任何分析片段，無法整理成文件")
    if len(segments) > _MAX_SEGMENTS:
        raise ValueError(
            f"片段數 {len(segments)} 超過上限 {_MAX_SEGMENTS}，這批資料不像正常的分析結果"
        )

    # 跟摘要的差別是**這裡會帶畫面文字**：實測 1,076/1,156 個片段有 ocr_text，
    # 而且對流程類影片特別有價值（實際內容包含 `STAGE 3`、`主機板 1990年代`
    # 這種製程階段標示），摘要用不到但 SOP 用得到。素材本身的格式與 summary.py
    # 共用，見 segment_material.py。
    content = segment_material.build_material(segments, include_ocr=True)
    prompt = _PROMPT_TEMPLATE.format(title=video_title, content=content)

    response = client.chat.completions.parse(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        response_format=VideoDocument,
        # 一份 SOP 可能有 20～30 個步驟，比摘要（600）大一個量級。中文字元常
        # 拆成 1~2 個 token，這裡留寬一點，被截斷會讓 parsed 直接變成 None。
        max_completion_tokens=8000,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        # refusal 或輸出被截斷時 parsed 會是 None（跟 vlm.py／translation.py
        # 同一個防禦點）。那兩處可以退回空字串，這裡沒有合理的空文件可退，
        # 直接丟錯讓呼叫端顯示失敗，不要存一份空殼進資料庫。
        raise ValueError("模型沒有回傳可用的文件內容，請再試一次")

    cost_usd = chat_completion_cost(
        response.usage, PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD
    )
    return DocumentResult(document=parsed, cost_usd=cost_usd)
