"""search.search() 的端到端特徵測試（characterization tests）：鎖住整條搜尋
流程「候選集 → 三模態評分 → 否定排除 → RRF 排序 → 品質門檻 → top_k」以及
is_confident／cost_usd／search_log 這三個容易被忽略的可觀察結果，做為之後把
search.py 拆成子模組（重構 B4）的安全網。

跟 tests/test_search.py 的分工：那邊測個別 helper 的純邏輯（`_extract_terms`／
`_rrf_scores`／`_apply_quality_filter`／`_hit_source`…），這裡測「把它們串起來
之後」的行為，包含只有整條跑完才看得到的細節——例如 is_confident 用的是套用
品質門檻**之前**的 top1，所以 results 是空的時候 is_confident 仍可能是 True。

隔離方式：資料庫用真的（tmp_path 的臨時 SQLite，連 FTS5 bm25 都是真的跑），
只把會呼叫 OpenAI 的兩個點換掉——`translation.translate_query()` 與
`embedding.embed_text()`。向量刻意用 4 維（真實是 1024 維），cosine 相似度
算出來的數字才好人工推算、斷言才寫得出確定值。
"""
from __future__ import annotations

import pytest

from ai_video_search_web import db
from ai_video_search_web.pipeline import embedding, translation
from ai_video_search_web.pipeline import search
from ai_video_search_web.pipeline.search import dense, fusion, results as results_module, service

# 查詢向量固定用這個方向；片段向量跟它的夾角決定相似度，方便人工推算。
QUERY_VECTOR = [1.0, 0.0, 0.0, 0.0]
SIMILARITY_1_00 = [1.0, 0.0, 0.0, 0.0]  # cosine = 1.00
SIMILARITY_0_71 = [1.0, 1.0, 0.0, 0.0]  # cosine = 0.707
SIMILARITY_0_45 = [1.0, 2.0, 0.0, 0.0]  # cosine = 0.447
SIMILARITY_0_20 = [1.0, 5.0, 0.0, 0.0]  # cosine = 0.196（低於 MIN_SIMILARITY）
UNRELATED = [0.0, 0.0, 0.0, 1.0]  # cosine = 0.00

TRANSLATE_COST = 0.001
EMBED_COST = 0.0001


class _FakeEmbedder:
    """取代 embedding.embed_text()：依文字查表回傳固定向量，記錄被 embed 過
    的文字（用來驗證「有沒有多花錢」——例如指定 video_id 時不該再為了影片
    層級篩選去 embed 每支影片的摘要）。查不到的文字回傳跟查詢正交的向量。
    """

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.texts: list[str] = []

    def __call__(self, client, text: str) -> embedding.EmbedResult:
        self.texts.append(text)
        return embedding.EmbedResult(vector=self.vectors.get(text, UNRELATED), cost_usd=EMBED_COST)


@pytest.fixture
def fake_openai(monkeypatch):
    """把 search.py 會碰到 OpenAI 的三個點換掉：get_client（不要真的建 client）、
    translate_query（回傳跟原文相同的中英文版本，讓 variants 收斂成一個，
    embedding 呼叫次數才可預期）、embed_text。回傳 embedder 供測試斷言。
    """
    embedder = _FakeEmbedder({})
    monkeypatch.setattr(service, "get_client", lambda: object())
    monkeypatch.setattr(
        dense.translation,
        "translate_query",
        lambda client, query: translation.TranslateResult(
            chinese=query, english=query, cost_usd=TRANSLATE_COST
        ),
    )
    monkeypatch.setattr(dense.embedding, "embed_text", embedder)
    # 影片標題／摘要的 embedding 快取是模組全域 dict，會跨測試殘留，每個測試
    # 都要換成新的，否則上一個測試的向量會讓這個測試的影片篩選結果不可預期。
    monkeypatch.setattr(dense, "_title_summary_embedding_cache", {})
    return embedder


def _add_video(title: str = "測試影片", summary: str | None = None) -> int:
    video_id = db.insert_video(
        title=title, source=db.SOURCE_LOCAL, source_url=None,
        file_path="/nonexistent.mp4", duration_sec=100,
    )
    db.update_video_status(video_id, db.STATUS_ANALYZED)
    if summary is not None:
        db.update_video_summary(video_id, summary, "fake-model", 0.0)
    return video_id


def _add_segment(
    video_id: int,
    *,
    transcript: str | None = None,
    visual: str | None = None,
    ocr: str | None = None,
    transcript_vec: list[float] | None = None,
    visual_vec: list[float] | None = None,
    ocr_vec: list[float] | None = None,
    start_sec: float = 0.0,
    end_sec: float = 5.0,
) -> int:
    encode = embedding.encode_embedding
    return db.insert_segment(
        video_id=video_id,
        start_sec=start_sec,
        end_sec=end_sec,
        transcript=transcript,
        visual_description=visual,
        ocr_text=ocr,
        transcript_embedding=encode(transcript_vec) if transcript_vec else None,
        visual_embedding=encode(visual_vec) if visual_vec else None,
        ocr_embedding=encode(ocr_vec) if ocr_vec else None,
        asr_model="fake", vlm_model="fake", embedding_model="fake",
    )


def _search_log_rows() -> list[tuple[str, float]]:
    with db.get_connection() as conn:
        rows = conn.execute("SELECT query, cost_usd FROM search_log ORDER BY id").fetchall()
    return [(row["query"], row["cost_usd"]) for row in rows]


# ----------------------------------------------------------------------
# 空候選集：仍然要記錄搜尋成本
# ----------------------------------------------------------------------
def test_search_with_no_segments_returns_empty_but_still_logs_cost(temp_db, fake_openai):
    fake_openai.vectors["找機器人"] = QUERY_VECTOR

    response = search.search("找機器人")

    assert response.results == []
    assert response.is_confident is False
    assert response.cost_usd == pytest.approx(TRANSLATE_COST + EMBED_COST)
    assert _search_log_rows() == [("找機器人", pytest.approx(TRANSLATE_COST + EMBED_COST))]


def test_search_logs_cost_even_when_negation_removes_every_candidate(temp_db, fake_openai):
    fake_openai.vectors["畫面 不要機器人"] = QUERY_VECTOR
    video_id = _add_video()
    _add_segment(video_id, transcript="工廠裡的機器人正在組裝", transcript_vec=SIMILARITY_1_00)

    response = search.search("畫面 不要機器人")

    assert response.results == []
    assert len(_search_log_rows()) == 1


# ----------------------------------------------------------------------
# 正常路徑：排序、欄位內容、similarity 的定義
# ----------------------------------------------------------------------
def test_search_orders_by_fusion_score_and_fills_result_fields(temp_db, fake_openai):
    fake_openai.vectors["紅色衣服"] = QUERY_VECTOR
    video_id = _add_video(title="工廠巡檢")
    low = _add_segment(video_id, visual="灰牆", visual_vec=SIMILARITY_0_45, start_sec=10.0, end_sec=15.0)
    high = _add_segment(video_id, visual="穿著制服的人", visual_vec=SIMILARITY_1_00, start_sec=0.0, end_sec=5.0)
    mid = _add_segment(video_id, visual="走廊", visual_vec=SIMILARITY_0_71, start_sec=20.0, end_sec=25.0)

    response = search.search("紅色衣服")

    assert [r.segment_id for r in response.results] == [high, mid, low]
    top = response.results[0]
    assert top.video_id == video_id
    assert top.video_title == "工廠巡檢"
    assert top.start_sec == 0.0 and top.end_sec == 5.0
    assert top.similarity == pytest.approx(1.0)
    assert top.visual_score == pytest.approx(1.0)
    assert top.transcript_score is None and top.ocr_score is None
    assert top.description == "穿著制服的人"
    assert top.hit_source == "畫面"
    assert top.fusion_strategy == results_module.FUSION_STRATEGY
    # 融合分數由高到低嚴格遞減，且都是 RRF 值（1/(K+rank)）而不是 cosine
    assert [r.fusion_score for r in response.results] == sorted(
        (r.fusion_score for r in response.results), reverse=True
    )
    assert response.results[0].fusion_score == pytest.approx(1 / (fusion.RRF_K + 1))


def test_search_similarity_is_the_max_of_three_modality_scores(temp_db, fake_openai):
    fake_openai.vectors["查詢"] = QUERY_VECTOR
    video_id = _add_video()
    _add_segment(
        video_id,
        transcript="甲", visual="乙", ocr="丙",
        transcript_vec=SIMILARITY_0_45, visual_vec=SIMILARITY_1_00, ocr_vec=SIMILARITY_0_71,
    )

    result = search.search("查詢").results[0]

    assert result.transcript_score == pytest.approx(0.4472, abs=1e-3)
    assert result.visual_score == pytest.approx(1.0)
    assert result.ocr_score == pytest.approx(0.7071, abs=1e-3)
    assert result.similarity == pytest.approx(1.0)


def test_search_skips_segments_without_any_embedding(temp_db, fake_openai):
    fake_openai.vectors["查詢"] = QUERY_VECTOR
    video_id = _add_video()
    scored = _add_segment(video_id, visual="有向量", visual_vec=SIMILARITY_1_00)
    _add_segment(video_id, visual="沒有向量")  # 三個模態都沒有 embedding

    response = search.search("查詢")

    assert [r.segment_id for r in response.results] == [scored]


def test_search_merges_local_ocr_event_score_into_ocr_score(temp_db, fake_openai):
    """本地 OCR 事件是既有 OCR 模態的補充，不是獨立通道：同一個片段取兩者較高分。"""
    fake_openai.vectors["查詢"] = QUERY_VECTOR
    video_id = _add_video()
    segment_id = _add_segment(video_id, ocr="VLM 抓到的文字", ocr_vec=SIMILARITY_0_45)
    db.insert_ocr_event(
        video_id=video_id, segment_id=segment_id, start_sec=0.0, end_sec=5.0, frame_sec=1.0,
        raw_text="本地 OCR", resolved_text="本地 OCR", confidence=0.9, bbox=None,
        primary_engine="easyocr", ocr_pipeline_version="local-ocr-v1",
        embedding=embedding.encode_embedding(SIMILARITY_1_00),
    )

    result = search.search("查詢").results[0]

    assert result.ocr_score == pytest.approx(1.0)  # 取 max，不是覆寫也不是相加
    assert result.similarity == pytest.approx(1.0)


# ----------------------------------------------------------------------
# 品質門檻與 top_k
# ----------------------------------------------------------------------
def test_search_drops_results_below_similarity_threshold(temp_db, fake_openai):
    fake_openai.vectors["查詢"] = QUERY_VECTOR
    video_id = _add_video()
    keep = _add_segment(video_id, visual="夠像", visual_vec=SIMILARITY_0_45)
    _add_segment(video_id, visual="不夠像", visual_vec=SIMILARITY_0_20)

    response = search.search("查詢")

    assert [r.segment_id for r in response.results] == [keep]


def test_search_applies_quality_filter_before_top_k(temp_db, fake_openai):
    """top_k 是「回傳筆數上限」不是「一定回傳這麼多筆」：品質不夠的先被濾掉，
    剩下的才截斷。
    """
    fake_openai.vectors["查詢"] = QUERY_VECTOR
    video_id = _add_video()
    best = _add_segment(video_id, visual="最像", visual_vec=SIMILARITY_1_00)
    _add_segment(video_id, visual="次像", visual_vec=SIMILARITY_0_71)
    _add_segment(video_id, visual="不夠像", visual_vec=SIMILARITY_0_20)

    response = search.search("查詢", top_k=1)

    assert [r.segment_id for r in response.results] == [best]


# ----------------------------------------------------------------------
# is_confident：用「套用品質門檻之前」的 top1 判斷
# ----------------------------------------------------------------------
def test_is_confident_true_when_top1_is_also_found_by_sparse_channel(temp_db, fake_openai):
    fake_openai.vectors["機器人"] = QUERY_VECTOR
    video_id = _add_video()
    _add_segment(video_id, transcript="工廠裡的機器人正在組裝", transcript_vec=SIMILARITY_1_00)
    _add_segment(video_id, visual="空無一人的走廊", visual_vec=SIMILARITY_0_71)

    response = search.search("機器人")

    assert response.is_confident is True


def test_is_confident_false_when_sparse_channel_finds_nothing(temp_db, fake_openai):
    fake_openai.vectors["紅色衣服"] = QUERY_VECTOR
    video_id = _add_video()
    _add_segment(video_id, visual="空無一人的走廊", visual_vec=SIMILARITY_1_00)

    response = search.search("紅色衣服")

    assert response.results != []
    assert response.is_confident is False


def test_is_confident_ignores_quality_filter_so_it_can_be_true_with_empty_results(temp_db, fake_openai):
    """這是整條流程最容易在重構時改壞的細節：is_confident 判斷的是「排序最頂端
    的候選有沒有被 sparse channel 印證」，用的是套用 MIN_SIMILARITY／
    MIN_FUSION_SCORE **之前**的候選集，所以回傳結果是空的時候它仍然可能是 True。
    """
    fake_openai.vectors["機器人"] = QUERY_VECTOR
    video_id = _add_video()
    _add_segment(video_id, transcript="工廠裡的機器人正在組裝", transcript_vec=SIMILARITY_0_20)

    response = search.search("機器人")

    assert response.results == []  # 相似度 0.196 沒過 MIN_SIMILARITY
    assert response.is_confident is True


# ----------------------------------------------------------------------
# 否定句排除
# ----------------------------------------------------------------------
def test_search_excludes_segments_hit_by_negated_terms(temp_db, fake_openai):
    fake_openai.vectors["工廠 不要機器人"] = QUERY_VECTOR
    video_id = _add_video()
    _add_segment(video_id, transcript="工廠裡的機器人正在組裝", transcript_vec=SIMILARITY_1_00)
    kept = _add_segment(video_id, transcript="工廠外的停車場空景", transcript_vec=SIMILARITY_0_71)

    response = search.search("工廠 不要機器人")

    assert [r.segment_id for r in response.results] == [kept]


# ----------------------------------------------------------------------
# 搜尋範圍：指定 video_id vs 全域（影片層級篩選）
# ----------------------------------------------------------------------
def test_search_with_video_id_scopes_to_that_video_and_skips_video_level_filter(temp_db, fake_openai):
    fake_openai.vectors["查詢"] = QUERY_VECTOR
    target = _add_video(title="目標影片", summary="這支影片講機器人")
    other = _add_video(title="另一支影片", summary="這支影片講烹飪")
    wanted = _add_segment(target, visual="目標片段", visual_vec=SIMILARITY_1_00)
    _add_segment(other, visual="其他片段", visual_vec=SIMILARITY_1_00)

    response = search.search("查詢", video_id=target)

    assert [r.segment_id for r in response.results] == [wanted]
    # 只 embed 查詢本身：指定影片時不做影片層級篩選，不會為了比對摘要多花錢
    assert fake_openai.texts == ["查詢"]
    assert response.cost_usd == pytest.approx(TRANSLATE_COST + EMBED_COST)


def test_global_search_filters_out_videos_whose_summary_is_irrelevant(temp_db, fake_openai):
    fake_openai.vectors["查詢"] = QUERY_VECTOR
    fake_openai.vectors["這支影片講機器人"] = SIMILARITY_1_00
    fake_openai.vectors["這支影片講烹飪"] = UNRELATED
    relevant = _add_video(title="機器人影片", summary="這支影片講機器人")
    irrelevant = _add_video(title="烹飪影片", summary="這支影片講烹飪")
    wanted = _add_segment(relevant, visual="產線畫面", visual_vec=SIMILARITY_1_00)
    _add_segment(irrelevant, visual="廚房畫面", visual_vec=SIMILARITY_1_00)

    response = search.search("查詢")

    assert [r.segment_id for r in response.results] == [wanted]
    # 兩支影片的摘要各 embed 一次，成本要算進去
    assert response.cost_usd == pytest.approx(TRANSLATE_COST + EMBED_COST * 3)


def test_global_search_keeps_all_videos_when_no_summary_stands_out(temp_db, fake_openai):
    """安全網：沒有任何影片明顯相關時不篩選，維持全部影片都搜尋。"""
    fake_openai.vectors["查詢"] = QUERY_VECTOR  # 兩支影片的摘要都拿不到向量 → 都是 0 分
    first = _add_video(title="A", summary="無關摘要一")
    second = _add_video(title="B", summary="無關摘要二")
    seg_a = _add_segment(first, visual="A 片段", visual_vec=SIMILARITY_1_00)
    seg_b = _add_segment(second, visual="B 片段", visual_vec=SIMILARITY_0_71)

    response = search.search("查詢")

    assert {r.segment_id for r in response.results} == {seg_a, seg_b}


# ----------------------------------------------------------------------
# 退回行為：翻譯失敗、search_log 記錄原始查詢
# ----------------------------------------------------------------------
def test_search_falls_back_to_original_query_when_translation_fails(temp_db, fake_openai, monkeypatch):
    def _boom(client, query):
        raise RuntimeError("翻譯 API 掛了")

    monkeypatch.setattr(dense.translation, "translate_query", _boom)
    fake_openai.vectors["查詢"] = QUERY_VECTOR
    video_id = _add_video()
    wanted = _add_segment(video_id, visual="片段", visual_vec=SIMILARITY_1_00)

    response = search.search("查詢")

    assert [r.segment_id for r in response.results] == [wanted]
    assert response.cost_usd == pytest.approx(EMBED_COST)  # 翻譯沒成功就沒有翻譯成本


def test_search_log_records_original_query_not_the_cleaned_one(temp_db, fake_openai):
    """泛用詞清理（「畫面」「段落」）只影響檢索本身，稽核軌跡要留使用者原本打的字。"""
    fake_openai.vectors["機器人的畫面"] = QUERY_VECTOR

    search.search("機器人的畫面")

    assert _search_log_rows()[0][0] == "機器人的畫面"
