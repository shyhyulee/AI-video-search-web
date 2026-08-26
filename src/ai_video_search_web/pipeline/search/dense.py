"""Dense channel：查詢向量（含中英文翻譯）、片段模態分數，以及影片層級篩選。

這裡是唯一會真的呼叫 OpenAI 的地方（翻譯與 embedding）；每個對外的入口都有
「失敗就優雅退回」的安全網，不讓翻譯或影片篩選壞掉時擋住整個搜尋功能。
"""
from __future__ import annotations

import logging

import numpy as np
from openai import OpenAI

from ... import db
from .. import embedding, translation

logger = logging.getLogger(__name__)

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


def _best_score(query_vectors: list[np.ndarray], blob: bytes | None) -> float | None:
    """某個模態的 embedding 對多個查詢語言版本各自算 cosine 相似度，取最高分。"""
    if not blob:
        return None
    content_vector = embedding.decode_embedding(blob)
    return max(embedding.cosine_similarity(qv, content_vector) for qv in query_vectors)


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
    client: OpenAI, query_vectors: list[np.ndarray], videos: list[db.VideoRecord]
) -> tuple[set[int] | None, float]:
    """判斷查詢跟哪些影片相關；回傳 None 代表沒有明顯相關的影片（安全網：
    不篩選，全部影片都搜尋），避免誤判排除掉真正相關的內容。第二個回傳值
    是這次判斷實際花費的 embedding 成本（快取命中的標題／摘要不花錢）。
    """
    if len(videos) <= 1:
        return None, 0.0

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
