"""search.py 的多語言查詢分數合併邏輯測試。純向量運算，不呼叫任何 API。"""
from __future__ import annotations

import numpy as np
import pytest

from ai_video_search_web import db
from ai_video_search_web.pipeline import embedding
from ai_video_search_web.pipeline.search import dense, fusion, query, results, sparse


def _vec(values: list[float]) -> np.ndarray:
    return np.asarray(values, dtype=np.float32)


def test_best_score_takes_max_across_query_variants():
    blob = embedding.encode_embedding([1.0, 0.0])
    query_vectors = [_vec([0.0, 1.0]), _vec([1.0, 0.0])]  # 一個完全正交，一個完全相同
    assert dense.best_score(query_vectors, blob) == 1.0


def test_best_score_single_query_vector():
    blob = embedding.encode_embedding([1.0, 0.0])
    assert dense.best_score([_vec([1.0, 0.0])], blob) == 1.0


def test_best_score_none_blob_returns_none():
    assert dense.best_score([_vec([1.0, 0.0])], None) is None


def test_best_score_empty_blob_returns_none():
    assert dense.best_score([_vec([1.0, 0.0])], b"") is None


# ----------------------------------------------------------------------
# _select_relevant_ids()：影片層級篩選的純邏輯（不呼叫 API）
# ----------------------------------------------------------------------


def test_select_relevant_ids_clear_winner_excludes_others():
    scores = {1: 0.42, 2: 0.14}  # 差距 0.28，超過 RELEVANCE_MARGIN(0.15)
    assert dense._select_relevant_ids(scores) == {1}


def test_select_relevant_ids_close_scores_keeps_both_safety_net():
    scores = {1: 0.26, 2: 0.12}  # 差距 0.14，小於 RELEVANCE_MARGIN(0.15)
    assert dense._select_relevant_ids(scores) == {1, 2}


def test_select_relevant_ids_all_low_scores_returns_none_safety_net():
    # 最高分沒過 MIN_RELEVANCE，代表整批分數都趨近雜訊，不篩選
    scores = {1: dense.MIN_RELEVANCE - 0.02, 2: dense.MIN_RELEVANCE - 0.05}
    assert dense._select_relevant_ids(scores) is None


def test_select_relevant_ids_empty_scores_returns_none():
    assert dense._select_relevant_ids({}) is None


def test_select_relevant_ids_single_video_above_threshold():
    assert dense._select_relevant_ids({1: 0.5}) == {1}


def test_select_relevant_ids_margin_boundary_is_inclusive():
    # 差距剛好等於 RELEVANCE_MARGIN，應該視為「還在範圍內」（>=，不是 >）
    scores = {1: 0.40, 2: 0.40 - dense.RELEVANCE_MARGIN}
    assert dense._select_relevant_ids(scores) == {1, 2}


# ----------------------------------------------------------------------
# strip_generic_terms()：移除「畫面」「段落」等泛用描述詞，純字串處理，
# 不呼叫 API（見 _GENERIC_DESCRIPTIVE_TERMS 旁的說明）
# ----------------------------------------------------------------------


def test_strip_generic_terms_removes_hua_mian():
    assert query.strip_generic_terms("找出全壘打的畫面") == "找出全壘打的"


def test_strip_generic_terms_removes_duan_luo():
    assert query.strip_generic_terms("介紹工廠的段落") == "介紹工廠的"


def test_strip_generic_terms_removes_multiple_occurrences():
    assert query.strip_generic_terms("畫面裡有畫面") == "裡有"


def test_strip_generic_terms_removes_pian_duan():
    """「片段」跟「畫面」「段落」同一類：使用者講的是影片的單位，不是要找的內容。
    漏掉它的實測代價見 docs/02-technical-decisions.md 的「排序被『誰先被資料庫回傳』決定」——「找出工廠中人員作業的片段」會讓「片段」
    當關鍵字，LIKE 命中 12 個不相干片段還拿到短詞哨兵分數。"""
    assert query.strip_generic_terms("找出工廠中人員作業的片段") == "找出工廠中人員作業的"


def test_strip_generic_terms_no_generic_terms_returns_unchanged():
    assert query.strip_generic_terms("大象跟小象在草地上走路") == "大象跟小象在草地上走路"


def test_strip_generic_terms_falls_back_to_original_when_result_empty():
    # 使用者只打「畫面」兩個字：清理後會變空字串，退回用原始查詢，不讓
    # embedding／關鍵字抽取拿到空字串。
    assert query.strip_generic_terms("畫面") == "畫面"
    assert query.strip_generic_terms("  段落  ") == "  段落  "


def test_strip_generic_terms_does_not_affect_unrelated_words():
    # 「動畫」只包含「畫」這個字，不是「畫面」這個子字串，不該被誤傷
    assert query.strip_generic_terms("看動畫影片") == "看動畫影片"


# ----------------------------------------------------------------------
# extract_terms()：規則式拆詞（見 docs/02-technical-decisions.md#搜尋
# 的「斷詞方式」），純字串處理，不呼叫 API
# ----------------------------------------------------------------------


def test_extract_terms_splits_english_and_chinese():
    assert query.extract_terms("Kate Beckinsale") == ["Kate", "Beckinsale"]


def test_extract_terms_splits_chinese_on_stopwords():
    # 「的」是虛詞，把「很兇猛的野生動物」切成「很兇猛」「野生動物」
    assert query.extract_terms("很兇猛的野生動物") == ["很兇猛", "野生動物"]


def test_extract_terms_keeps_two_char_word():
    assert query.extract_terms("汽車") == ["汽車"]


def test_extract_terms_does_not_merge_yao_into_following_word():
    # 「要」是虛詞，「要真人的畫面」不該把「要」黏進「真人」變成查不到
    # 任何片段的複合詞「要真人」（見 docs/02-technical-decisions.md
    # 「否定句查詢的疊加案例」）
    assert query.extract_terms("要真人的畫面") == ["真人", "畫面"]


def test_extract_terms_drops_single_char_chunks():
    # 「在」是虛詞，切開後剩下「家」長度<2，直接丟棄，不會產生沒有鑑別力的候選詞
    assert query.extract_terms("在家") == []


def test_extract_terms_mixed_english_and_chinese_kept_separate():
    terms = query.extract_terms("FRAME 這個字出現在畫面上")
    assert "FRAME" in terms
    assert "畫面" in terms


def test_extract_terms_dedups_preserving_order():
    terms = query.extract_terms("大象跟大象")
    assert terms.count("大象") == 1


# ----------------------------------------------------------------------
# rrf_scores()：dense 排名 + sparse（BM25/LIKE，經 monkeypatch 隔離掉真正的
# DB／FTS 查詢）融合，純邏輯測試
# ----------------------------------------------------------------------


def _search_result(similarity: float, fusion_score: float = 0.0) -> results.SearchResult:
    return results.SearchResult(
        segment_id=1, video_id=1, video_title="t", start_sec=0.0, end_sec=1.0,
        similarity=similarity, hit_source="畫面", description="",
        transcript=None, transcript_score=None, visual_score=similarity,
        ocr_score=None, fusion_strategy=results.FUSION_STRATEGY, fusion_score=fusion_score,
    )


# ----------------------------------------------------------------------
# apply_quality_filter()：回傳結果的品質下限（相似度／融合分數都要達標），
# 純邏輯測試
# ----------------------------------------------------------------------


def test_apply_quality_filter_keeps_result_meeting_both_thresholds():
    results = [_search_result(similarity=0.5, fusion_score=0.2)]
    assert fusion.apply_quality_filter(results) == results


def test_apply_quality_filter_drops_low_similarity():
    results = [_search_result(similarity=0.39, fusion_score=0.2)]
    assert fusion.apply_quality_filter(results) == []


def test_apply_quality_filter_drops_low_fusion_score():
    results = [_search_result(similarity=0.5, fusion_score=0.09)]
    assert fusion.apply_quality_filter(results) == []


def test_apply_quality_filter_boundary_values_are_inclusive():
    # 剛好等於門檻應該保留（>=，不是 >）
    results = [_search_result(similarity=fusion.MIN_SIMILARITY, fusion_score=fusion.MIN_FUSION_SCORE)]
    assert fusion.apply_quality_filter(results) == results


def test_apply_quality_filter_preserves_order_of_surviving_results():
    keep_high = _search_result(similarity=0.9, fusion_score=0.3)
    keep_low = _search_result(similarity=0.4, fusion_score=0.1)
    drop = _search_result(similarity=0.2, fusion_score=0.3)
    assert fusion.apply_quality_filter([keep_high, drop, keep_low]) == [keep_high, keep_low]


def test_rrf_scores_pure_dense_when_sparse_finds_nothing(monkeypatch):
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [])

    scored = [(1, _search_result(0.9)), (2, _search_result(0.5))]
    fused, sparse_hit_ids = fusion.rrf_scores("query", scored)

    k = fusion.RRF_K
    assert fused[1] == pytest.approx(1.0 / (k + 1))
    assert fused[2] == pytest.approx(1.0 / (k + 2))
    assert sparse_hit_ids == set()


def test_rrf_scores_sparse_channel_boosts_low_dense_rank(monkeypatch):
    # segment 1 dense 排名最好（第1名）但完全沒被 BM25 找到；segment 2、3
    # dense 排名較後面，但都被 BM25 找到並互相佐證——融合後兩者應該都
    # 反超 segment 1，重現 gs-013／gs-010 那種「dense 錯過、BM25 救回」的情境
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [(3, -5.0), (2, -1.0)])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [])

    scored = [(1, _search_result(0.9)), (2, _search_result(0.7)), (3, _search_result(0.5))]
    fused, sparse_hit_ids = fusion.rrf_scores("query", scored)

    assert fused[2] > fused[1]
    assert fused[3] > fused[1]
    assert sparse_hit_ids == {2, 3}


def test_rrf_scores_tied_sparse_scores_share_one_rank(monkeypatch):
    """短詞哨兵讓多個片段同分時，它們必須拿到**同一個** RRF 貢獻。

    逐一給名次的話，誰排前面由資料庫回傳順序決定——實測 120 個同分片段裡，
    第一名拿 1/(5+1)=0.167、最後一名拿 1/(5+120)=0.008，差 20 倍全憑運氣
    （docs/02-technical-decisions.md 的「排序被『誰先被資料庫回傳』決定」）。三個同分片段的共用名次是 (1+2+3)/3 = 2。

    候選集刻意放到 20 個：3 個命中要低於 `_SHORT_TERM_MAX_MATCH_RATIO`（20%）
    那道泛用詞門檻，否則這個短詞會整個被跳過、根本進不到融合這一步。
    """
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [7, 8, 9])
    scored = [(i, _search_result(1.0 - i * 0.01)) for i in range(1, 21)]

    fused, _ = fusion.rrf_scores("汽車", scored)

    sparse_part = [fused[i] - 1.0 / (fusion.RRF_K + i) for i in (7, 8, 9)]
    assert sparse_part[0] == pytest.approx(sparse_part[1]) == pytest.approx(sparse_part[2])
    assert sparse_part[0] == pytest.approx(1.0 / (fusion.RRF_K + 2))


def test_rrf_scores_selective_term_gets_bigger_bonus_than_generic_one(monkeypatch):
    """共用平均名次讓 bonus 自動依鑑別力縮放：命中 2 個的詞比命中 6 個的詞
    拿到更大的 sparse 貢獻。這正是短詞哨兵原本想表達、但被任意順序毀掉的意圖。"""
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [])
    scored = [(i, _search_result(0.5)) for i in range(1, 41)]

    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [1, 2])
    selective, _ = fusion.rrf_scores("汽車", scored)
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [1, 2, 3, 4, 5, 6])
    generic, _ = fusion.rrf_scores("汽車", scored)

    dense_part = 1.0 / (fusion.RRF_K + 1)
    assert selective[1] - dense_part > generic[1] - dense_part


def test_rrf_scores_ignores_sparse_hits_outside_candidate_set(monkeypatch):
    # fts_bm25_search 回傳的 segment id 不在這次搜尋範圍內（例如已經被
    # video 層級篩選掉），不該汙染融合分數，也不該出現在 sparse_hit_ids
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [(999, -5.0)])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [])

    scored = [(1, _search_result(0.9))]
    fused, sparse_hit_ids = fusion.rrf_scores("query", scored)

    assert 999 not in fused
    assert fused[1] == pytest.approx(1.0 / (fusion.RRF_K + 1))
    assert sparse_hit_ids == set()


# ----------------------------------------------------------------------
# sparse_scores()：長詞真實 bm25 分數優先、短詞哨兵分數不覆寫，且過度
# 常見的短詞整個跳過，純邏輯測試（見 _SHORT_TERM_SPARSE_SCORE／
# _SHORT_TERM_MAX_MATCH_RATIO 旁的說明，重現「找出全壘打的畫面」被常見
# 短詞「畫面」稀釋掉「全壘打」bm25 排名的情境）。valid_ids 統一給 10 個
# 片段的候選池，讓短詞命中比例維持在 _SHORT_TERM_MAX_MATCH_RATIO(0.2)
# 門檻以下，才不會被下面「過度常見」的測試邏輯誤觸發。
# ----------------------------------------------------------------------

_TEN_IDS = set(range(1, 11))


def test_sparse_scores_short_term_does_not_override_real_bm25_score(monkeypatch):
    # segment 1 同時被長詞 bm25 命中（真實分數 -6.0）跟短詞 LIKE 命中；
    # 短詞哨兵分數不該覆寫掉真實 bm25 分數
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [(1, -6.0)])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [1])

    scores = sparse.sparse_scores("全壘打的畫面", _TEN_IDS)

    assert scores[1] == -6.0


def test_sparse_scores_short_term_fills_in_when_no_bm25_hit(monkeypatch):
    # segment 2 只被短詞 LIKE 命中，完全沒有 bm25 分數，應該補上哨兵分數
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [2])

    scores = sparse.sparse_scores("畫面", _TEN_IDS)

    assert scores[2] == sparse._SHORT_TERM_SPARSE_SCORE


def test_sparse_scores_unrelated_bm25_and_like_hits_do_not_affect_each_other(monkeypatch):
    # segment 1 只被長詞 bm25 命中；segment 2 只被短詞 LIKE 命中，各自獨立
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [(1, -6.0)])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [2])

    scores = sparse.sparse_scores("全壘打的畫面", _TEN_IDS)

    assert scores == {1: -6.0, 2: sparse._SHORT_TERM_SPARSE_SCORE}


def test_sparse_scores_splits_long_term_that_matches_nothing(monkeypatch):
    """規則式取詞會把「人員作業」黏成庫裡不存在的四字詞，BM25 命中 0——
    退回用 2 字滑動窗再試，「人員」這個訊號才進得了 sparse channel
    （docs/02-technical-decisions.md 的「排序被『誰先被資料庫回傳』決定」）。"""
    probed: list[list[str]] = []

    def fake_bm25(terms, video_ids=None):
        probed.append(list(terms))
        return []

    monkeypatch.setattr(db, "fts_bm25_search", fake_bm25)
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [5] if term == "人員" else [])

    scores = sparse.sparse_scores("人員作業", {5, 6, 7, 8, 9, 10, 11, 12, 13, 14})

    assert scores == {5: sparse._SHORT_TERM_SPARSE_SCORE}
    assert ["人員作業"] in probed  # 先探測過原詞


def test_sparse_scores_keeps_long_term_that_does_match(monkeypatch):
    """長詞查得到就不拆——拆開只會讓比對變鬆。"""
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [(4, -3.0)])
    monkeypatch.setattr(
        db, "fts_like_search", lambda term, video_ids=None: pytest.fail(f"不該退回 LIKE：{term}")
    )

    assert sparse.sparse_scores("機器人", {4}) == {4: -3.0}


def test_sparse_scores_skips_short_term_matching_too_large_a_fraction(monkeypatch):
    # 短詞比對到候選池 100%（遠超過 _SHORT_TERM_MAX_MATCH_RATIO=0.2），
    # 視為沒有鑑別力的泛用詞（例如「畫面」），整個跳過、不當 sparse 訊號
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: list(_TEN_IDS))

    scores = sparse.sparse_scores("畫面", _TEN_IDS)

    assert scores == {}


def test_sparse_scores_keeps_short_term_just_under_ratio_threshold(monkeypatch):
    # 命中比例剛好等於門檻（不是超過）仍視為有鑑別力，正常套用哨兵分數
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [1, 2])  # 2/10 = 0.2，等於門檻

    scores = sparse.sparse_scores("畫面", _TEN_IDS)

    assert scores == {1: sparse._SHORT_TERM_SPARSE_SCORE, 2: sparse._SHORT_TERM_SPARSE_SCORE}


# ----------------------------------------------------------------------
# split_negated_query()：把否定詞後面到下一個標點符號之前的內容切成
# negative_text，純字串處理，不呼叫 API
# ----------------------------------------------------------------------


def test_split_negated_query_no_marker_returns_original_and_empty():
    assert query.split_negated_query("獅子") == ("獅子", "")


def test_split_negated_query_single_marker_at_start():
    positive, negative = query.split_negated_query("不要機器人")
    assert negative == "機器人"
    assert query.extract_terms(positive) == []


def test_split_negated_query_marker_in_middle_keeps_earlier_text_positive():
    positive, negative = query.split_negated_query("要真人的畫面 不要出現機器人的畫面")
    assert query.extract_terms(positive) == ["真人", "畫面"]
    assert query.extract_terms(negative) == ["機器人", "畫面"]


def test_split_negated_query_stops_at_punctuation():
    positive, negative = query.split_negated_query("不要機器人。工廠裡都是真人")
    assert query.extract_terms(negative) == ["機器人"]
    assert "真人" in query.extract_terms(positive)


def test_split_negated_query_multiple_markers_merge_into_one_negative_text():
    _, negative = query.split_negated_query("不要機器人，也不要無人機")
    assert query.extract_terms(negative) == ["機器人", "無人機"]


# ----------------------------------------------------------------------
# negated_segment_ids()：重用 sparse_scores() 的長短詞分流＋比例門檻，
# monkeypatch db 呼叫，純邏輯測試
# ----------------------------------------------------------------------


def test_negated_segment_ids_no_marker_returns_empty_set():
    assert sparse.negated_segment_ids("獅子", _TEN_IDS) == set()


def test_negated_segment_ids_excludes_matched_segments(monkeypatch):
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [(3, -6.0)])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: [])

    excluded = sparse.negated_segment_ids("不要機器人", _TEN_IDS)

    assert excluded == {3}


def test_negated_segment_ids_skips_overly_common_negative_term(monkeypatch):
    # 否定詞剛好比對到候選池 100%（例如「畫面」），套用 sparse_scores()
    # 既有的比例門檻防呆，不會把幾乎全部片段都排除掉
    monkeypatch.setattr(db, "fts_bm25_search", lambda terms, video_ids=None: [])
    monkeypatch.setattr(db, "fts_like_search", lambda term, video_ids=None: list(_TEN_IDS))

    excluded = sparse.negated_segment_ids("不要畫面", _TEN_IDS)

    assert excluded == set()


# ----------------------------------------------------------------------
# hit_source_label()：依分數決定顯示「字幕／畫面／OCR／組合／綜合」，純邏輯
# ----------------------------------------------------------------------


def test_hit_source_single_modality():
    assert results.hit_source_label(0.8, None, None) == "字幕"
    assert results.hit_source_label(None, 0.8, None) == "畫面"
    assert results.hit_source_label(None, None, 0.8) == "OCR"


def test_hit_source_two_close_scores_combined():
    # 差距 0.02 < _CLOSE_THRESHOLD(0.03)，視為並列
    assert results.hit_source_label(0.80, 0.78, None) == "字幕＋畫面"


def test_hit_source_two_far_apart_scores_only_shows_higher():
    # 差距 0.10 >= _CLOSE_THRESHOLD，只顯示分數較高的模態
    assert results.hit_source_label(0.80, 0.70, None) == "字幕"


def test_hit_source_three_close_scores_shows_comprehensive():
    assert results.hit_source_label(0.80, 0.79, 0.78) == "綜合"


def test_hit_source_close_threshold_boundary_is_exclusive():
    # 差距剛好等於門檻（不是小於）不算並列
    assert results.hit_source_label(0.80, 0.80 - results._CLOSE_THRESHOLD, None) == "字幕"
