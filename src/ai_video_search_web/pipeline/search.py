"""搜尋：dense（embedding cosine 相似度）+ sparse（BM25 關鍵字）hybrid 召回，
用 RRF 融合排名，取代 V0 純 dense 排序。見 docs/hybrid-retrieval-bm25-plan.md
的 spike 過程與決策依據；reranker 還沒做，是後續 Phase 2 的範圍。

排序（RRF 融合分數）跟畫面上顯示的 `similarity` 欄位是分開的兩件事：
`similarity` 保留原本的 dense cosine 分數語意（UI 拿來畫百分比／進度條，
見 docs/AI_Video_Search_搜尋準確率提升規劃.md 的「保留現有 UI 操作」原則），
RRF 只決定 `results` 的排列順序，不覆寫這個欄位。`SearchResult.fusion_score`
額外把 RRF 分數本身也帶出來給 UI 顯示，避免使用者只看得到 `similarity`
卻不知道實際排序依據是什麼、誤以為排序沒對齊畫面上的相似度（見
docs/hybrid-retrieval-bm25-plan.md「UI 透明度」的說明）。

`SearchResponse.is_confident`：判斷 top1 結果是否可信（取代 V0 借用
MIN_RELEVANCE 當無答案門檻的暫時作法）。訊號是「top1 是否同時被 sparse
（BM25/LIKE 關鍵字）channel 印證」——單純 dense 相似度分不開 answerable／
no_answer 兩組（golden set 實測 no_answer 四題 top1 dense 相似度落在
0.41~0.74，跟 answerable 題目重疊），RRF 融合分數與 top1/top2 分數差距
也一樣分不開；只有「兩個 channel 是否都同意」這個布林訊號能把兩組分開
（golden set 實測 no_answer_f1 從 0 提升到 0.667）。已知限制：無法處理
否定句（例如「工廠裡沒有機器人」，BM25 照樣會命中「機器人」字面關鍵字，
這是語意理解問題不是門檻問題）；只在 17 題小樣本驗證過。

查詢會先翻譯成中英文兩個版本各自 embed，每個模態的分數取兩者較高分，
處理內容跟查詢語言不一致的情況（例如英文影片被中文查詢、或反過來）；
翻譯失敗則優雅退回只用原始查詢，不讓翻譯失敗擋住搜尋功能。

全域搜尋（沒有指定 video_id）會先依影片摘要（沒有摘要退回標題）判斷
查詢跟哪些影片相關，只在相關影片的片段內比對，減少不相關影片的雜訊；
判斷不出明顯相關影片時（安全網）不篩選，維持原本全部影片都搜尋的行為，
避免誤判排除掉真正相關的內容。「在此影片內搜尋」（已指定 video_id）
不套用這層篩選。

每次搜尋的實際花費（翻譯＋embedding 呼叫）會記錄進 search_log 表，並
包在回傳的 SearchResponse 裡。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np
from openai import OpenAI

from .. import db
from . import embedding, translation
from .openai_client import get_client

logger = logging.getLogger(__name__)

FUSION_STRATEGY = (
    "RRF 融合（dense cosine 相似度 + BM25 關鍵字；查詢已翻譯成中英文各自比對取最高分）"
)

# RRF（Reciprocal Rank Fusion）：score = Σ 1/(k + rank)，k=60 是業界常見的
# 保守慣例值，但實測候選片段數多（一兩百個）時會讓「兩個 channel 都中等」
# 贏過「單一 channel 命中得很準」，調小讓 top rank 的優勢更明顯，見
# docs/hybrid-retrieval-bm25-plan.md「調小 RRF_K」實驗。
RRF_K = 5

# 中文虛詞表，用來把查詢字串切成候選關鍵字（不是真正斷詞，純規則）；
# 兩輪 spike（見 docs/hybrid-retrieval-bm25-plan.md）驗證過這個粗糙作法
# 「夠用」：唯一的失敗模式剛好都落在 dense 已經排第一的查詢上，融合後
# 不影響整體結果，所以沒有為此再引入 jieba 之類的斷詞依賴。「要」是後來
# 補的：「要真人的畫面」原本會被黏成查不到任何片段的複合詞「要真人」，
# 見 docs/02-technical-decisions.md「否定句查詢的疊加案例」。
_STOPWORDS = set("的了在是這那個有跟和與上中一準備出現連續喊著地正要")
_ENGLISH_RE = re.compile(r"[A-Za-z0-9]+")

# 否定詞清單：偵測到這些詞，後面到下一個標點符號（或字串結尾）之前的內容
# 視為「使用者不想要」的範圍，見 _split_negated_query()。只用
# docs/05-known-limitations-and-open-items.md 待辦事項裡已經列出的四個，
# 不預先擴充；之後有真實案例顯示需要更多否定詞，再照這個模式新增。
_NEGATION_MARKERS = ("不要", "沒有", "不是", "並非")
_CLAUSE_PUNCTUATION = "，。！？、"

# 泛用描述詞：使用者常見的「畫面」「段落」是描述影片單位本身的詞（想找的
# 是內容，不是「這是一個畫面／段落」這件事），不是有鑑別力的內容詞。Sparse
# channel 已經靠 _SHORT_TERM_MAX_MATCH_RATIO 間接濾掉「畫面」（見下方註解
# 實測 77.4% 比例），但那是統計上剛好被濾掉，dense channel（embedding）完全
# 沒有對應機制——整句原文（含這兩個詞）直接拿去 embed，VLM 視覺描述模板常以
# 「畫面中…」開頭，幾乎每個片段的 embedding 都帶有這個詞的語意重量，稀釋掉
# 真正有鑑別力的內容詞。直接在 search() 入口用子字串移除清理，兩個 channel
# 都吃到清理後的查詢字串，不用個別修 sparse／dense 兩套邏輯。只挑字面出現
# 的這兩個詞刪除，不是真正斷詞，跟 _STOPWORDS／_NEGATION_MARKERS 同樣「粗糙
# 但夠用」的取捨——極端情況（詞組剛好包住這兩個字，例如「壁畫面積」）會被
# 誤刪，但這個 app 的查詢型態（人物／動作／物件描述）機率很低，先不處理。
_GENERIC_DESCRIPTIVE_TERMS = ("畫面", "段落")

# <3 字元的關鍵字用 LIKE 找到時給的哨兵分數：FTS5 trigram tokenizer 對
# 這種短詞完全查不到（見 db/segments.py create_table 的說明），這裡直接
# 讓它們排在所有真正 bm25 分數（實測落在 -2~-10 之間）前面，模擬「精確
# 關鍵字命中應該最優先」——沒有嚴謹校準過，只是 spike 驗證過方向正確。
#
# 只在片段還沒有真正 bm25 分數時才套用這個哨兵分數（見 _sparse_scores()）：
# 實測「找出全壘打的畫面」這類查詢會同時拆出一個罕見長詞（「全壘打」，
# 10 個片段命中，真實 bm25）跟一個常見短詞（「畫面」，同一支 app.db 裡
# 527 個片段都命中），如果短詞哨兵分數無條件覆寫，會讓 527 個只是剛好
# 提到「畫面」、跟查詢語意無關的片段並列蓋過真正命中「全壘打」的片段，
# 排序整個跑掉；保留真正 bm25 分數，哨兵分數只補「完全沒被 bm25 找到」
# 的片段，兩者才不會互相蓋過。
_SHORT_TERM_SPARSE_SCORE = -1e6

# 短詞如果比對到「太大比例」的候選片段，代表它不是精確關鍵字、比較像
# 「畫面」這種描述性泛用詞，不是「汽車」「工廠」這種有鑑別力的內容詞；
# 這種短詞套用哨兵分數只會製造大量並列的雜訊、把真正精確的長詞 bm25
# 命中擠到排名後面，直接跳過、不當作 sparse 訊號比較安全。用比例（不是
# 絕對筆數）判斷，這樣不管是全域搜尋或限定單一影片搜尋，候選片段池大小
# 不同時都適用。門檻沒有嚴謹校準過，只用同一支 app.db 的幾個詞驗證過方向
# 正確：汽車 11.6%／工廠 14.4%（有鑑別力，該保留）vs 畫面 77.4%（沒有
# 鑑別力，該跳過），0.2 這個門檻剛好能把兩種情況分開。
_SHORT_TERM_MAX_MATCH_RATIO = 0.2

_MODALITY_NAMES = {"transcript": "字幕", "visual": "畫面", "ocr": "OCR"}
_MODALITY_ORDER = ("transcript", "visual", "ocr")
_CLOSE_THRESHOLD = 0.03

# 影片層級篩選：最高分都低於這個門檻，代表沒有影片明顯相關，不篩選、
# 全部影片都搜尋（安全網）；否則只留下跟最高分差距在 RELEVANCE_MARGIN
# 以內的影片。MIN_RELEVANCE 只是基本下限（避免整批分數都趨近雜訊時還硬篩），
# 真正決定要不要篩選的主力是 RELEVANCE_MARGIN（相對差距）——實測發現用
# Phase F 產生的長摘要（而非短標題）比對時，就算是明確相關的查詢，最高分
# 也可能偏低（例如「Keira Knightley」對長摘要只有 0.22），比短標題時期
# 估的 0.25 還低；相對差距（gap）才是穩定的訊號（同一組測試中，明確相關
# 的查詢 gap 都在 0.18 以上，不相關的查詢 gap 都在 0.05 以下，分得很開）。
# 這組數字只用實測幾組查詢驗證過，不是嚴謹調校的結果，見
# docs/changelog/2026-08-19-ocr-and-search.md「搜尋支援中英文雙語查詢」後續的影片篩選規劃。
MIN_RELEVANCE = 0.10
RELEVANCE_MARGIN = 0.15

# 回傳結果的品質下限：兩個條件同時成立才回傳，任一項沒過門檻就不算「足夠
# 相關」，不會出現在 SearchResponse.results 裡（不影響 is_confident——那個
# 判斷的是「排序後最頂端的候選是否被 sparse channel 印證」，用的是套用這
# 兩個門檻之前的候選集合，跟這裡的品質篩選是兩件事，見 search() 內的說明）。
# 沒有嚴謹校準過，是使用者直接指定的門檻值。
MIN_SIMILARITY = 0.4
MIN_FUSION_SCORE = 0.1


@dataclass
class SearchResult:
    segment_id: int  # 對應 db.SegmentRecord.id，供多輪對話跨輪次穩定引用同一個片段
    video_id: int
    video_title: str
    start_sec: float
    end_sec: float
    similarity: float
    hit_source: str  # 字幕 / 畫面 / 字幕＋畫面
    description: str
    transcript: str | None
    transcript_score: float | None
    visual_score: float | None
    ocr_score: float | None
    fusion_strategy: str
    fusion_score: float = 0.0  # RRF 融合分數，排序依據；search() 算完 fused_scores 後才填入


@dataclass
class SearchResponse:
    results: list[SearchResult]
    cost_usd: float
    is_confident: bool  # top1 是否同時被 sparse channel 印證，見模組說明


def _strip_generic_terms(query: str) -> str:
    """移除查詢字串裡的泛用描述詞（見 _GENERIC_DESCRIPTIVE_TERMS 旁的說明），
    回傳清理後的字串供 dense／sparse 兩個 channel 共用。清理後整句變空字串
    （例如使用者只打「畫面」兩個字）就退回用原始查詢——安全網，跟
    _get_query_vectors() 翻譯失敗、_relevant_video_ids() 判斷失敗時的退回
    邏輯一致，不讓清理把整個查詢清空。
    """
    cleaned = query
    for term in _GENERIC_DESCRIPTIVE_TERMS:
        cleaned = cleaned.replace(term, "")
    cleaned = cleaned.strip()
    return cleaned if cleaned else query


def search(query: str, top_k: int = 20, video_id: int | None = None) -> SearchResponse:
    """全域搜尋所有已分析片段；傳入 video_id 則只在該支影片的片段內搜尋，
    不套用影片層級篩選。search_log 記錄使用者原始輸入 query，實際檢索（dense
    embedding／sparse 關鍵字抽取）改用 _strip_generic_terms() 清理後的字串
    ——清理只影響檢索本身，不影響搜尋紀錄的稽核軌跡。

    回傳結果先套用 MIN_SIMILARITY／MIN_FUSION_SCORE 品質門檻（兩者都要達標）
    再取前 top_k 筆——top_k 只決定回傳筆數上限，不是「一定會有 top_k 筆」，
    品質不夠的候選會先被濾掉。
    """
    client = get_client()
    cleaned_query = _strip_generic_terms(query)
    query_vectors, cost = _get_query_vectors(client, cleaned_query)

    if video_id is not None:
        segments = db.list_segments_for_video(video_id)
    else:
        segments = db.list_all_segments()
        relevant_ids, filter_cost = _relevant_video_ids(query_vectors, db.list_analyzed_videos())
        cost += filter_cost
        if relevant_ids is not None:
            segments = [seg for seg in segments if seg.video_id in relevant_ids]

    if not segments:
        db.insert_search_log(query, cost)
        return SearchResponse(results=[], cost_usd=cost, is_confident=False)

    # 否定句排除（見 _split_negated_query()／_negated_segment_ids()）：命中
    # 否定關鍵字（例如「不要出現機器人」的「機器人」）的片段直接從候選
    # 集合拿掉，不進下面的評分／RRF 融合，也就不可能變成 is_confident
    # 判斷的 top1——沒有否定詞的查詢這裡回傳空集合，行為完全不變。
    excluded_ids = _negated_segment_ids(cleaned_query, {seg.id for seg in segments})
    if excluded_ids:
        segments = [seg for seg in segments if seg.id not in excluded_ids]
        if not segments:
            db.insert_search_log(query, cost)
            return SearchResponse(results=[], cost_usd=cost, is_confident=False)

    video_titles = {v.id: v.title for v in db.list_analyzed_videos()}
    events_by_segment = _ocr_events_by_segment(video_id)

    scored: list[tuple[int, SearchResult]] = []
    for seg in segments:
        transcript_score = _best_score(query_vectors, seg.transcript_embedding)
        visual_score = _best_score(query_vectors, seg.visual_embedding)
        ocr_score = _best_score(query_vectors, seg.ocr_embedding)
        for event in events_by_segment.get(seg.id, []):
            event_score = _best_score(query_vectors, event.embedding)
            ocr_score = event_score if ocr_score is None else max(ocr_score, event_score)

        modality_scores = [s for s in (transcript_score, visual_score, ocr_score) if s is not None]
        if not modality_scores:
            continue
        similarity = max(modality_scores)
        hit_source = _hit_source(transcript_score, visual_score, ocr_score)
        description = seg.visual_description or seg.transcript or seg.ocr_text or ""

        result = SearchResult(
            segment_id=seg.id,
            video_id=seg.video_id,
            video_title=video_titles.get(seg.video_id, "未知影片"),
            start_sec=seg.start_sec,
            end_sec=seg.end_sec,
            similarity=similarity,
            hit_source=hit_source,
            description=description,
            transcript=seg.transcript,
            transcript_score=transcript_score,
            visual_score=visual_score,
            ocr_score=ocr_score,
            fusion_strategy=FUSION_STRATEGY,
        )
        scored.append((seg.id, result))

    fused_scores, sparse_hit_ids = _rrf_scores(cleaned_query, scored)
    for seg_id, result in scored:
        result.fusion_score = fused_scores.get(seg_id, 0.0)
    scored.sort(key=lambda pair: fused_scores.get(pair[0], 0.0), reverse=True)
    results = [result for _, result in scored]
    # is_confident 刻意用套用品質門檻「之前」的 top1 判斷（跟現有 no_answer
    # 偵測邏輯保持一致，不因為這次新加的品質篩選被連帶影響）：這個判斷關心
    # 的是「排序最頂端的候選有沒有被 sparse channel 印證」，跟 results 最終
    # 有沒有東西是兩件事。
    is_confident = bool(results) and scored[0][0] in sparse_hit_ids

    results = _apply_quality_filter(results)

    db.insert_search_log(query, cost)
    return SearchResponse(results=results[:top_k], cost_usd=cost, is_confident=is_confident)


def _apply_quality_filter(results: list[SearchResult]) -> list[SearchResult]:
    """回傳結果的品質下限：相似度與融合分數都要達標才保留，濾掉排序上還在
    但品質不夠的候選（見 MIN_SIMILARITY／MIN_FUSION_SCORE 旁的說明）。拆成
    獨立函式方便不用真的跑一次完整 search() 就能測門檻判斷本身。
    """
    return [r for r in results if r.similarity >= MIN_SIMILARITY and r.fusion_score >= MIN_FUSION_SCORE]


def _extract_terms(query: str) -> list[str]:
    """把查詢字串拆成候選關鍵字：英文／數字直接當一個詞；中文用虛詞表切開，
    剩下的連續中文片段整段當一個候選詞（不是真正斷詞，見 RRF_K 旁的說明）。
    長度 <2 的片段丟棄，太短沒有鑑別力。"""
    english = [w for w in _ENGLISH_RE.findall(query) if len(w) >= 2]
    remainder = _ENGLISH_RE.sub(" ", query)
    chunks: list[str] = []
    current = ""
    for ch in remainder:
        if ch in _STOPWORDS or ch.isspace() or ch in "，。！？、":
            if len(current) >= 2:
                chunks.append(current)
            current = ""
        else:
            current += ch
    if len(current) >= 2:
        chunks.append(current)
    return list(dict.fromkeys(english + chunks))  # 去重，保留順序


def _sparse_scores(query: str, valid_ids: set[int]) -> dict[int, float]:
    """BM25 關鍵字檢索分數，只回傳 valid_ids 範圍內、真的被找到的片段；
    數字越小（越負）代表越相關。>=3 字元的詞用 FTS5 bm25()（真正的 IDF
    加權），<3 字元的詞用 LIKE fallback（trigram tokenizer 查不到，見
    db/segments.py create_table 的說明）。長詞的真實 bm25 分數優先：短詞
    哨兵分數只補「這個片段完全沒被任何長詞 bm25 找到」的情況，不會覆寫
    已經算出來的真實 bm25 分數；比對到過大比例候選片段的短詞（沒有鑑別
    力，見 _SHORT_TERM_MAX_MATCH_RATIO）整個跳過，不當作 sparse 訊號。"""
    terms = _extract_terms(query)
    long_terms = [t for t in terms if len(t) >= 3]
    short_terms = [t for t in terms if len(t) < 3]

    scores: dict[int, float] = {}
    if long_terms:
        for seg_id, bm25_score in db.fts_bm25_search(long_terms):
            if seg_id in valid_ids:
                scores[seg_id] = bm25_score

    max_matches = len(valid_ids) * _SHORT_TERM_MAX_MATCH_RATIO
    for term in short_terms:
        matched_ids = [seg_id for seg_id in db.fts_like_search(term) if seg_id in valid_ids]
        if valid_ids and len(matched_ids) > max_matches:
            continue  # 太常見，不是精確關鍵字，跳過這個短詞
        for seg_id in matched_ids:
            scores.setdefault(seg_id, _SHORT_TERM_SPARSE_SCORE)
    return scores


def _split_negated_query(query: str) -> tuple[str, str]:
    """把查詢依 _NEGATION_MARKERS 切成 (positive_text, negative_text)。否定詞
    出現後、到下一個標點符號（_CLAUSE_PUNCTUATION）或字串結尾之前的內容算
    否定範圍；可能有多段否定，全部否定範圍合併成一段 negative_text（用空白
    分隔）。positive_text 是把否定範圍（含否定詞本身）挖空成空白後剩下的
    文字。沒有偵測到否定詞時回傳 (query, "")。

    刻意用標點當否定範圍邊界，不用 _STOPWORDS 當邊界——虛詞是結構助詞
    （的／在...），會把否定範圍切太短，見 _STOPWORDS 旁「要真人」案例的
    教訓。
    """
    negative_contents: list[str] = []
    blanked = list(query)
    idx = 0
    while idx < len(query):
        marker = next((m for m in _NEGATION_MARKERS if query.startswith(m, idx)), None)
        if marker is None:
            idx += 1
            continue
        content_start = idx + len(marker)
        content_end = content_start
        while content_end < len(query) and query[content_end] not in _CLAUSE_PUNCTUATION:
            content_end += 1
        negative_contents.append(query[content_start:content_end])
        for i in range(idx, content_end):
            blanked[i] = " "
        idx = content_end

    if not negative_contents:
        return query, ""
    return "".join(blanked), " ".join(negative_contents)


def _negated_segment_ids(query: str, valid_ids: set[int]) -> set[int]:
    """回傳因為命中否定關鍵字而該被排除的 segment id 集合（見 search() 的
    使用方式）。直接重用 _sparse_scores()——它已經有長詞 bm25／短詞 LIKE＋
    _SHORT_TERM_MAX_MATCH_RATIO 比例門檻防呆，對否定範圍的文字跑一次一樣
    的取詞與比對，避免否定詞剛好是「畫面」這種泛用詞時，誤刪掉大部分候選
    片段。"""
    _, negative_text = _split_negated_query(query)
    if not negative_text.strip():
        return set()
    return set(_sparse_scores(negative_text, valid_ids).keys())


def _rrf_scores(
    query: str, scored: list[tuple[int, SearchResult]]
) -> tuple[dict[int, float], set[int]]:
    """RRF 融合分數，以及有被 sparse channel 找到的 segment id 集合（給
    SearchResponse.is_confident 判斷 top1 是否被兩個 channel 都印證用，見
    模組說明）。dense 排名用 scored 目前的 similarity 順序（涵蓋全部候選
    片段，不是只有 top_k），sparse 排名用 BM25/LIKE 找到的片段——沒被某個
    channel 找到的片段，該 channel 對它的貢獻就是 0，不是懲罰分數。"""
    dense_order = sorted(scored, key=lambda pair: pair[1].similarity, reverse=True)
    fused: dict[int, float] = {
        seg_id: 1.0 / (RRF_K + rank) for rank, (seg_id, _) in enumerate(dense_order, start=1)
    }

    valid_ids = {seg_id for seg_id, _ in scored}
    sparse = _sparse_scores(query, valid_ids)
    sparse_order = sorted(sparse.items(), key=lambda kv: kv[1])
    for rank, (seg_id, _) in enumerate(sparse_order, start=1):
        fused[seg_id] = fused.get(seg_id, 0.0) + 1.0 / (RRF_K + rank)
    return fused, set(sparse.keys())


def _get_query_vectors(client: OpenAI, query: str) -> tuple[list[np.ndarray], float]:
    """回傳查詢對應的一到多個 embedding 向量，以及這次呼叫實際花費：預設把
    查詢翻譯成中英文各自 embed（原始查詢字串也一併保留，確保翻譯品質不佳時
    至少不會比翻譯前更差），翻譯失敗就優雅退回只用原始查詢，不讓翻譯失敗
    擋住整個搜尋功能。
    """
    cost = 0.0
    try:
        translated = translation.translate_query(client, query)
        cost += translated.cost_usd
        variants = {query, translated.chinese, translated.english}
    except Exception:
        logger.warning("查詢翻譯失敗，退回只用原始查詢搜尋", exc_info=True)
        variants = {query}

    vectors = []
    for variant in variants:
        embed_result = embedding.embed_text(client, variant)
        cost += embed_result.cost_usd
        vectors.append(np.asarray(embed_result.vector, dtype=np.float32))
    return vectors, cost


_title_summary_embedding_cache: dict[str, tuple[float, ...]] = {}


def _embed_cached(client: OpenAI, text: str) -> tuple[tuple[float, ...], float]:
    """回傳 (embedding 向量, 這次呼叫實際花費)。同一段文字之前 embed 過就直接
    從記憶體快取回傳、花費是 0；沒快取過才真的呼叫 API 並存進快取。用來快取
    影片標題／摘要——這種文字穩定不常變，不像查詢每次都不同，值得快取。快取
    跟著 app 行程生命週期，不寫回資料庫，重啟後清空重算。
    """
    if text in _title_summary_embedding_cache:
        return _title_summary_embedding_cache[text], 0.0
    result = embedding.embed_text(client, text)
    vector = tuple(result.vector)
    _title_summary_embedding_cache[text] = vector
    return vector, result.cost_usd


def _video_relevance_score(
    client: OpenAI, query_vectors: list[np.ndarray], video: db.VideoRecord
) -> tuple[float, float]:
    """影片跟查詢的相關性分數與這次呼叫花費：摘要優先（Phase F 自動產生，見
    docs/changelog/2026-08-19-ocr-and-search.md「Phase F」），沒有摘要
    （例如舊影片還沒重新分析）才退回標題。
    """
    text = video.summary if video.summary else video.title
    vector, cost = _embed_cached(client, text)
    score = max(embedding.cosine_similarity(qv, np.asarray(vector, dtype=np.float32)) for qv in query_vectors)
    return score, cost


def _relevant_video_ids(
    query_vectors: list[np.ndarray], videos: list[db.VideoRecord]
) -> tuple[set[int] | None, float]:
    """判斷查詢跟哪些影片相關；回傳 None 代表沒有明顯相關的影片（安全網：
    不篩選，全部影片都搜尋），避免誤判排除掉真正相關的內容。第二個回傳值
    是這次判斷實際花費的 embedding 成本（快取命中的標題／摘要不花錢）。
    """
    if len(videos) <= 1:
        return None, 0.0

    client = get_client()
    cost = 0.0
    try:
        scores: dict[int, float] = {}
        for video in videos:
            score, video_cost = _video_relevance_score(client, query_vectors, video)
            scores[video.id] = score
            cost += video_cost
    except Exception:
        logger.warning("影片相關性判斷失敗，退回不篩選、搜尋全部影片", exc_info=True)
        return None, cost

    return _select_relevant_ids(scores), cost


def _select_relevant_ids(scores: dict[int, float]) -> set[int] | None:
    """純邏輯（不呼叫 API）：給定每支影片的相關性分數，判斷哪些算「相關」。
    拆成獨立函式方便測試，不用真的呼叫 embedding API 就能驗證門檻邏輯。
    """
    if not scores:
        return None
    max_score = max(scores.values())
    if max_score < MIN_RELEVANCE:
        return None
    return {vid for vid, score in scores.items() if score >= max_score - RELEVANCE_MARGIN}


def _best_score(query_vectors: list[np.ndarray], blob: bytes | None) -> float | None:
    """某個模態的 embedding 對多個查詢語言版本各自算 cosine 相似度，取最高分。"""
    if not blob:
        return None
    content_vector = embedding.decode_embedding(blob)
    return max(embedding.cosine_similarity(qv, content_vector) for qv in query_vectors)


def _ocr_events_by_segment(video_id: int | None) -> dict[int, list[db.OcrEventRecord]]:
    """把本地 OCR（EasyOCR）事件依 segment_id 分組，供 search() 併入既有 OCR 模態分數——
    互補既有 VLM-OCR（segments.ocr_embedding），不是獨立的檢索通道，
    見 docs/ocr-local-engine-plan.md 設計決策 4。"""
    events = db.list_ocr_events_for_video(video_id) if video_id is not None else db.list_all_ocr_events()
    grouped: dict[int, list[db.OcrEventRecord]] = {}
    for event in events:
        if event.segment_id is not None and event.embedding:
            grouped.setdefault(event.segment_id, []).append(event)
    return grouped


def _hit_source(
    transcript_score: float | None, visual_score: float | None, ocr_score: float | None
) -> str:
    """依規格「字幕｜畫面｜OCR｜字幕＋畫面｜綜合」：只有一個模態命中就顯示該模態；
    兩個模態分數相近（差距 < 0.03）就顯示組合名稱；三個都相近就顯示「綜合」。
    """
    available = {
        "transcript": transcript_score,
        "visual": visual_score,
        "ocr": ocr_score,
    }
    available = {k: v for k, v in available.items() if v is not None}
    if not available:
        return "畫面"  # 理論上不會發生：search() 已過濾掉三個模態都沒有分數的片段

    max_score = max(available.values())
    close = [k for k in _MODALITY_ORDER if k in available and max_score - available[k] < _CLOSE_THRESHOLD]

    if len(close) >= 3:
        return "綜合"
    return "＋".join(_MODALITY_NAMES[k] for k in close)
