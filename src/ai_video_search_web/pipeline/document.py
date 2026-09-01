"""影片文件整理：把整支影片的畫面描述／字幕／畫面文字彙整成一份結構化文件
（工廠影片 → 生產流程 SOP、烹飪影片 → 教學步驟、課程 → 課堂筆記）。

V0 只接 OpenAI，只暴露 provider 無關的介面，之後要加其他供應商在這個模組
內部加實作分支即可。不直接碰 db，片段資料由呼叫端傳入，維持跟 asr/vlm/
summary 一致的「純函式包 API」設計。

跟 summary.py 的分工：摘要回答「這支影片在講什麼」（100～200 字純文字）；
這裡回答「照著做的話要做哪幾步」（有章節、有步驟、每步帶時間戳的結構化資料）。
四個實作上的差異都是實測資料逼出來的，見各自的註解：**會用 ocr_text**、
**不做片段數硬截斷**、**用 structured output 而不是純文字**、**文件停在前半段時
會再問一次**（`_extend_to_the_end()`）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from openai import OpenAI
from pydantic import BaseModel

from . import segment_material
from .openai_client import chat_completion_cost

if TYPE_CHECKING:
    from ..db import SegmentRecord

logger = logging.getLogger(__name__)

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

四條必須遵守的規則：

1. **每個步驟都要對得上素材裡的某個時間點**，timestamp_sec **直接填素材方括號裡的秒數**（例如 `[03:18｜198 秒]` 就填 198），不要自己從 MM:SS 換算。素材裡沒有的內容一律不准寫——寧可少寫，不要補完。你判斷得出「這裡應該還有一步但素材沒交代」的，寫進 uncovered，不要寫進 sections。

2. **素材品質不一致，要自己判斷該信哪個**。字幕來自語音辨識，純音樂或無人聲的片段可能生出完全無意義的文字（包括看起來像字幕製作人員名單的外語）。字幕與畫面描述明顯矛盾時**以畫面描述為準**；看不懂的片段直接略過，不要試圖解釋它。

3. **不適合就不要硬掰**。判斷成 content_log 時就老實做時間軸紀錄，不要為了湊出流程而發明步驟。

4. **步驟要橫跨整段素材，中間也不能跳過**。這份素材共 {line_count} 行，從第 {first_sec} 秒延伸到第 {last_sec} 秒，最後一個步驟應該落在第 {tail_sec} 秒之後。

   **相鄰兩個步驟之間，不要跳過超過 {gap_sec} 秒的素材**。被跳過的那幾行如果是不同的作業，就各自寫成步驟；只有在它們確實是**同一個動作的延續**（同一道工序連續好幾段、或畫面幾乎沒變）時才可以合併成一步。寫幾步開頭再跳到片尾補一步，不算橫跨。

   但**這不是要你湊數**：某一段如果真的沒有值得寫成步驟的內容（只剩片尾字卡、黑畫面、重複畫面、或跟前面完全相同的作業），就把這件事寫進 uncovered，**絕對不要發明步驟去填滿**。寧可留白，也不要寫出素材裡沒有的事。

其餘欄位：
- title：這份文件的標題（不用照抄影片標題）。
- overview：用 3～5 句話、約 100～200 個字說明**這支影片**主要在講什麼。這一段會直接當成影片摘要顯示，所以要寫成「影片在講什麼」而不是「這份文件涵蓋什麼」——**不要用「本文件」「這份文件」當開頭**，也不要逐句覆述時間軸內容、不要加開頭語。
- sections：依內容分成幾個階段／章節，每節底下是該階段的步驟。

素材：

{content}"""

# 補寫用的第二次呼叫，見 _fill_gaps()。刻意只餵「沒被寫進文件的那一段素材」而不是
# 整份：模型手上只有真素材，就補不出素材裡沒有的東西。
_FILL_TEMPLATE = """影片《{title}》的文件裡，**第 {start_sec} 秒到第 {end_sec} 秒這一段沒有被寫進去**。

以下是那一段的素材，每行是一個片段：

{window}

請只針對這段素材補寫步驟，並給這一節一個 heading。

- timestamp_sec **直接填素材方括號裡的秒數**（例如 `[03:18｜198 秒]` 就填 198），不要自己換算。
- **只寫這一段的內容**，這段之前與之後的部分文件已經寫過了，不要重寫。
- **這段素材如果沒有值得寫成步驟的內容**（只剩片尾字卡、黑畫面、或跟前面完全相同的作業重複），就回傳空的 steps，把原因寫進 uncovered。**不要為了填滿而發明步驟**——寧可回空，也不要寫出素材裡沒有的事。

文件現有的章節：{headings}"""


# 第四條規則裡「最後一個步驟應該落在第 N 秒之後」的 N，取素材長度的九成。
#
# 挑 0.9 是為了對齊驗收條件（涵蓋率 > 90%），不是調出來的最佳值——更嚴的門檻沒有
# 試過，而門檻越靠近片尾，「為了達標而發明一個尾段步驟」的壓力越大。這條規則的重
# 點是把「寫完前三分之一就停」拉回來，不是把最後一秒也榨出來。
_TAIL_FRACTION = 0.9

# 相鄰兩個步驟之間最多可以跳過的秒數。
#
# **這條是「寫到片尾」不夠用才補的**：只要求最後一步落在門檻之後，模型會用「寫幾步
# 開頭、跳到片尾補兩步」滿足它——實測 v37 用 11 個步驟拿到 97.8% 涵蓋率，中間空了
# 514 秒、62 行素材裡 77% 沒被寫到。涵蓋率這個代理指標被繞過去了，正是 docs/18
# §6.2 說的那件事。
#
# 60 秒是驗收線，不是量出來的最佳值：v37 被跳過的那 6 分鐘有 34 行素材，全是不同
# 的製程（浸漆、車削、切管、鑽孔、轉子組裝），不是重複畫面。場景長度正規化到
# 8～12 秒，所以 60 秒大約是 5～7 行。
_MAX_STEP_GAP_SEC = 60

# 一份文件最多補幾次。這是成本上限，不是「補完為止」——補一次約 US$0.001（只餵那
# 一段素材），所以最壞情況每份文件多 US$0.005。
#
# 一度是 3，實測不夠：v33 重跑時主稿的洞比預算多，一個 232 秒的洞排第四、根本沒被
# 嘗試，結果 28% 的素材仍然落在空白裡。洞很多的影片補完仍可能留白，這是刻意的上限。
_MAX_FILL_CALLS = 5


def _coverage_bounds(material: str) -> dict[str, int]:
    """第四條規則要填的數字：素材的行數與起訖、最後一步的下限、以及空隙上限。"""
    time_range = segment_material.material_time_range(material)
    if time_range is None:
        # 每個片段的三個欄位都是空的（或整欄被判定成幻覺而丟掉）。這種素材本來就
        # 生不出有依據的文件，模型只會整份編造，所以跟 parsed is None 一樣直接丟錯。
        raise ValueError("這支影片的片段沒有任何可用內容，無法整理成文件")
    first_sec, last_sec = time_range
    return {
        "line_count": len(segment_material.material_lines(material)),
        "first_sec": first_sec,
        "last_sec": last_sec,
        "tail_sec": int(last_sec * _TAIL_FRACTION),
        "gap_sec": _MAX_STEP_GAP_SEC,
    }


class DocumentStep(BaseModel):
    # 時間戳是必填的，這是防幻覺的主要手段：講不出「這是影片第幾秒的內容」
    # 的步驟，通常就是模型自己補出來的。
    #
    # 曾經觀察到「講得出時間戳也可能是編造的」（8 支文件裡 3 支寫出超過影片
    # 長度的秒數），一度歸因成模型幻覺。**追下去發現是素材格式的問題**：素材
    # 只給 `[MM:SS]`，這個欄位卻要秒數，模型常常直接抄 SS。改成同時給總秒數
    # 之後（見 segment_material.build_material()）重跑 9 支，超出影片長度的
    # 步驟 4 → 0。前端仍然保留「超出長度就不給點」當安全網，見
    # docs/05-known-limitations-and-open-items.md。
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


class _FilledSection(BaseModel):
    """補寫回來的一節。`steps` 允許是空的——那是「這一段真的沒東西可寫」的正確答案。"""

    heading: str
    steps: list[DocumentStep]
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
    bounds = _coverage_bounds(content)
    prompt = _PROMPT_TEMPLATE.format(title=video_title, content=content, **bounds)

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
    return _fill_gaps(
        client, video_title, DocumentResult(document=parsed, cost_usd=cost_usd), content, bounds
    )


def _step_seconds(doc: VideoDocument) -> list[float]:
    return sorted(s.timestamp_sec for sec in doc.sections for s in sec.steps)


def _unwritten(doc: VideoDocument, lines: dict[int, str]) -> dict[int, str]:
    """素材裡還沒有任何步驟指到的那些行。"""
    written = {int(t) for t in _step_seconds(doc)}
    return {sec: line for sec, line in lines.items() if sec not in written}


def _holes(doc: VideoDocument, lines: dict[int, str]) -> list[tuple[int, int]]:
    """文件沒有寫到的時間區間，兩端補上素材的頭與尾。

    頭尾要算進來：一份從 03:40 才開始寫的文件，前面那三分半也是漏掉的內容；而
    「只寫到一半就停」不過是最後那個洞特別大而已——**尾段不是特例，是同一件事**。
    """
    unwritten = _unwritten(doc, lines)
    if not lines:
        return []
    # 落在素材範圍外的時間戳要排除，否則邊界不再單調遞增、算出來的區間是負的。
    # 那種步驟本來就是壞的（前端也擋著不給點），不該拿來當「已經寫過」的依據。
    first, last = float(min(lines)), float(max(lines))
    stamps = [t for t in _step_seconds(doc) if first <= t <= last]
    if not stamps:
        return []
    edges = [first] + stamps + [last]
    holes = [(int(a), int(b)) for a, b in zip(edges, edges[1:]) if b - a > _MAX_STEP_GAP_SEC]
    # 洞裡沒有沒寫過的素材就沒得補。用閉區間比對而不是開區間：頭尾那兩個洞的邊界
    # 就是素材的第一行與最後一行本身，開區間會把它們排除掉——「只寫到一半就停」
    # 那種情況會因此漏掉素材的最後一行。
    return [(a, b) for a, b in holes if any(a <= sec <= b for sec in unwritten)]


def _fill_gaps(
    client: OpenAI,
    video_title: str,
    result: DocumentResult,
    content: str,
    bounds: dict[str, int],
) -> DocumentResult:
    """文件跳過的每一段，各拿那一段的素材再問一次，把補到的插回時間軸上。

    **為什麼 prompt 規則不夠**：這是第二次撞到同一件事。第四條規則要求「寫到片尾」，
    模型就用「寫幾步開頭、跳到片尾補兩步」滿足它——實測 v37 用 11 個步驟拿到 97.8%
    涵蓋率，中間空了 514 秒、62 行素材裡 77% 沒被寫到。後來把「不要跳過超過 60 秒」
    也寫進規則，A/B 各三次，最大空隙 270/314/226 → 381/302/350 秒，**沒有改善**。
    prompt 改得動分布，保證不了每一次。

    **只餵那個洞的素材**，這是防幻覺的依據：模型手上沒有別的東西，補不出素材裡沒有
    的內容，而且明確允許回空的 steps——那一段真的只剩片尾字卡時，回空才是正確答案。

    **`content_log` 不補**，這是實測逼出來的：同一套機制在 v37（SOP）補了 6 個步驟、
    每一步都對得上素材、`uncovered` 誠實寫下「剩下只有重複字幕與片尾字卡」；但在龍隊
    精華（`content_log`）補出約 25 個步驟，幾乎一行素材一步，內容是「比賽結束的信號
    ｜最終鳴哨結束比賽」這種填充句（棒球根本沒有鳴哨）。時間軸紀錄的每一行素材本身
    就是內容，模型於是全部記成步驟。

    **失敗不影響已經產好的文件**：補寫是加分項，某一次呼叫掛掉就記 warning、留著手上
    這份（跟 analyzer 那邊「文件失敗退回摘要」同一個取捨）。
    """
    if result.document.doc_type == "content_log":
        return result

    lines = segment_material.material_lines(content)
    attempted: set[tuple[int, int]] = set()
    for _ in range(_MAX_FILL_CALLS):
        # **每一輪重算**，不是照主稿的清單跑完。補一個大洞如果只補回兩三步，那個
        # 區間裡剩下的空白仍然是空白——實測 v33 就是這樣：主稿的洞比預算多，一個
        # 232 秒的洞排在第四位，永遠輪不到它。重算之後預算會花在「現在還缺的地方」。
        holes = [hole for hole in _holes(result.document, lines) if hole not in attempted]
        if not holes:
            break
        # 每次補最大的那個：漏掉最多內容的優先。補過的不再重試——模型回空的
        # steps（「這一段真的沒東西可寫」）是正當答案，不該把剩下的預算耗在上面。
        hole = max(holes, key=lambda h: h[1] - h[0])
        attempted.add(hole)
        result = _fill_one(
            client, video_title, result, _unwritten(result.document, lines), *hole
        )
    return result


def _fill_one(
    client: OpenAI,
    video_title: str,
    result: DocumentResult,
    unwritten: dict[int, str],
    start_sec: int,
    end_sec: int,
) -> DocumentResult:
    """補一個洞。補不到就原樣回傳，不讓已經產好的文件跟著沒了。"""
    document = result.document
    window = [line for sec, line in sorted(unwritten.items()) if start_sec <= sec <= end_sec]

    try:
        response = client.chat.completions.parse(
            model=MODEL_NAME,
            messages=[{
                "role": "user",
                "content": _FILL_TEMPLATE.format(
                    title=video_title,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    window="\n".join(window),
                    headings="、".join(s.heading for s in document.sections),
                ),
            }],
            response_format=_FilledSection,
            # 依洞的大小給預算，不要給固定值：實測一個 96 行的洞會把 4000 撞爆
            # （LengthFinishReasonError），然後靜靜退回那份沒補到的文件。
            max_completion_tokens=min(8000, 400 + 80 * len(window)),
        )
        extra = response.choices[0].message.parsed
    except Exception:
        logger.warning("補寫 %s~%s 秒失敗，這一段留白", start_sec, end_sec, exc_info=True)
        return result

    if extra is None:
        logger.warning("補寫 %s~%s 秒沒有回傳可用內容，這一段留白", start_sec, end_sec)
        return result

    cost_usd = result.cost_usd + chat_completion_cost(
        response.usage, PRICE_INPUT_PER_TOKEN_USD, PRICE_OUTPUT_PER_TOKEN_USD
    )
    # steps 是空的就不要塞一個空章節進去——那是「這一段真的沒東西可寫」的正確答案，
    # 而它給的理由要留著（那正是使用者該知道的「為什麼這裡沒有步驟」）。
    sections = document.sections
    if extra.steps:
        sections = _merge_filled(
            sections, DocumentSection(heading=extra.heading, steps=extra.steps), start_sec
        )
    merged = document.model_copy(
        update={"sections": sections, "uncovered": document.uncovered + extra.uncovered}
    )
    return DocumentResult(document=merged, cost_usd=cost_usd)


def _merge_filled(
    sections: list[DocumentSection], filled: DocumentSection, start_sec: int
) -> list[DocumentSection]:
    """把補到的步驟併進「洞前面那一步」所屬的章節，並讓那一節依時間排好。

    **補寫的步驟刻意不自成一節。** 一度是那樣做的，實跑之後讀起來是壞的：主稿的
    章節本來就可能橫跨整支影片（實測一節的步驟是 02:14、04:03、10:15 三個），補寫
    的新章節接在它後面，時間軸就變成 615 秒跳回 140 秒。改成併回去之後，那一節內
    部依時間排序，讀起來才是單調的。

    代價是模型給補寫那一節的 heading 用不到了（除非洞在文件的最前面，那時候補的
    是「文件根本還沒開始寫」的一段，自成一節才對）。**既有章節仍然不重排**：章節
    是依主題分的，時間軸上允許互相重疊（`docs/05` 記過 Intel 那份「自動化生產線
    02:09~15:30」與「測試與品檢 11:45~18:01」），照時間硬排會把作者的分章打散。
    """
    home, latest = None, None
    for i, section in enumerate(sections):
        for step in section.steps:
            if step.timestamp_sec <= start_sec and (latest is None or step.timestamp_sec > latest):
                home, latest = i, step.timestamp_sec
    if home is None:
        return [filled] + sections

    merged = sections[home].model_copy(update={
        "steps": sorted(sections[home].steps + filled.steps, key=lambda s: s.timestamp_sec)
    })
    return sections[:home] + [merged] + sections[home + 1:]
