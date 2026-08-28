"""搜尋的對外入口：把 query／dense／sparse／fusion 幾個模組串起來。

這裡只做編排——決定候選集、逐片段取三個模態分數、排序、套門檻、記帳；
每個步驟的規則與校準依據都在各自的模組裡。
"""
from __future__ import annotations

from ... import db
from ..openai_client import get_client
from . import dense, fusion, query as query_module, sparse
from .results import FUSION_STRATEGY, SearchResponse, SearchResult, _hit_source


def search(query: str, top_k: int = 20, video_id: int | None = None) -> SearchResponse:
    """全域搜尋所有已分析片段；傳入 video_id 則只在該支影片的片段內搜尋，
    不套用影片層級篩選。search_log 記錄使用者原始輸入 query，實際檢索（dense
    embedding／sparse 關鍵字抽取）改用 query._strip_generic_terms() 清理後的
    字串——清理只影響檢索本身，不影響搜尋紀錄的稽核軌跡。

    回傳結果先套用 MIN_SIMILARITY／MIN_FUSION_SCORE 品質門檻（兩者都要達標）
    再取前 top_k 筆——top_k 只決定回傳筆數上限，不是「一定會有 top_k 筆」，
    品質不夠的候選會先被濾掉。
    """
    client = get_client()
    cleaned_query = query_module._strip_generic_terms(query)
    query_vectors, cost = dense._get_query_vectors(client, cleaned_query)

    # 已分析影片清單同時給「影片層級篩選」與「結果的影片標題」用，讀一次就好。
    analyzed_videos = db.list_analyzed_videos()

    if video_id is not None:
        segments = db.list_segments_for_video(video_id)
    else:
        segments = db.list_all_segments()
        relevant_ids, filter_cost = dense._relevant_video_ids(client, query_vectors, analyzed_videos)
        cost += filter_cost
        if relevant_ids is not None:
            segments = [seg for seg in segments if seg.video_id in relevant_ids]

    if not segments:
        db.insert_search_log(query, cost)
        return SearchResponse(results=[], cost_usd=cost, is_confident=False)

    # 否定句排除（見 query._split_negated_query()／sparse._negated_segment_ids()）：
    # 命中否定關鍵字（例如「不要出現機器人」的「機器人」）的片段直接從候選
    # 集合拿掉，不進下面的評分／RRF 融合，也就不可能變成 is_confident
    # 判斷的 top1——沒有否定詞的查詢這裡回傳空集合，行為完全不變。
    excluded_ids = sparse._negated_segment_ids(cleaned_query, {seg.id for seg in segments})
    if excluded_ids:
        segments = [seg for seg in segments if seg.id not in excluded_ids]
        if not segments:
            db.insert_search_log(query, cost)
            return SearchResponse(results=[], cost_usd=cost, is_confident=False)

    video_titles = {v.id: v.title for v in analyzed_videos}
    events_by_segment = _ocr_events_by_segment(video_id)

    scored: list[tuple[int, SearchResult]] = []
    for seg in segments:
        transcript_score = dense._best_score(query_vectors, seg.transcript_embedding)
        visual_score = dense._best_score(query_vectors, seg.visual_embedding)
        ocr_score = dense._best_score(query_vectors, seg.ocr_embedding)
        for event in events_by_segment.get(seg.id, []):
            event_score = dense._best_score(query_vectors, event.embedding)
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

    fused_scores, sparse_hit_ids = fusion._rrf_scores(cleaned_query, scored)
    for seg_id, result in scored:
        result.fusion_score = fused_scores.get(seg_id, 0.0)
    scored.sort(key=lambda pair: fused_scores.get(pair[0], 0.0), reverse=True)
    results = [result for _, result in scored]
    # is_confident 刻意用套用品質門檻「之前」的 top1 判斷（跟現有 no_answer
    # 偵測邏輯保持一致，不因為這次新加的品質篩選被連帶影響）：這個判斷關心
    # 的是「排序最頂端的候選有沒有被 sparse channel 印證」，跟 results 最終
    # 有沒有東西是兩件事。
    is_confident = bool(results) and scored[0][0] in sparse_hit_ids

    results = fusion._apply_quality_filter(results)

    db.insert_search_log(query, cost)
    return SearchResponse(results=results[:top_k], cost_usd=cost, is_confident=is_confident)


def _ocr_events_by_segment(video_id: int | None) -> dict[int, list[db.OcrEventRecord]]:
    """把本地 OCR（EasyOCR）事件依 segment_id 分組，供 search() 併入既有 OCR 模態分數——
    互補既有 VLM-OCR（segments.ocr_embedding），不是獨立的檢索通道，
    見 docs/02-technical-decisions.md#vlm-與-ocr。"""
    events = db.list_ocr_events_for_video(video_id) if video_id is not None else db.list_all_ocr_events()
    grouped: dict[int, list[db.OcrEventRecord]] = {}
    for event in events:
        if event.segment_id is not None and event.embedding:
            grouped.setdefault(event.segment_id, []).append(event)
    return grouped
