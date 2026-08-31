"""analyzer.py 的場景過濾邏輯與 Tier 1／Tier 2 平行化（見
docs/02-technical-decisions.md#分析流程平行化）測試：本地 OCR 只應該掃描
VLM-OCR 沒抓到文字的場景；Phase C 片段內三個 embedding 平行送出後 budget
截斷時機要跟循序版本一致；Phase E／F 同時起跑時彼此失敗互不影響、
total_cost 不會重複計算或漏算；Phase F 的「文件優先、摘要當退路」四條分支
（成功／文件失敗／兩條都失敗／超支）；Phase B 批次平行後場景順序不能被打亂、
budget 改成逐批次檢查、rate limit 重試邏輯正確。用假的
ocr_service.scan_scenes／embedding.embed_text／vlm 攔截實際呼叫參數，
不跑真實 EasyOCR／OpenAI。"""
from __future__ import annotations

import queue
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx2
import openai
import pytest

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
        progress_queue=queue.Queue(), video_title="測試影片", initial_cost=initial_cost,
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


# ----------------------------------------------------------------------
# _analyze_worker()：不管怎麼失敗都要送出剛好一個終端事件
#
# 少送一次，job_manager 的 pump thread 會永遠停在 queue.get()、分析 slot
# 永遠不釋放，之後每一支影片都卡在 queued（見 _analyze_worker() 的說明）。
# ----------------------------------------------------------------------


def test_analyze_worker_emits_error_event_when_client_creation_fails(monkeypatch):
    """`get_client()` 失敗（例如缺 API 金鑰）發生在內層 try 之前，最外層必須
    接住並送出 AnalysisError。"""
    monkeypatch.setattr(analyzer.db, "get_video", lambda vid: MagicMock(
        file_path="/dev/null", duration_sec=10, title="測試影片", pipeline_stage=None))
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer, "get_client", MagicMock(side_effect=RuntimeError("沒有 API 金鑰")))

    q: queue.Queue = queue.Queue()
    analyzer._analyze_worker(1, q)

    events = _drain(q)
    assert any(isinstance(e, analyzer.AnalysisError) for e in events), "必須送出終端事件"
    assert "沒有 API 金鑰" in events[-1].message


def test_analyze_worker_emits_error_event_when_reading_the_video_record_fails(monkeypatch):
    """連讀取影片紀錄都失敗（資料庫鎖死／損毀）一樣要送出終端事件。"""
    monkeypatch.setattr(analyzer.db, "get_video", MagicMock(side_effect=RuntimeError("database is locked")))
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())

    q: queue.Queue = queue.Queue()
    analyzer._analyze_worker(1, q)

    events = _drain(q)
    assert len(events) == 1
    assert isinstance(events[0], analyzer.AnalysisError)
    assert "database is locked" in events[0].message


def test_analyze_worker_still_emits_error_event_when_marking_failed_also_fails(monkeypatch):
    """連「標記失敗」都寫不進資料庫時，仍然要送出終端事件——這是 slot 能不能
    釋放的唯一依據，不能因為資料庫壞掉就一起放棄。"""
    monkeypatch.setattr(analyzer.db, "get_video", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock(side_effect=RuntimeError("也寫不進去")))

    q: queue.Queue = queue.Queue()
    analyzer._analyze_worker(1, q)

    events = _drain(q)
    assert len(events) == 1
    assert isinstance(events[0], analyzer.AnalysisError)


def test_analyze_worker_emits_exactly_one_terminal_event_on_normal_failure(monkeypatch):
    """內層 except 已經處理過的一般失敗，不能因為多包了一層而送出兩個終端事件。"""
    monkeypatch.setattr(analyzer.db, "get_video", lambda vid: MagicMock(
        file_path="/dev/null", duration_sec=10, title="測試影片", pipeline_stage="場景切分中"))
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer, "get_client", lambda: MagicMock())
    monkeypatch.setattr(analyzer, "_run_scene_detection_and_transcription",
                        MagicMock(side_effect=RuntimeError("場景切分爆炸")))

    q: queue.Queue = queue.Queue()
    analyzer._analyze_worker(1, q)

    terminal = [e for e in _drain(q) if isinstance(e, (analyzer.AnalysisError, analyzer.AnalysisResult))]
    assert len(terminal) == 1
    assert "場景切分爆炸" in terminal[0].message


def _drain(q: queue.Queue) -> list:
    items = []
    while not q.empty():
        items.append(q.get())
    return items


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


def test_run_local_ocr_and_document_combines_costs_without_double_counting(monkeypatch):
    """Phase E／F 都要用「進入這個函式那一刻」的 total_cost 當基準，不是
    「E 跑完後」的金額——最終合計不能重複計算或漏算任一邊的花費。"""
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())

    def fake_run_local_ocr(ctx, segment_rows, segment_ids):
        assert ctx.total_cost == 0.05  # 收到的是基準值，不是「循序版本」會有的其他數字
        ctx.spend(0.02)

    def fake_run_document_phase(ctx):
        assert ctx.total_cost == 0.05  # 用「本地 OCR 開始前」的金額判斷，不是 OCR 跑完後
        ctx.spend(0.03)
        return analyzer._DocumentPhaseOutput(summary="摘要文字")

    monkeypatch.setattr(analyzer, "_run_local_ocr", fake_run_local_ocr)
    monkeypatch.setattr(analyzer, "_run_document_phase", fake_run_document_phase)

    ctx = _context(initial_cost=0.05)
    output = analyzer._run_local_ocr_and_document(ctx, [], [])

    assert output.summary == "摘要文字"
    assert round(ctx.total_cost, 10) == 0.10  # 0.05（基準）+ 0.02（OCR）+ 0.03（文件）


def test_run_local_ocr_and_document_isolates_local_ocr_failure(monkeypatch):
    """本地 OCR 那個子執行緒丟例外時，只記 log、不能影響文件整理照常執行，
    也不能讓例外冒出這個函式（延續既有的失敗隔離原則）。"""
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())

    def fake_run_local_ocr(ctx, segment_rows, segment_ids):
        raise RuntimeError("本地 OCR 掛了")

    def fake_run_document_phase(ctx):
        ctx.spend(0.03)
        return analyzer._DocumentPhaseOutput(summary="摘要照常產生")

    monkeypatch.setattr(analyzer, "_run_local_ocr", fake_run_local_ocr)
    monkeypatch.setattr(analyzer, "_run_document_phase", fake_run_document_phase)

    ctx = _context(initial_cost=0.05)
    output = analyzer._run_local_ocr_and_document(ctx, [], [])

    assert output.summary == "摘要照常產生"
    # 本地 OCR 失敗沒有貢獻花費，總花費只有基準值 + 文件花費
    assert round(ctx.total_cost, 10) == 0.08


def _stub_document_phase_deps(monkeypatch, segments=("片段",)):
    """Phase F 測試的共同前置：enter_stage 寫 DB 換成 mock，片段清單給假的。"""
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer.db, "list_segments_for_video", lambda video_id: list(segments))


def test_document_phase_reuses_the_document_overview_as_the_summary(monkeypatch):
    """Phase F 主線：文件成功時五個欄位一次備齊，摘要就是文件的 overview
    （一稿兩用，跟手動整理文件那條路一致），花費記進 ctx。"""
    _stub_document_phase_deps(monkeypatch)
    fake_document = SimpleNamespace(
        doc_type="sop",
        overview="這支影片在講主板產線。",
        model_dump_json=lambda: '{"doc_type":"sop"}',
    )
    monkeypatch.setattr(
        analyzer.document_pipeline, "generate_document",
        lambda client, title, segments: SimpleNamespace(document=fake_document, cost_usd=0.002),
    )

    ctx = _context()
    output = analyzer._run_document_phase(ctx)

    assert output.summary == "這支影片在講主板產線。"
    assert output.summary_model == analyzer.document_pipeline.MODEL_NAME
    assert output.document_json == '{"doc_type":"sop"}'
    assert output.document_type == "sop"
    assert output.document_model == analyzer.document_pipeline.MODEL_NAME
    assert ctx.total_cost == pytest.approx(0.002)


def test_document_phase_passes_the_video_title_from_the_context(monkeypatch):
    """文件的 prompt 需要影片標題，它從 ctx 來（不是某個 phase 算出來的）。"""
    _stub_document_phase_deps(monkeypatch)
    seen: dict[str, object] = {}

    def fake_generate_document(client, title, segments):
        seen["title"] = title
        return SimpleNamespace(
            document=SimpleNamespace(doc_type="sop", overview="o", model_dump_json=lambda: "{}"),
            cost_usd=0.0,
        )

    monkeypatch.setattr(analyzer.document_pipeline, "generate_document", fake_generate_document)

    analyzer._run_document_phase(_context())

    assert seen["title"] == "測試影片"


def test_document_phase_falls_back_to_summary_when_the_document_fails(monkeypatch):
    """文件失敗不能讓影片整支沒有摘要——`videos.summary` 是搜尋的影片層級篩選
    與影片庫分類的依據，沒有它那支影片會被降權。"""
    _stub_document_phase_deps(monkeypatch)
    monkeypatch.setattr(
        analyzer.document_pipeline, "generate_document",
        MagicMock(side_effect=ValueError("模型沒有回傳可用的文件內容")),
    )
    monkeypatch.setattr(
        analyzer.summary_pipeline, "generate_summary",
        lambda client, segments: SimpleNamespace(summary="退路摘要", cost_usd=0.0004),
    )

    ctx = _context()
    output = analyzer._run_document_phase(ctx)

    assert output.summary == "退路摘要"
    assert output.summary_model == analyzer.summary_pipeline.MODEL_NAME
    # 文件那三欄留空，mark_video_analyzed() 的 COALESCE 才會保留影片上原本的文件
    assert (output.document_json, output.document_type, output.document_model) == (None, None, None)
    assert ctx.total_cost == pytest.approx(0.0004)


def test_document_phase_returns_empty_when_both_paths_fail(monkeypatch):
    """兩條路都失敗只記 log，不能讓例外冒出去把已經成功的分析結果判成失敗。"""
    _stub_document_phase_deps(monkeypatch)
    monkeypatch.setattr(
        analyzer.document_pipeline, "generate_document", MagicMock(side_effect=RuntimeError("文件掛了")),
    )
    monkeypatch.setattr(
        analyzer.summary_pipeline, "generate_summary", MagicMock(side_effect=RuntimeError("摘要也掛了")),
    )

    output = analyzer._run_document_phase(_context())

    assert output == analyzer._DocumentPhaseOutput()


def test_document_phase_skips_everything_when_over_budget(monkeypatch):
    """超支就整段跳過，兩條路都不能花錢（維持這個 phase 原本的行為）。"""
    _stub_document_phase_deps(monkeypatch)
    generate_document = MagicMock()
    generate_summary = MagicMock()
    monkeypatch.setattr(analyzer.document_pipeline, "generate_document", generate_document)
    monkeypatch.setattr(analyzer.summary_pipeline, "generate_summary", generate_summary)

    output = analyzer._run_document_phase(_context(initial_cost=analyzer.BUDGET_USD + 0.01))

    assert output == analyzer._DocumentPhaseOutput()
    generate_document.assert_not_called()
    generate_summary.assert_not_called()


def test_document_phase_skips_when_there_are_no_segments(monkeypatch):
    _stub_document_phase_deps(monkeypatch, segments=())
    generate_document = MagicMock()
    monkeypatch.setattr(analyzer.document_pipeline, "generate_document", generate_document)

    assert analyzer._run_document_phase(_context()) == analyzer._DocumentPhaseOutput()
    generate_document.assert_not_called()


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


def test_run_scene_detection_and_transcription_scene_error_wins_when_both_fail(monkeypatch):
    """兩邊同時失敗時，往外傳的必須是場景切分的例外——轉錄的例外不能蓋掉它，
    不然使用者看到的失敗原因會是錯的。轉錄執行緒一樣要等它跑完才離開。"""
    transcription_completed = {"done": False}

    def fake_run_scene_detection(ctx, duration_sec):
        raise RuntimeError("場景切分失敗")

    def fake_run_transcription(ctx, duration_sec):
        time.sleep(0.05)
        transcription_completed["done"] = True
        raise RuntimeError("轉錄也失敗")

    monkeypatch.setattr(analyzer, "_run_scene_detection", fake_run_scene_detection)
    monkeypatch.setattr(analyzer, "_run_transcription", fake_run_transcription)

    try:
        analyzer._run_scene_detection_and_transcription(_context(), 10.0)
        raise AssertionError("應該要拋出例外")
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

    # 字幕要給真的內容：空的轉錄結果現在代表「純畫面影片」，會讓每個場景都走
    # 三幀那條路（見 _is_visual_only()），測不到這裡要測的兩幀觸發。
    transcribe_result = MagicMock(segments=[MagicMock(text=f"第 {i} 句") for i in range(10)])
    scene_rows, _ = analyzer._run_vlm_phase(_context(), scenes, transcribe_result)

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


# ----------------------------------------------------------------------
# 純畫面影片：沒有音軌就跳過 ASR，字幕整欄沒用就加密畫面取樣
# 見 docs/02-technical-decisions.md「純畫面影片：跳過 ASR，把預算換成畫面」
# ----------------------------------------------------------------------


def _transcribe_result(*texts: str) -> MagicMock:
    return MagicMock(segments=[MagicMock(text=t) for t in texts])


def test_is_visual_only_when_there_is_no_transcript_at_all():
    """真無聲的影片轉錄結果是空的。這一條不能只委派給
    segment_material.is_transcript_column_junk()——它的樣本數下限是 8 句，
    空清單會回 False，最該加密取樣的影片反而拿不到多幀。"""
    assert analyzer._is_visual_only(_transcribe_result()) is True


def test_is_visual_only_when_transcript_is_only_whitespace():
    assert analyzer._is_visual_only(_transcribe_result("", "   ", "")) is True


def test_is_visual_only_when_the_whole_column_is_hallucinated():
    # BMW 那支的形狀：97 句裡 95 句一字不差
    result = _transcribe_result(*(["Thank you for watching."] * 9 + ["真的內容"]))
    assert analyzer._is_visual_only(result) is True


def test_not_visual_only_for_real_speech():
    assert analyzer._is_visual_only(_transcribe_result(*[f"第 {i} 句" for i in range(10)])) is False


def test_frame_fractions_for_visual_only_overrides_single_frame():
    scene = NormalizedScene(0.0, 10.0, source_raw_duration=10.0)
    assert analyzer._frame_fractions_for(scene, visual_only=True) == analyzer.VISUAL_ONLY_FRAME_FRACTIONS


def test_frame_fractions_for_visual_only_also_overrides_the_two_frame_trigger():
    """兩個條件同時成立時走三幀那條——三幀本來就比兩幀密，不需要再分岔。"""
    scene = NormalizedScene(20.0, 30.0, source_raw_duration=analyzer.MULTI_FRAME_TRIGGER_SEC + 0.1)
    assert analyzer._frame_fractions_for(scene, visual_only=True) == analyzer.VISUAL_ONLY_FRAME_FRACTIONS


def test_run_transcription_skips_whisper_when_there_is_no_audio_stream(monkeypatch):
    """沒有音軌就不呼叫 Whisper：省下實測佔總成本 62～66% 的那筆錢，也避免
    ffmpeg 抽音訊失敗讓整支分析失敗。"""
    monkeypatch.setattr(analyzer.media, "has_audio_stream", lambda path: False)
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())

    called = MagicMock()
    monkeypatch.setattr(analyzer.asr, "transcribe_with_progress", called)

    ctx = _context()
    result = analyzer._run_transcription(ctx, duration_sec=600.0)

    called.assert_not_called()
    assert result.segments == []
    assert result.cost_usd == 0.0
    assert ctx.total_cost == 0.0


def test_run_vlm_phase_uses_three_frames_when_the_transcript_is_unusable(monkeypatch):
    """字幕整欄沒用時，每個場景都要收到 VISUAL_ONLY_FRAME_FRACTIONS——包括
    原本只會拿單幀的場景。驗證判斷結果真的往下傳給 VLM 呼叫。"""
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
        NormalizedScene(0.0, 10.0, source_raw_duration=10.0),   # 原本單幀
        NormalizedScene(10.0, 20.0, source_raw_duration=40.0),  # 原本兩幀
    ]
    scene_rows, _ = analyzer._run_vlm_phase(_context(), scenes, _transcribe_result())

    assert received_fractions == [analyzer.VISUAL_ONLY_FRAME_FRACTIONS] * 2
    assert [row.frame_count for row in scene_rows] == [3, 3]


def test_run_vlm_phase_shrinks_the_batch_for_visual_only_videos(monkeypatch):
    """純畫面影片每個場景要抽三幀，批次不縮的話同一批會送出 3×3＝9 張圖——
    實測 v28 就是這樣撞了 5 次 429。撞 rate limit 的是圖片張數不是場景數，
    所以批次要跟著幀數走。"""
    monkeypatch.setattr(analyzer.db, "update_video_status", MagicMock())
    monkeypatch.setattr(analyzer.asr, "text_for_range", lambda segments, s, e: "")
    monkeypatch.setattr(analyzer.asr, "scores_for_range", lambda segments, s, e: _NO_SCORES)

    max_workers_seen: list[int] = []
    real_pool = analyzer.ThreadPoolExecutor

    def spy_pool(max_workers):
        max_workers_seen.append(max_workers)
        return real_pool(max_workers=max_workers)

    monkeypatch.setattr(analyzer, "ThreadPoolExecutor", spy_pool)
    monkeypatch.setattr(
        analyzer, "_describe_segment_with_retry",
        lambda c, p, s, e, f: DescribeResult("d", None, 0.0, len(f)),
    )

    scenes = [NormalizedScene(i * 10.0, i * 10.0 + 10.0, source_raw_duration=10.0) for i in range(4)]

    analyzer._run_vlm_phase(_context(), scenes, _transcribe_result())
    assert max_workers_seen == [analyzer.VISUAL_ONLY_VLM_BATCH_SIZE]

    max_workers_seen.clear()
    analyzer._run_vlm_phase(_context(), scenes, _transcribe_result(*[f"第 {i} 句" for i in range(10)]))
    assert max_workers_seen == [analyzer.VLM_BATCH_SIZE]
