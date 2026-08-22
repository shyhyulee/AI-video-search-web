"""evaluation.py 的評分邏輯測試：純計算＋CSV 解析，不呼叫任何 API。
真正跑 search() 對照 golden-set.csv 的完整評分是 integration 測試
（見 tests/test_evaluation_integration.py 或 scripts/run_golden_set_eval.py）。"""
from __future__ import annotations

from ai_video_search_web.pipeline import evaluation as ev
from ai_video_search_web.pipeline.search import SearchResponse, SearchResult


def _result(video_id: int, start: float, end: float, similarity: float = 0.5) -> SearchResult:
    return SearchResult(
        segment_id=0,
        video_id=video_id,
        video_title="測試影片",
        start_sec=start,
        end_sec=end,
        similarity=similarity,
        hit_source="畫面",
        description="",
        transcript=None,
        transcript_score=None,
        visual_score=similarity,
        ocr_score=None,
        fusion_strategy="",
    )


def _response(results: list[SearchResult], is_confident: bool, cost_usd: float = 0.0) -> SearchResponse:
    return SearchResponse(results=results, cost_usd=cost_usd, is_confident=is_confident)


def _answer(video_id: int, start: float, end: float) -> ev.GoldenAnswer:
    return ev.GoldenAnswer(video_id=video_id, start_sec=start, end_sec=end)


# ----------------------------------------------------------------------
# parse_timestamp / load_golden_set
# ----------------------------------------------------------------------


def test_parse_timestamp_minutes_seconds():
    assert ev.parse_timestamp("06:53.3") == 413.3


def test_parse_timestamp_zero():
    assert ev.parse_timestamp("00:00.0") == 0.0


def test_load_golden_set_merges_multi_row_query(tmp_path):
    csv_text = (
        "id,query,query_type,is_answerable,expected_video_id,expected_start,expected_end,confirmed,notes\n"
        "gs-003,先出現豬,temporal,TRUE,2,00:08.2,00:18.0,TRUE,note-a\n"
        "gs-003,先出現豬,temporal,TRUE,2,00:18.0,00:29.1,TRUE,note-a\n"
        "gs-015,太空人,no_answer,FALSE,,,,TRUE,note-b\n"
    )
    path = tmp_path / "golden.csv"
    path.write_text(csv_text, encoding="utf-8")

    queries = ev.load_golden_set(path)

    assert [q.id for q in queries] == ["gs-003", "gs-015"]
    gs003 = queries[0]
    assert gs003.is_answerable is True
    assert len(gs003.answers) == 2
    assert gs003.answers[0] == ev.GoldenAnswer(video_id=2, start_sec=8.2, end_sec=18.0)
    gs015 = queries[1]
    assert gs015.is_answerable is False
    assert gs015.answers == []


# ----------------------------------------------------------------------
# temporal_iou / is_hit
# ----------------------------------------------------------------------


def test_temporal_iou_full_overlap():
    assert ev.temporal_iou(0, 10, 0, 10) == 1.0


def test_temporal_iou_no_overlap():
    assert ev.temporal_iou(0, 10, 10, 20) == 0.0


def test_temporal_iou_partial_overlap():
    # overlap [5,10]=5, union [0,15]=15
    assert ev.temporal_iou(0, 10, 5, 15) == 5 / 15


def test_is_hit_requires_matching_video_and_overlap():
    result = _result(video_id=2, start=18.0, end=29.1)
    assert ev.is_hit(result, [_answer(2, 18.0, 29.1)]) is True
    assert ev.is_hit(result, [_answer(3, 18.0, 29.1)]) is False  # 影片不同
    assert ev.is_hit(result, [_answer(2, 40.0, 50.0)]) is False  # 沒有重疊


# ----------------------------------------------------------------------
# recall_at_k / reciprocal_rank / ndcg_at_k / best_iou
# ----------------------------------------------------------------------


def test_recall_at_k_hit_within_k():
    results = [_result(9, 0, 1), _result(2, 18.0, 29.1)]
    answers = [_answer(2, 18.0, 29.1)]
    assert ev.recall_at_k(results, answers, 1) is False
    assert ev.recall_at_k(results, answers, 2) is True


def test_reciprocal_rank_first_hit_rank_two():
    results = [_result(9, 0, 1), _result(2, 18.0, 29.1)]
    answers = [_answer(2, 18.0, 29.1)]
    assert ev.reciprocal_rank(results, answers) == 0.5


def test_reciprocal_rank_no_hit_is_zero():
    results = [_result(9, 0, 1)]
    answers = [_answer(2, 18.0, 29.1)]
    assert ev.reciprocal_rank(results, answers) == 0.0


def test_ndcg_at_k_hit_at_rank_one_is_one():
    results = [_result(2, 18.0, 29.1)]
    answers = [_answer(2, 18.0, 29.1)]
    assert ev.ndcg_at_k(results, answers, 5) == 1.0


def test_ndcg_at_k_hit_at_rank_two_is_discounted():
    results = [_result(9, 0, 1), _result(2, 18.0, 29.1)]
    answers = [_answer(2, 18.0, 29.1)]
    import math
    assert ev.ndcg_at_k(results, answers, 5) == 1 / math.log2(3)


def test_ndcg_at_k_no_hit_within_k_is_zero():
    results = [_result(9, 0, 1)]
    answers = [_answer(2, 18.0, 29.1)]
    assert ev.ndcg_at_k(results, answers, 5) == 0.0


def test_best_iou_picks_max_across_answers():
    results = [_result(2, 17.0, 28.0)]  # 跟 answer 有部分重疊
    answers = [_answer(2, 18.0, 29.1), _answer(2, 100.0, 110.0)]
    iou = ev.best_iou(results, answers, 5)
    assert iou is not None and iou > 0


def test_best_iou_none_when_no_hit():
    results = [_result(9, 0, 1)]
    answers = [_answer(2, 18.0, 29.1)]
    assert ev.best_iou(results, answers, 5) is None


# ----------------------------------------------------------------------
# predicted_answerable / f1_score
# ----------------------------------------------------------------------


def test_predicted_answerable_when_confident():
    response = _response([_result(2, 0, 1)], is_confident=True)
    assert ev.predicted_answerable(response) is True


def test_predicted_answerable_when_not_confident():
    response = _response([_result(2, 0, 1)], is_confident=False)
    assert ev.predicted_answerable(response) is False


def test_predicted_answerable_empty_results():
    response = _response([], is_confident=False)
    assert ev.predicted_answerable(response) is False


def test_f1_score_perfect():
    assert ev.f1_score(precision=1.0, recall=1.0) == 1.0


def test_f1_score_zero_precision_and_recall():
    assert ev.f1_score(precision=0.0, recall=0.0) == 0.0


# ----------------------------------------------------------------------
# evaluate_query / aggregate
# ----------------------------------------------------------------------


def test_evaluate_query_answerable_query():
    query = ev.GoldenQuery(
        id="gs-x", query="q", query_type="object", is_answerable=True,
        answers=[_answer(2, 18.0, 29.1)], notes="",
    )
    response = _response([_result(2, 18.0, 29.1, similarity=0.4)], is_confident=True)
    r = ev.evaluate_query(query, response, top_k=5)
    assert r.recall_at_1 is True
    assert r.recall_at_5 is True
    assert r.reciprocal_rank == 1.0
    assert r.ndcg_at_5 == 1.0
    assert r.best_iou == 1.0
    assert r.predicted_answerable is True


def test_evaluate_query_no_answer_query_skips_recall_metrics():
    query = ev.GoldenQuery(
        id="gs-y", query="q", query_type="no_answer", is_answerable=False,
        answers=[], notes="",
    )
    response = _response([_result(2, 0, 1, similarity=0.02)], is_confident=False)
    r = ev.evaluate_query(query, response, top_k=5)
    assert r.recall_at_1 is None
    assert r.recall_at_5 is None
    assert r.reciprocal_rank is None
    assert r.ndcg_at_5 is None
    assert r.best_iou is None
    assert r.predicted_answerable is False  # 不可信（沒有 sparse 印證），正確判斷無答案


def test_aggregate_no_answer_f1_counts_correctly():
    answerable_hit = ev.evaluate_query(
        ev.GoldenQuery("gs-1", "q1", "object", True, [_answer(1, 0, 1)], ""),
        _response([_result(1, 0, 1, similarity=0.5)], is_confident=True), 5,
    )
    no_answer_correct = ev.evaluate_query(
        ev.GoldenQuery("gs-2", "q2", "no_answer", False, [], ""),
        _response([_result(1, 0, 1, similarity=0.02)], is_confident=False), 5,
    )
    no_answer_wrong = ev.evaluate_query(
        ev.GoldenQuery("gs-3", "q3", "no_answer", False, [], ""),
        _response([_result(1, 0, 1, similarity=0.5)], is_confident=True), 5,
    )

    report = ev.aggregate(
        [answerable_hit, no_answer_correct, no_answer_wrong], "golden.csv", top_k=5
    )

    assert report.recall_at_1 == 1.0  # 只算 answerable 那一題
    assert report.no_answer_precision == 1.0  # tp=1, fp=0
    assert report.no_answer_recall == 0.5  # tp=1, fn=1
    assert report.no_answer_f1 == ev.f1_score(1.0, 0.5)
