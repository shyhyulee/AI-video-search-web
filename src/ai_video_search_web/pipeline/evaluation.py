"""Golden Set 評分：對照 docs/golden-set.csv 量化 search.py 的搜尋品質，
對應 docs/00-overview.md#23-搜尋準確率提升需求 的 Phase 0。

命中判定刻意用「video_id 相同 且 時間區間有重疊（IoU > 0）」，不是精確比對
單一時間區間——golden-set.csv 部分查詢（如 gs-003）同一題有多個正確區間，
用 in-video 但沒有時間重疊也算命中會高估，不過分嚴格。gs-013（hard
negative）在 notes 裡特別註記「建議用是不是排在 video=4 的某個片段」較寬鬆
判定，本模組刻意不對單一題目寫特例：per-query 報告會附上 notes 文字，
交由人工判讀，避免評分邏輯裡藏著看不出來的例外。

Recall@K／MRR／nDCG@K 只計算 is_answerable=TRUE 的題目（沒有正確答案的題目
不適用「有沒有找到正確片段」）；無答案判斷改用 no_answer_f1 另外評分，
涵蓋全部題目。nDCG@K 假設每題概念上只有一個「正確答案」（IDCG 固定為命中
發生在第一名的分數），不是多相關文件的一般化版本，這樣才能對齊 Recall/MRR
「有沒有把答案排到前面」的量測目的。

no_answer_f1 用 search.SearchResponse.is_confident 判斷（top1 是否同時被
sparse channel 印證，見 search.py 頂端說明），取代早期借用
search.MIN_RELEVANCE 當替代門檻的作法——golden set 實測純 dense 相似度
（或 RRF 融合分數、top1/top2 分數差距）在 answerable／no_answer 兩組
之間分不開，只有「兩個 channel 是否都同意」這個訊號分得開。
"""
from __future__ import annotations

import csv
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import db
from . import search as search_module

DEFAULT_GOLDEN_SET_PATH = db.PROJECT_ROOT / "docs" / "golden-set.csv"
DEFAULT_TOP_K = 20


# ----------------------------------------------------------------------
# Golden Set 讀取
# ----------------------------------------------------------------------


@dataclass
class GoldenAnswer:
    video_id: int
    start_sec: float
    end_sec: float


@dataclass
class GoldenQuery:
    id: str
    query: str
    query_type: str
    is_answerable: bool
    answers: list[GoldenAnswer]
    notes: str


def parse_timestamp(text: str) -> float:
    """把 "MM:SS.s" 格式（golden-set.csv 的時間欄位）轉成秒數。"""
    minutes_str, seconds_str = text.strip().split(":")
    return int(minutes_str) * 60 + float(seconds_str)


def load_golden_set(path: Path | str = DEFAULT_GOLDEN_SET_PATH) -> list[GoldenQuery]:
    """讀取 golden-set.csv，依 id 把同一題的多個正確區間（如 gs-003）合併成
    一個 GoldenQuery。保留檔案裡的原始順序。"""
    queries: dict[str, GoldenQuery] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            qid = row["id"]
            if qid not in queries:
                queries[qid] = GoldenQuery(
                    id=qid,
                    query=row["query"],
                    query_type=row["query_type"],
                    is_answerable=row["is_answerable"].strip().upper() == "TRUE",
                    answers=[],
                    notes=row["notes"],
                )
            if row["expected_video_id"].strip():
                queries[qid].answers.append(
                    GoldenAnswer(
                        video_id=int(row["expected_video_id"]),
                        start_sec=parse_timestamp(row["expected_start"]),
                        end_sec=parse_timestamp(row["expected_end"]),
                    )
                )
    return list(queries.values())


# ----------------------------------------------------------------------
# 純邏輯的評分函式（不呼叫 API，可直接單元測試）
# ----------------------------------------------------------------------


def temporal_iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    overlap = min(a_end, b_end) - max(a_start, b_start)
    if overlap <= 0:
        return 0.0
    union = max(a_end, b_end) - min(a_start, b_start)
    return overlap / union if union > 0 else 0.0


def is_hit(result: search_module.SearchResult, answers: list[GoldenAnswer]) -> bool:
    return any(
        result.video_id == answer.video_id
        and temporal_iou(result.start_sec, result.end_sec, answer.start_sec, answer.end_sec) > 0
        for answer in answers
    )


def hit_rank(results: list[search_module.SearchResult], answers: list[GoldenAnswer]) -> int | None:
    """回傳第一個命中結果的名次（1-based），沒有命中回傳 None。"""
    for rank, result in enumerate(results, start=1):
        if is_hit(result, answers):
            return rank
    return None


def recall_at_k(results: list[search_module.SearchResult], answers: list[GoldenAnswer], k: int) -> bool:
    rank = hit_rank(results[:k], answers)
    return rank is not None


def reciprocal_rank(results: list[search_module.SearchResult], answers: list[GoldenAnswer]) -> float:
    rank = hit_rank(results, answers)
    return 0.0 if rank is None else 1.0 / rank


def ndcg_at_k(results: list[search_module.SearchResult], answers: list[GoldenAnswer], k: int) -> float:
    """二元相關性、假設每題只有一個「正確答案」，故 IDCG 固定為命中排在
    第一名的分數（1 / log2(2) = 1）。"""
    rank = hit_rank(results[:k], answers)
    if rank is None:
        return 0.0
    return 1.0 / math.log2(rank + 1)


def best_iou(results: list[search_module.SearchResult], answers: list[GoldenAnswer], k: int) -> float | None:
    """在前 k 名裡，跟任一正確區間重疊最大的 IoU；沒有命中回傳 None。"""
    best: float | None = None
    for result in results[:k]:
        for answer in answers:
            if result.video_id != answer.video_id:
                continue
            iou = temporal_iou(result.start_sec, result.end_sec, answer.start_sec, answer.end_sec)
            if iou > 0 and (best is None or iou > best):
                best = iou
    return best


def predicted_answerable(response: search_module.SearchResponse) -> bool:
    return response.is_confident


def f1_score(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


# ----------------------------------------------------------------------
# 整合評分：呼叫真正的 search()，需要真實 API（見 scripts/run_golden_set_eval.py）
# ----------------------------------------------------------------------


@dataclass
class QueryEvalResult:
    id: str
    query: str
    query_type: str
    is_answerable: bool
    notes: str
    recall_at_1: bool | None
    recall_at_5: bool | None
    reciprocal_rank: float | None
    ndcg_at_5: float | None
    best_iou: float | None
    predicted_answerable: bool
    top1_similarity: float | None
    cost_usd: float


@dataclass
class EvaluationReport:
    golden_set_path: str
    top_k: int
    query_results: list[QueryEvalResult] = field(default_factory=list)
    recall_at_1: float = 0.0
    recall_at_5: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    mean_timestamp_iou: float | None = None
    no_answer_precision: float = 0.0
    no_answer_recall: float = 0.0
    no_answer_f1: float = 0.0
    total_cost_usd: float = 0.0


def evaluate_query(
    query: GoldenQuery,
    response: search_module.SearchResponse,
    top_k: int,
) -> QueryEvalResult:
    results = response.results
    if query.is_answerable:
        r1 = recall_at_k(results, query.answers, 1)
        r5 = recall_at_k(results, query.answers, 5)
        rr = reciprocal_rank(results, query.answers)
        ndcg5 = ndcg_at_k(results, query.answers, 5)
        iou = best_iou(results, query.answers, top_k)
    else:
        r1 = r5 = rr = ndcg5 = iou = None

    return QueryEvalResult(
        id=query.id,
        query=query.query,
        query_type=query.query_type,
        is_answerable=query.is_answerable,
        notes=query.notes,
        recall_at_1=r1,
        recall_at_5=r5,
        reciprocal_rank=rr,
        ndcg_at_5=ndcg5,
        best_iou=iou,
        predicted_answerable=predicted_answerable(response),
        top1_similarity=results[0].similarity if results else None,
        cost_usd=response.cost_usd,
    )


def aggregate(
    query_results: list[QueryEvalResult],
    golden_set_path: str,
    top_k: int,
) -> EvaluationReport:
    answerable = [r for r in query_results if r.is_answerable]

    def mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    ious = [r.best_iou for r in answerable if r.best_iou is not None]

    tp = sum(1 for r in query_results if not r.is_answerable and not r.predicted_answerable)
    fp = sum(1 for r in query_results if r.is_answerable and not r.predicted_answerable)
    fn = sum(1 for r in query_results if not r.is_answerable and r.predicted_answerable)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    return EvaluationReport(
        golden_set_path=golden_set_path,
        top_k=top_k,
        query_results=query_results,
        recall_at_1=mean([1.0 if r.recall_at_1 else 0.0 for r in answerable]),
        recall_at_5=mean([1.0 if r.recall_at_5 else 0.0 for r in answerable]),
        mrr=mean([r.reciprocal_rank for r in answerable]),
        ndcg_at_5=mean([r.ndcg_at_5 for r in answerable]),
        mean_timestamp_iou=mean(ious) if ious else None,
        no_answer_precision=precision,
        no_answer_recall=recall,
        no_answer_f1=f1_score(precision, recall),
        total_cost_usd=sum(r.cost_usd for r in query_results),
    )


def run_evaluation(
    golden_set_path: Path | str = DEFAULT_GOLDEN_SET_PATH,
    top_k: int = DEFAULT_TOP_K,
    on_query_done: Callable[[QueryEvalResult], None] | None = None,
) -> EvaluationReport:
    """實際呼叫 search.search() 跑過整個 Golden Set——需要真實 OpenAI API
    呼叫（翻譯＋embedding），會產生小額費用並寫入 search_log 表，見
    scripts/run_golden_set_eval.py。`on_query_done` 可傳入 callback（例如印
    進度），每題跑完呼叫一次。"""
    queries = load_golden_set(golden_set_path)
    query_results = []
    for query in queries:
        response = search_module.search(query.query, top_k=top_k)
        result = evaluate_query(query, response, top_k)
        query_results.append(result)
        if on_query_done is not None:
            on_query_done(result)
    return aggregate(query_results, str(golden_set_path), top_k)
