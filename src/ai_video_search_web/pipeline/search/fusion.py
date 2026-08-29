"""RRF 融合與回傳結果的品質門檻：把 dense 排名與 sparse 排名合成一個排序依據，
再濾掉品質不夠的候選。
"""
from __future__ import annotations

from .results import SearchResult
from .sparse import _sparse_scores

# RRF（Reciprocal Rank Fusion）：score = Σ 1/(k + rank)，k=60 是業界常見的
# 保守慣例值，但實測候選片段數多（一兩百個）時會讓「兩個 channel 都中等」
# 贏過「單一 channel 命中得很準」，調小讓 top rank 的優勢更明顯，見
# docs/02-technical-decisions.md#搜尋 的「RRF_K 調參」。
RRF_K = 5

# 回傳結果的品質下限：兩個條件同時成立才回傳，任一項沒過門檻就不算「足夠
# 相關」，不會出現在 SearchResponse.results 裡（不影響 is_confident——那個
# 判斷的是「排序後最頂端的候選是否被 sparse channel 印證」，用的是套用這
# 兩個門檻之前的候選集合，跟這裡的品質篩選是兩件事，見 service.search()
# 內的說明）。沒有嚴謹校準過，是使用者直接指定的門檻值。
MIN_SIMILARITY = 0.4
MIN_FUSION_SCORE = 0.1


def _rrf_scores(
    query: str, scored: list[tuple[int, SearchResult]], video_ids: list[int] | None = None
) -> tuple[dict[int, float], set[int]]:
    """RRF 融合分數，以及有被 sparse channel 找到的 segment id 集合（給
    SearchResponse.is_confident 判斷 top1 是否被兩個 channel 都印證用，見
    套件說明）。dense 排名用 scored 目前的 similarity 順序（涵蓋全部候選
    片段，不是只有 top_k），sparse 排名用 BM25/LIKE 找到的片段——沒被某個
    channel 找到的片段，該 channel 對它的貢獻就是 0，不是懲罰分數。

    video_ids 是搜尋範圍，原封不動往下傳給 _sparse_scores()（理由見那裡）。"""
    dense_order = sorted(scored, key=lambda pair: pair[1].similarity, reverse=True)
    fused: dict[int, float] = {
        seg_id: 1.0 / (RRF_K + rank) for rank, (seg_id, _) in enumerate(dense_order, start=1)
    }

    valid_ids = {seg_id for seg_id, _ in scored}
    sparse = _sparse_scores(query, valid_ids, video_ids)
    sparse_order = sorted(sparse.items(), key=lambda kv: kv[1])
    for rank, (seg_id, _) in enumerate(sparse_order, start=1):
        fused[seg_id] = fused.get(seg_id, 0.0) + 1.0 / (RRF_K + rank)
    return fused, set(sparse.keys())


def _apply_quality_filter(results: list[SearchResult]) -> list[SearchResult]:
    """回傳結果的品質下限：相似度與融合分數都要達標才保留，濾掉排序上還在
    但品質不夠的候選（見 MIN_SIMILARITY／MIN_FUSION_SCORE 旁的說明）。拆成
    獨立函式方便不用真的跑一次完整 search() 就能測門檻判斷本身。
    """
    return [r for r in results if r.similarity >= MIN_SIMILARITY and r.fusion_score >= MIN_FUSION_SCORE]
