"""analyzer.py 的場景過濾邏輯與 Tier 1／Tier 2 平行化（見
docs/analysis-pipeline-parallelization-plan.md）測試：本地 OCR 只應該掃描
VLM-OCR 沒抓到文字的場景；Phase C 片段內三個 embedding 平行送出後 budget
截斷時機要跟循序版本一致；Phase E／F 同時起跑時彼此失敗互不影響、
total_cost 不會重複計算或漏算；Phase B 批次平行後場景順序不能被打亂、
budget 改成逐批次檢查、rate limit 重試邏輯正確。用假的
ocr_service.scan_scenes／embedding.embed_text／vlm 攔截實際呼叫參數，
不跑真實 EasyOCR／OpenAI。"""
from __future__ import annotations

import queue
import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx2
import openai

from ai_video_search_web.pipeline import analyzer
from ai_video_search_web.pipeline.embedding import EmbedResult
from ai_video_search_web.pipeline.asr import SegmentScores
from ai_video_search_web.pipeline.vlm import DescribeResult
from ai_video_search_web.pipeline.scene_detect import NormalizedScene

_DUMMY_VIDEO_PATH = Path("/dev/null")
_NO_SCORES = SegmentScores(no_speech_prob=None, avg_logprob=None, compression_ratio=None)


def _context(initial_cost: float = 0.0) -> analyzer._AnalysisContext:
    """測試用的分析 context：固定的 video_id／影片路徑／假 client，進度事件丟進
    一條沒人讀的 queue。initial_cost 對應重構前直接傳進 phase 函式的 total_cost。
    """
    return analyzer._AnalysisContext(
        video_id=1, video_path=_DUMMY_VIDEO_PATH, client=MagicMock(),
        progress_queue=queue.Queue(), initial_cost=initial_cost,
    )


def _rate_limit_error() -> openai.RateLimitError:
    request = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx2.Response(status_code=429, request=request)
    return openai.RateLimitError("rate limited", response=response, body=None)


def _segment_row(start_sec: float, end_sec: float, ocr_text: str | None) -> analyzer._SegmentRow:
    return analyzer._SegmentRow(
        start_sec=start_sec, end_sec=end_sec, transcript_text="transcript", description="description",
        ocr_text=ocr_text, transcript_embedding=None, visual_embedding=None, ocr_embedding=None,
        scores=_NO_SCORES, frame_count=1,
    )


def _scene_row(
    start_sec: float,
    end_sec: float,
    transcript_text: str = "",
    description: str = "",
    ocr_text: str | None = None,
    scores: SegmentScores = _NO_SCORES,
    frame_count: int = 1,
) -> analyzer._SceneAnalysisRow:
    return analyzer._SceneAnalysisRow(
        start_sec=start_sec, end_sec=end_sec, transcript_text=transcript_text, description=description,
        ocr_text=ocr_text, scores=scores, frame_count=frame_count,
    )


def test_run_local_ocr_only_scans_scenes_without_vlm_ocr_text(monkeypatch):
    segment_rows = [
        _segment_row(0.0, 6.0, "已經有文字"),
        _segment_row(6.0, 12.0, None),
        _segment_row(12.0, 18.0, ""),
        _segment_row(18.0, 24.0, "也有文字"),
    ]
    segment_ids = [101, 102, 103, 104]

    captured: dict[str, object] = {}

    def fake_scan_scenes(video_id, video_path, scenes, on_progress=None):
        captured["scenes"] = scenes
        return []

    monkeypatch.setattr(analyzer.ocr_service, "scan_scenes", fake_scan_scenes)

    ctx = _context()
    analyzer._run_local_ocr(ctx, segment_rows, segment_ids)

    assert captured["scenes"] == [(6.0, 12.0, 102), (12.0, 18.0, 103)]
    assert ctx.total_cost == 0.0


def test_run_local_ocr_skips_scan_scenes_when_all_covered_by_vlm(monkeypatch):
    """VLM 已經覆蓋全部場景時，連 scan_scenes 都不該呼叫——省下 EasyOCR 模型
    冷啟動的時間（實測約 10 秒），不是只掃到 0 個場景而已。"""
    segment_rows = [_segment_row(0.0, 6.0, "文字A"), _segment_row(6.0, 12.0, "文字B")]
    segment_ids = [201, 202]

    scan_scenes_mock = MagicMock(side_effect=AssertionError("不該被呼叫"))
    monkeypatch.setattr(analyzer.ocr_service, "scan_scenes", scan_scenes_mock)

    ctx = _context()
    analyzer._run_local_ocr(ctx, segment_rows, segment_ids)

    scan_scenes_mock.assert_not_called()
    assert ctx.total_cost == 0.0


def test_embed_segment_texts_returns_all_present_kinds(monkeypatch):
    def fake_embed_text(client, text):
        return EmbedResult(vector=[float(len(text))], cost_usd=0.01)

    monkeypatch.setattr(analyzer.embedding, "embed_text", fake_embed_text)

    results = analyzer._embed_segment_texts(MagicMock(), transcript="abc", visual="de", ocr=None)

    assert set(results) == {"transcript", "visual"}
    assert results["transcript"].vector == [3.0]
    assert results["visual"].vector == [2.0]


def test_embed_segment_texts_skips_missing_texts(monkeypatch):
    monkeypatch.setattr(analyzer.embedding, "embed_text", MagicMock(side_effect=AssertionError("不該被呼叫")))

    results = analyzer._embed_segment_texts(MagicMock(), transcript=None, visual="", ocr=None)

    assert results == {}


def test_run_embedding_phase_stops_at_same_segment_as_sequential(monkeypatch):
    """平行送出片段內三個 embedding 後，budget 截斷的時機（在第幾個片段停）
    要跟循序版本完全一致：一個片段的三個 embedding 都做完才檢查一次。"""
    monkeypatch.setattr(analyzer, "BUDGET_USD", 0.20)  # 固定測試用的門檻，不依賴正式常數的實際值
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())

    call_count = {"n": 0}

    def fake_embed_text(client, text):
        call_count["n"] += 1
        return EmbedResult(vector=[0.0], cost_usd=0.05)

    monkeypatch.setattr(analyzer.embedding, "embed_text", fake_embed_text)

    scene_rows = [
        _scene_row(0.0, 1.0, transcript_text="t0", description="d0", ocr_text="o0"),
        _scene_row(1.0, 2.0, transcript_text="t1", description="d1", ocr_text="o1"),
        _scene_row(2.0, 3.0, transcript_text="t2", description="d2", ocr_text="o2"),
    ]

    ctx = _context()
    segment_rows = analyzer._run_embedding_phase(ctx, scene_rows)

    # 每個片段 3 個 embedding * $0.05：第 1 個片段做完 $0.15（未超支，繼續），
    # 第 2 個片段做完 $0.30（超支，停）——第 3 個片段完全不該被處理。
    assert len(segment_rows) == 2
    assert call_count["n"] == 6
    assert round(ctx.total_cost, 10) == 0.30


def test_run_embedding_phase_skips_transcript_embedding_when_hallucinated(monkeypatch):
    """字幕疑似幻覺（no_speech_prob 超過門檻）時不建立字幕 embedding，避免
    污染搜尋；但 segments.transcript 仍然照實際內容寫入，不隱藏原始字幕。"""
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())

    embedded_texts = []

    def fake_embed_text(client, text):
        embedded_texts.append(text)
        return EmbedResult(vector=[0.0], cost_usd=0.01)

    monkeypatch.setattr(analyzer.embedding, "embed_text", fake_embed_text)

    hallucinated_scores = SegmentScores(no_speech_prob=0.9, avg_logprob=-0.1, compression_ratio=1.1)
    normal_scores = SegmentScores(no_speech_prob=0.2, avg_logprob=-0.3, compression_ratio=1.2)

    scene_rows = [
        _scene_row(0.0, 1.0, transcript_text="ក្រាមំ ក្រាមំ", scores=hallucinated_scores),
        _scene_row(1.0, 2.0, transcript_text="真實字幕", scores=normal_scores),
    ]

    segment_rows = analyzer._run_embedding_phase(_context(), scene_rows)

    assert len(segment_rows) == 2
    assert "ក្រាមំ ក្រាមំ" not in embedded_texts  # 幻覺字幕沒有被送去 embed
    assert "真實字幕" in embedded_texts

    assert segment_rows[0].transcript_text == "ក្រាមំ ក្រាមំ"  # 原始字幕文字仍完整寫入
    assert segment_rows[1].transcript_text == "真實字幕"

    assert segment_rows[0].transcript_embedding is None  # 幻覺那筆沒有 transcript_embedding
    assert segment_rows[1].transcript_embedding is not None  # 真實那筆有


def test_run_embedding_phase_skips_transcript_embedding_for_repetitive_run(monkeypatch):
    """模式 B：信心分數正常但連續場景被同一個詞主導（例如「Music Music」）
    也不該建立字幕 embedding——這是模式 A（信心分數）完全抓不到、需要跨場景
    判斷的情況。"""
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())

    embedded_texts = []

    def fake_embed_text(client, text):
        embedded_texts.append(text)
        return EmbedResult(vector=[0.0], cost_usd=0.01)

    monkeypatch.setattr(analyzer.embedding, "embed_text", fake_embed_text)

    # 信心分數完全正常（模式 A 不會觸發），但 3 個連續場景都是 Music 重複
    normal_scores = SegmentScores(no_speech_prob=0.3, avg_logprob=-0.3, compression_ratio=1.2)

    scene_rows = [
        _scene_row(0.0, 1.0, transcript_text="Music", scores=normal_scores),
        _scene_row(1.0, 2.0, transcript_text="Music Music", scores=normal_scores),
        _scene_row(2.0, 3.0, transcript_text="Music", scores=normal_scores),
        _scene_row(3.0, 4.0, transcript_text="真實字幕內容", scores=normal_scores),
    ]

    segment_rows = analyzer._run_embedding_phase(_context(), scene_rows)

    assert len(segment_rows) == 4
    assert "Music" not in embedded_texts
    assert "Music Music" not in embedded_texts
    assert "真實字幕內容" in embedded_texts

    # 原始文字仍然完整寫入，即使沒有 embedding
    assert [row.transcript_text for row in segment_rows] == ["Music", "Music Music", "Music", "真實字幕內容"]
    assert segment_rows[0].transcript_embedding is None
    assert segment_rows[1].transcript_embedding is None
    assert segment_rows[2].transcript_embedding is None
    assert segment_rows[3].transcript_embedding is not None


def test_run_local_ocr_and_summary_combines_costs_without_double_counting(monkeypatch):
    """Phase E／F 都要用「進入這個函式那一刻」的 total_cost 當基準，不是
    「E 跑完後」的金額——最終合計不能重複計算或漏算任一邊的花費。"""
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())

    def fake_run_local_ocr(ctx, segment_rows, segment_ids):
        assert ctx.total_cost == 0.05  # 收到的是基準值，不是「循序版本」會有的其他數字
        ctx.spend(0.02)

    def fake_run_summary_phase(ctx):
        assert ctx.total_cost == 0.05  # 用「本地 OCR 開始前」的金額判斷，不是 OCR 跑完後
        ctx.spend(0.03)
        return "摘要文字"

    monkeypatch.setattr(analyzer, "_run_local_ocr", fake_run_local_ocr)
    monkeypatch.setattr(analyzer, "_run_summary_phase", fake_run_summary_phase)

    ctx = _context(initial_cost=0.05)
    summary_text = analyzer._run_local_ocr_and_summary(ctx, [], [])

    assert summary_text == "摘要文字"
    assert round(ctx.total_cost, 10) == 0.10  # 0.05（基準）+ 0.02（OCR）+ 0.03（摘要）


def test_run_local_ocr_and_summary_isolates_local_ocr_failure(monkeypatch):
    """本地 OCR 那個子執行緒丟例外時，只記 log、不能影響摘要照常執行，
    也不能讓例外冒出這個函式（延續既有的失敗隔離原則）。"""
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())

    def fake_run_local_ocr(ctx, segment_rows, segment_ids):
        raise RuntimeError("本地 OCR 掛了")

    def fake_run_summary_phase(ctx):
        ctx.spend(0.03)
        return "摘要照常產生"

    monkeypatch.setattr(analyzer, "_run_local_ocr", fake_run_local_ocr)
    monkeypatch.setattr(analyzer, "_run_summary_phase", fake_run_summary_phase)

    ctx = _context(initial_cost=0.05)
    summary_text = analyzer._run_local_ocr_and_summary(ctx, [], [])

    assert summary_text == "摘要照常產生"
    # 本地 OCR 失敗沒有貢獻花費，總花費只有基準值 + 摘要花費
    assert round(ctx.total_cost, 10) == 0.08


def test_run_scene_detection_and_transcription_returns_both_results(monkeypatch):
    def fake_run_scene_detection(ctx, duration_sec):
        return [(0.0, 1.0)]

    def fake_run_transcription(ctx, duration_sec):
        ctx.spend(0.01)
        return "TRANSCRIBE_RESULT"

    monkeypatch.setattr(analyzer, "_run_scene_detection", fake_run_scene_detection)
    monkeypatch.setattr(analyzer, "_run_transcription", fake_run_transcription)

    ctx = _context()
    scenes, transcribe_result = analyzer._run_scene_detection_and_transcription(ctx, 10.0)

    assert scenes == [(0.0, 1.0)]
    assert transcribe_result == "TRANSCRIBE_RESULT"
    assert round(ctx.total_cost, 10) == 0.01


def test_run_scene_detection_and_transcription_joins_thread_even_if_scene_detection_fails(monkeypatch):
    """場景切分萬一拋例外，也要等轉錄執行緒做完才能離開這個函式——不能留下
    沒 join 的執行緒繼續在背景花錢。"""
    transcription_completed = {"done": False}

    def fake_run_scene_detection(ctx, duration_sec):
        raise RuntimeError("場景切分失敗")

    def fake_run_transcription(ctx, duration_sec):
        time.sleep(0.05)  # 模擬轉錄仍在進行中
        transcription_completed["done"] = True
        ctx.spend(0.01)
        return "TRANSCRIBE_RESULT"

    monkeypatch.setattr(analyzer, "_run_scene_detection", fake_run_scene_detection)
    monkeypatch.setattr(analyzer, "_run_transcription", fake_run_transcription)

    try:
        analyzer._run_scene_detection_and_transcription(_context(), 10.0)
        raise AssertionError("應該要拋出場景切分的例外")
    except RuntimeError as exc:
        assert "場景切分失敗" in str(exc)

    assert transcription_completed["done"] is True


# ----------------------------------------------------------------------
# _frame_fractions_for()：VLM 條件式多幀取樣的觸發判斷，純邏輯（不呼叫
# API／不需要真的場景偵測結果），見 docs/02-technical-decisions.md
# 「VLM 條件式多幀取樣」
# ----------------------------------------------------------------------


def test_frame_fractions_for_returns_default_when_not_split():
    scene = NormalizedScene(0.0, 10.0, source_raw_duration=10.0)
    assert analyzer._frame_fractions_for(scene) == analyzer.vlm.DEFAULT_FRAME_FRACTIONS


def test_frame_fractions_for_returns_default_at_threshold_boundary():
    # 剛好等於門檻不算超過，維持單幀（>，不是 >=）
    scene = NormalizedScene(0.0, 10.0, source_raw_duration=analyzer.MULTI_FRAME_TRIGGER_SEC)
    assert analyzer._frame_fractions_for(scene) == analyzer.vlm.DEFAULT_FRAME_FRACTIONS


def test_frame_fractions_for_triggers_multi_frame_above_threshold():
    scene = NormalizedScene(20.0, 30.0, source_raw_duration=analyzer.MULTI_FRAME_TRIGGER_SEC + 0.1)
    assert analyzer._frame_fractions_for(scene) == analyzer.MULTI_FRAME_FRACTIONS


def test_run_vlm_phase_passes_multi_frame_fractions_to_triggered_scenes(monkeypatch):
    """source_raw_duration 超過門檻的場景要收到 MULTI_FRAME_FRACTIONS，沒超過
    的場景維持預設單幀——驗證 _run_vlm_phase() 有把 _frame_fractions_for()
    的判斷結果實際往下傳給 VLM 呼叫，不是只算出來沒使用。"""
    monkeypatch.setattr(analyzer, "VLM_BATCH_SIZE", 2)
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer.asr, "text_for_range", lambda segments, s, e: "")
    monkeypatch.setattr(analyzer.asr, "scores_for_range", lambda segments, s, e: _NO_SCORES)

    received_fractions: list[tuple[float, ...]] = []

    def fake_describe(client, video_path, start_sec, end_sec, frame_fractions):
        received_fractions.append(frame_fractions)
        return DescribeResult(
            description="d", ocr_text=None, cost_usd=0.0, frame_count=len(frame_fractions),
        )

    monkeypatch.setattr(analyzer, "_describe_segment_with_retry", fake_describe)

    scenes = [
        NormalizedScene(0.0, 10.0, source_raw_duration=10.0),  # 沒被硬切，單幀
        NormalizedScene(10.0, 20.0, source_raw_duration=40.0),  # 硬切出來的，觸發多幀
    ]

    scene_rows, _ = analyzer._run_vlm_phase(_context(), scenes, MagicMock(segments=[]))

    assert received_fractions == [analyzer.vlm.DEFAULT_FRAME_FRACTIONS, analyzer.MULTI_FRAME_FRACTIONS]
    assert [row.frame_count for row in scene_rows] == [1, 2]


def test_run_vlm_phase_preserves_scene_order_despite_parallel_completion(monkeypatch):
    """批次內用執行緒平行呼叫，完成的先後順序不保證跟送出順序一樣——結果
    一定要照送出順序組裝，不能被完成順序打亂。"""
    monkeypatch.setattr(analyzer, "VLM_BATCH_SIZE", 3)
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer.asr, "text_for_range", lambda segments, s, e: f"T{s}")
    monkeypatch.setattr(analyzer.asr, "scores_for_range", lambda segments, s, e: _NO_SCORES)

    def fake_describe(client, video_path, start_sec, end_sec, frame_fractions):
        # 場景時間點越晚、睡越短，讓「後面」的場景反而先完成
        time.sleep(0.03 * (3 - start_sec))
        return DescribeResult(description=f"D{start_sec}", ocr_text=None, cost_usd=0.0, frame_count=1)

    monkeypatch.setattr(analyzer, "_describe_segment_with_retry", fake_describe)

    scenes = [
        NormalizedScene(0.0, 1.0, source_raw_duration=1.0),
        NormalizedScene(1.0, 2.0, source_raw_duration=1.0),
        NormalizedScene(2.0, 3.0, source_raw_duration=1.0),
    ]

    ctx = _context()
    scene_rows, vlm_failed_count = analyzer._run_vlm_phase(ctx, scenes, MagicMock(segments=[]))

    assert [row.description for row in scene_rows] == ["D0.0", "D1.0", "D2.0"]
    assert [row.transcript_text for row in scene_rows] == ["T0.0", "T1.0", "T2.0"]
    assert [(row.start_sec, row.end_sec) for row in scene_rows] == [(s.start_sec, s.end_sec) for s in scenes]
    assert round(ctx.total_cost, 10) == 0.0
    assert vlm_failed_count == 0


def test_run_vlm_phase_checks_budget_once_per_batch_not_per_scene(monkeypatch):
    """budget 檢查放寬成「整批做完才檢查」：循序版本會在第 2 個場景就因為
    超支停下來，批次版本要等整批（3 個場景）都做完才檢查，所以 3 個全部
    被處理——這是刻意接受的已知取捨，不是 bug。"""
    monkeypatch.setattr(analyzer, "VLM_BATCH_SIZE", 3)
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer.asr, "text_for_range", lambda segments, s, e: "")
    monkeypatch.setattr(analyzer.asr, "scores_for_range", lambda segments, s, e: _NO_SCORES)

    def fake_describe(client, video_path, start_sec, end_sec, frame_fractions):
        return DescribeResult(description="d", ocr_text=None, cost_usd=0.15, frame_count=1)

    monkeypatch.setattr(analyzer, "_describe_segment_with_retry", fake_describe)

    scenes = [
        NormalizedScene(0.0, 1.0, source_raw_duration=1.0),
        NormalizedScene(1.0, 2.0, source_raw_duration=1.0),
        NormalizedScene(2.0, 3.0, source_raw_duration=1.0),
    ]

    ctx = _context()
    scene_rows, vlm_failed_count = analyzer._run_vlm_phase(ctx, scenes, MagicMock(segments=[]))

    assert len(scene_rows) == 3
    assert round(ctx.total_cost, 10) == 0.45
    assert vlm_failed_count == 0


def test_run_vlm_phase_stops_at_batch_boundary_when_more_scenes_remain(monkeypatch):
    """第 2 批超支後，第 3 批完全不該開始。"""
    monkeypatch.setattr(analyzer, "BUDGET_USD", 0.20)  # 固定測試用的門檻，不依賴正式常數的實際值
    monkeypatch.setattr(analyzer, "VLM_BATCH_SIZE", 2)
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer.asr, "text_for_range", lambda segments, s, e: "")
    monkeypatch.setattr(analyzer.asr, "scores_for_range", lambda segments, s, e: _NO_SCORES)

    call_count = {"n": 0}

    def fake_describe(client, video_path, start_sec, end_sec, frame_fractions):
        call_count["n"] += 1
        return DescribeResult(description="d", ocr_text=None, cost_usd=0.11, frame_count=1)

    monkeypatch.setattr(analyzer, "_describe_segment_with_retry", fake_describe)

    scenes = [
        NormalizedScene(0.0, 1.0, source_raw_duration=1.0),
        NormalizedScene(1.0, 2.0, source_raw_duration=1.0),
        NormalizedScene(2.0, 3.0, source_raw_duration=1.0),
        NormalizedScene(3.0, 4.0, source_raw_duration=1.0),
        NormalizedScene(4.0, 5.0, source_raw_duration=1.0),
        NormalizedScene(5.0, 6.0, source_raw_duration=1.0),
    ]

    ctx = _context()
    scene_rows, vlm_failed_count = analyzer._run_vlm_phase(ctx, scenes, MagicMock(segments=[]))

    # 第 1 批（2 個場景）：0.22，超支，停——第 2、3 批完全不該開始
    assert len(scene_rows) == 2
    assert call_count["n"] == 2
    assert round(ctx.total_cost, 10) == 0.22
    assert vlm_failed_count == 0


def test_run_vlm_phase_isolates_single_scene_failure(monkeypatch):
    """單一場景的 VLM 呼叫失敗（例如內容審查拒絕）不該讓整支分析失敗——
    只跳過那個場景的畫面描述／OCR，字幕跟其他場景不受影響。"""
    monkeypatch.setattr(analyzer, "VLM_BATCH_SIZE", 3)
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer.asr, "text_for_range", lambda segments, s, e: f"字幕{s}")
    monkeypatch.setattr(analyzer.asr, "scores_for_range", lambda segments, s, e: _NO_SCORES)

    def fake_describe(client, video_path, start_sec, end_sec, frame_fractions):
        if start_sec == 1.0:
            raise RuntimeError("內容審查拒絕")
        return DescribeResult(description=f"D{start_sec}", ocr_text=f"O{start_sec}", cost_usd=0.05, frame_count=1)

    monkeypatch.setattr(analyzer, "_describe_segment_with_retry", fake_describe)

    scenes = [
        NormalizedScene(0.0, 1.0, source_raw_duration=1.0),
        NormalizedScene(1.0, 2.0, source_raw_duration=1.0),
        NormalizedScene(2.0, 3.0, source_raw_duration=1.0),
    ]

    ctx = _context()
    scene_rows, vlm_failed_count = analyzer._run_vlm_phase(ctx, scenes, MagicMock(segments=[]))

    assert vlm_failed_count == 1
    # 失敗場景（index 1）：字幕保留、畫面描述空字串、OCR 是 None
    assert [row.transcript_text for row in scene_rows] == ["字幕0.0", "字幕1.0", "字幕2.0"]
    assert [row.description for row in scene_rows] == ["D0.0", "", "D2.0"]
    assert [row.ocr_text for row in scene_rows] == ["O0.0", None, "O2.0"]
    # 三個場景都還是有留下一筆
    assert [(row.start_sec, row.end_sec) for row in scene_rows] == [(s.start_sec, s.end_sec) for s in scenes]
    assert [row.frame_count for row in scene_rows] == [1, 0, 1]  # 失敗場景的 frame_count 記 0
    # 失敗場景沒有貢獻花費，只有 2 個成功場景各 0.05
    assert round(ctx.total_cost, 10) == 0.10


def test_run_vlm_phase_failure_does_not_trigger_budget_break(monkeypatch):
    """失敗場景的花費算 0，不會誤觸發 budget 截斷。"""
    monkeypatch.setattr(analyzer, "VLM_BATCH_SIZE", 2)
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer.asr, "text_for_range", lambda segments, s, e: "")
    monkeypatch.setattr(analyzer.asr, "scores_for_range", lambda segments, s, e: _NO_SCORES)

    def fake_describe(client, video_path, start_sec, end_sec, frame_fractions):
        if start_sec == 0.0:
            raise RuntimeError("失敗")
        return DescribeResult(description="d", ocr_text=None, cost_usd=0.19, frame_count=1)

    monkeypatch.setattr(analyzer, "_describe_segment_with_retry", fake_describe)

    scenes = [
        NormalizedScene(0.0, 1.0, source_raw_duration=1.0),
        NormalizedScene(1.0, 2.0, source_raw_duration=1.0),
    ]

    ctx = _context()
    scene_rows, vlm_failed_count = analyzer._run_vlm_phase(ctx, scenes, MagicMock(segments=[]))

    assert vlm_failed_count == 1
    assert len(scene_rows) == 2  # 兩個場景都留下一筆，沒有被 budget 截斷
    assert round(ctx.total_cost, 10) == 0.19


def test_describe_segment_with_retry_retries_on_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr(analyzer, "VLM_RATE_LIMIT_RETRY_WAIT_SEC", 0.0)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    attempts = {"n": 0}

    def fake_describe_segment(client, video_path, start_sec, end_sec, frame_fractions):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise _rate_limit_error()
        return DescribeResult(description="成功", ocr_text=None, cost_usd=0.01, frame_count=1)

    monkeypatch.setattr(analyzer.vlm, "describe_segment", fake_describe_segment)

    result = analyzer._describe_segment_with_retry(MagicMock(), _DUMMY_VIDEO_PATH, 0.0, 1.0, (0.5,))

    assert result.description == "成功"
    assert attempts["n"] == 2


def test_describe_segment_with_retry_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(analyzer, "VLM_RATE_LIMIT_MAX_RETRIES", 2)
    monkeypatch.setattr(analyzer, "VLM_RATE_LIMIT_RETRY_WAIT_SEC", 0.0)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    attempts = {"n": 0}

    def fake_describe_segment(client, video_path, start_sec, end_sec, frame_fractions):
        attempts["n"] += 1
        raise _rate_limit_error()

    monkeypatch.setattr(analyzer.vlm, "describe_segment", fake_describe_segment)

    try:
        analyzer._describe_segment_with_retry(MagicMock(), _DUMMY_VIDEO_PATH, 0.0, 1.0, (0.5,))
        raise AssertionError("應該要在重試用完後把例外拋出去")
    except openai.RateLimitError:
        pass

    # 第 1 次呼叫 + 最多 2 次重試 = 總共 3 次
    assert attempts["n"] == 3


def test_describe_segment_with_retry_does_not_retry_other_exceptions(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)

    attempts = {"n": 0}

    def fake_describe_segment(client, video_path, start_sec, end_sec, frame_fractions):
        attempts["n"] += 1
        raise RuntimeError("非 rate limit 的例外")

    monkeypatch.setattr(analyzer.vlm, "describe_segment", fake_describe_segment)

    try:
        analyzer._describe_segment_with_retry(MagicMock(), _DUMMY_VIDEO_PATH, 0.0, 1.0, (0.5,))
        raise AssertionError("應該要直接把例外拋出去，不重試")
    except RuntimeError:
        pass

    assert attempts["n"] == 1
