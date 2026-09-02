"""六個 phase 與它們的常數、中間資料列。

Phase A（場景切分）／音訊轉錄 → Phase B（VLM 畫面分析）→ Phase C（建立向量）
→ Phase D（寫入 segments）→ Phase E（本地 OCR）∥ Phase F（整理文件與摘要）。
每個 phase 只收 `ctx` 加上自己真正需要的參數，不互相呼叫（唯二的例外是刻意
平行的那兩組：`_run_scene_detection_and_transcription()` 與
`_run_local_ocr_and_document()`）。

只依賴 context 與 events，不認識 worker——流程的順序由 worker 決定。
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI, RateLimitError

from ... import db
from .. import asr, embedding, media, ocr_service, scene_detect, vlm
from .. import document as document_pipeline
from .. import summary as summary_pipeline
from .context import _AnalysisContext

logger = logging.getLogger(__name__)

# **每個片段一律抽三張畫面**，位置在 10%／40%／70%（2026-08-31，P4）。
#
# 之前是三層：預設中點單幀、場景切分完全沒抓到切點時兩幀（門檻 20 秒）、字幕整欄
# 沒用時三幀。統一成三幀之後那兩個觸發條件就不再決定任何事，連同判斷邏輯與常數一起
# 刪掉——留著不會被讀到的分支，比少一個設定選項更糟。
#
# **理由是「單幀片段的瓶頸是那張畫面本身」**：改 prompt 在多幀上拿到 +21.4pt 的具體
# 動作描述率，在單幀上怎麼改都只有個位數、而且落在雜訊內。一張靜止畫面看不出動作的
# 方向（彎腰扶著箱子，可能是搬起、放下或只是扶著），那是資訊本身不存在，不是措辭
# 問題。見 docs/02-technical-decisions.md#單幀-prompt問姿勢不要問動作。
#
# 三幀是**目前唯一實測過的最高密度**（v28／v36 各跑過一次完整分析）。再往上是未量測
# 領域，而且已知元描述率會隨幀數上升（兩幀 4.3% → 三幀 16.8~28%，已判定是表面瑕疵，
# 見 docs/18-畫面分析精細化計畫.md）。
#
# 位置 10%／40%／70% 由使用者指定。間距跟先前的 20%／50%／80% 同樣是 30%，差別只在
# 整體往前移 10%——**盲區因此落在每個片段的最後 30%**，而不是像對稱取樣那樣分散在
# 頭尾；跨片段來看兩者的縫隙一樣大（下一段的第一個探測點緊接在後）。
FRAME_FRACTIONS = (0.1, 0.4, 0.7)

# Phase B 批次平行的批次大小。**撞 rate limit 的是同一批送出的圖片張數，不是場景
# 數**——每個場景現在固定三幀，批次 2 等於每批 6 張，跟條件式多幀上線時驗證過
# （0 次撞限）的用量同級。實測逼出來的：v28 用批次 3 跑（3×3＝9 張）時 429 撞了
# 5 次，靠重試救回來、107 個場景全數完成 0 失敗，但那是靠運氣不是靠設計。
#
# 舊註解（batch_size=5／3 時期的推導依據，已知有誤，保留供對照）：原本用 gpt-4o-mini
# 的 TPM 上限（200,000/分鐘）回推，但假設「low」解析度圖片固定 85 tokens（那是一般
# gpt-4o 的公式），實測單幀呼叫真實 prompt tokens 是 2,960（圖片就佔約 2,880），高了
# 一個數量級。這個落差沒有造成實際問題，研判是真實 API 呼叫的延遲本身就有節流效果，
# 不是 token 預算公式在把關。
VLM_BATCH_SIZE = 2

# 批次平行後同一批內同時打多個請求，撞到 429 的機率比循序執行時更高；
# 帳號已經實測撞過 TPM 上限，這裡的等待秒數／重試次數是合理預設，不是
# 實測校準值。
VLM_RATE_LIMIT_MAX_RETRIES = 2
VLM_RATE_LIMIT_RETRY_WAIT_SEC = 8.0


@dataclass
class _SceneAnalysisRow:
    """Phase B（VLM 逐片段畫面分析）單一場景的輸出，Phase C（建立向量）逐筆
    處理。用具名 dataclass、一個場景一筆，不是好幾個平行陣列——避免「新增一
    個欄位要同步改宣告／Phase B 的 append／Phase C 的 zip 解構三處，任一處
    漏改都是不會報錯但資料錯位」的風險，跟 _SegmentRow 採用同一個理由。
    """
    start_sec: float
    end_sec: float
    transcript_text: str
    description: str
    ocr_text: str | None
    scores: asr.SegmentScores
    frame_count: int  # 這個片段的畫面描述用了幾張畫面（1=單幀，2=條件式多幀）


@dataclass
class _SegmentRow:
    """Phase C（建立向量）的輸出，Phase D（`_write_segments()`，寫入 segments 表）
    與 Phase E（`_run_local_ocr()`，判斷哪些場景還缺 OCR 文字）逐一讀取；用
    具名 dataclass 取代先前的無型別 9-tuple，避免位置索引（例如本地 OCR 用來
    判斷要不要複掃的欄位）失去意義、欄位順序一改就悄悄壞掉不會有型別檢查提醒。
    """
    start_sec: float
    end_sec: float
    transcript_text: str
    description: str
    ocr_text: str | None
    transcript_embedding: bytes | None
    visual_embedding: bytes | None
    ocr_embedding: bytes | None
    scores: asr.SegmentScores
    frame_count: int


def _run_scene_detection(ctx: _AnalysisContext, duration_sec: float) -> list[scene_detect.NormalizedScene]:
    """Phase A：場景切分。"""

    def _on_scene_progress(percent: int) -> None:
        ctx.report_progress("場景切分中", f"{percent}%（預估）")

    return scene_detect.detect_scenes_with_progress(
        ctx.video_path, duration_sec, on_progress=_on_scene_progress
    )


def _run_transcription(ctx: _AnalysisContext, duration_sec: float) -> asr.TranscribeResult:
    """整支影片的音訊轉錄（原本無獨立 Phase 字母，緊接在 Phase A 場景切分之後、
    Phase B 逐片段畫面分析之前）。花費直接記進 ctx。

    **沒有音軌就整段跳過**，回一個空的結果。兩個理由：
    - Whisper 按分鐘計價、跟畫面複雜度無關，實測佔一支影片總成本的 **62～66%**
      （18.6 分鐘的 Intel 那支：總計 US$0.1711，其中 ASR US$0.1116）。對一支沒有
      聲音的影片，這筆錢買到的只有幻覺。
    - `asr._extract_audio()` 對沒有音軌的檔案會讓 ffmpeg 失敗，而 ASR 例外會讓
      **整支分析失敗**（不是略過字幕）。所以這道檢查同時修掉「純畫面影片根本分析
      不完」這個既有的洞。
    """
    if not media.has_audio_stream(ctx.video_path):
        ctx.enter_stage("沒有音軌，略過音訊轉錄")
        return asr.TranscribeResult(segments=[], cost_usd=0.0)

    ctx.enter_stage("音訊轉錄中")

    def _on_transcribe_progress(percent: int) -> None:
        ctx.report_progress("音訊轉錄中", f"{percent}%（預估）")

    transcribe_result = asr.transcribe_with_progress(
        ctx.client, ctx.video_path, duration_sec, on_progress=_on_transcribe_progress
    )
    ctx.spend(transcribe_result.cost_usd)
    ctx.enter_stage("音訊轉錄完成")

    return transcribe_result


def _run_scene_detection_and_transcription(
    ctx: _AnalysisContext, duration_sec: float
) -> tuple[list[scene_detect.NormalizedScene], asr.TranscribeResult]:
    """Phase A（場景切分）跟音訊轉錄互不依賴——一個看畫面、一個聽聲音，改成
    同時起跑縮短總耗時；`_run_scene_detection()`／`_run_transcription()` 本身
    不動，只是呼叫順序從循序改成併發，見
    docs/02-technical-decisions.md#分析流程平行化。
    """
    with ThreadPoolExecutor(max_workers=1) as pool:
        transcribe_future = pool.submit(_run_transcription, ctx, duration_sec)
        # 場景切分萬一拋例外，離開這個 with 區塊時 executor 的
        # shutdown(wait=True) 仍然會等轉錄跑完——不會留下一個脫離這個函式
        # 生命週期、還在背景花錢的 API 呼叫。
        scenes = _run_scene_detection(ctx, duration_sec)

    # 取轉錄結果刻意排在場景切分「之後」而且不放進 finally：場景切分失敗時
    # 例外會在上一行就往外拋，根本不會走到這裡，往外傳的因此一定是場景切分
    # 自己的例外。放進 finally 的話，轉錄如果也失敗就會反過來蓋掉它，使用者
    # 看到的失敗原因會是錯的（有測試鎖住這個情況）。
    return scenes, transcribe_future.result()


def _run_vlm_phase(
    ctx: _AnalysisContext,
    scenes: list[scene_detect.NormalizedScene],
    transcribe_result: asr.TranscribeResult,
) -> tuple[list[_SceneAnalysisRow], int]:
    """Phase B：逐片段畫面分析（VLM，成本主要來源）。場景分批平行送出縮短耗時
    （Tier 2 平行化，見 docs/02-technical-decisions.md#分析流程平行化）：同一批
    內用 thread pool 並發呼叫，用「送出順序」收集結果（不是完成順序），確保
    回傳的 list[_SceneAnalysisRow] 順序仍然精確對應 scenes 的順序；budget
    檢查從「每個場景後」放寬成「每個批次後」。

    每個場景一律抽 `FRAME_FRACTIONS` 三張畫面，沒有條件判斷——理由與演進見那個常數
    上方的說明。

    單一場景的 VLM 呼叫失敗（內容審查拒絕、API 錯誤等 rate limit 以外的例外）
    只跳過那個場景的畫面描述／OCR，不讓整支分析失敗，比照 Phase E／F 的失敗
    隔離原則；字幕不受影響，因為是從已經抓好的逐字稿本機切出來的，跟 VLM
    呼叫成不成功無關。失敗場景數用回傳值 vlm_failed_count 往外傳，讓呼叫端
    可以把這個原因獨立顯示給使用者，不能跟預算截斷共用同一個訊息（見
    docs/00-overview.md#33-整體資料流）。失敗場景的 cost_usd 一律算 0——內容審查
    拒絕的呼叫實務上可能還是有算到一點輸入 token 費用，但例外是在讀到
    response.usage 之前就被拋出，程式拿不到那個數字，這是已知、暫不處理的
    誤差；失敗場景的 frame_count 記 0（沒有任何畫面真的產生描述）。
    """
    scene_rows: list[_SceneAnalysisRow] = []
    vlm_failed_count = 0

    completed = 0

    def _report_progress() -> None:
        nonlocal completed
        completed += 1
        percent = round(completed / len(scenes) * 100)
        ctx.report_progress("畫面分析", f"{percent}%", persist_as=f"畫面分析 {percent}%")

    with ThreadPoolExecutor(max_workers=VLM_BATCH_SIZE) as pool:
        for batch_start in range(0, len(scenes), VLM_BATCH_SIZE):
            batch = scenes[batch_start : batch_start + VLM_BATCH_SIZE]
            futures = [
                pool.submit(
                    _describe_segment_with_retry,
                    ctx.client, ctx.video_path, scene.start_sec, scene.end_sec, FRAME_FRACTIONS,
                )
                for scene in batch
            ]

            for scene, future in zip(batch, futures):
                start_sec, end_sec = scene.start_sec, scene.end_sec
                try:
                    describe_result = future.result()
                except Exception:
                    logger.warning(
                        "VLM 畫面分析失敗，跳過這個場景（%.1fs~%.1fs），保留字幕、不產生畫面描述",
                        start_sec, end_sec, exc_info=True,
                    )
                    describe_result = None
                    vlm_failed_count += 1

                _report_progress()

                if describe_result is not None:
                    ctx.spend(describe_result.cost_usd)
                scene_rows.append(
                    _SceneAnalysisRow(
                        start_sec=start_sec,
                        end_sec=end_sec,
                        transcript_text=asr.text_for_range(transcribe_result.segments, start_sec, end_sec),
                        description=describe_result.description if describe_result else "",
                        ocr_text=describe_result.ocr_text if describe_result else None,
                        scores=asr.scores_for_range(transcribe_result.segments, start_sec, end_sec),
                        frame_count=describe_result.frame_count if describe_result else 0,
                    )
                )

            if ctx.over_budget:
                break

    return scene_rows, vlm_failed_count


def _describe_segment_with_retry(
    client: OpenAI, video_path: Path, start_sec: float, end_sec: float, frame_fractions: tuple[float, ...]
) -> vlm.DescribeResult:
    """包一層 rate limit 重試。批次平行送出後，同一批內同時打多個請求，撞到
    OpenAI 429（gpt-4o-mini TPM 上限）的機率比循序執行時更高——帳號實測撞過
    這個上限（見 docs/02-technical-decisions.md#分析流程平行化「Tier 2」），
    這裡補上重試，不然平行化反而會讓整支影片分析比現在更容易失敗。非
    rate-limit 的例外不重試，直接往外拋，維持跟現有版本一樣的失敗語意。
    """
    attempt = 0
    while True:
        try:
            return vlm.describe_segment(client, video_path, start_sec, end_sec, frame_fractions)
        except RateLimitError:
            attempt += 1
            if attempt > VLM_RATE_LIMIT_MAX_RETRIES:
                raise
            logger.warning(
                "VLM 呼叫撞到 rate limit，%.0f 秒後重試（第 %d/%d 次）",
                VLM_RATE_LIMIT_RETRY_WAIT_SEC, attempt, VLM_RATE_LIMIT_MAX_RETRIES,
            )
            time.sleep(VLM_RATE_LIMIT_RETRY_WAIT_SEC)


def _run_embedding_phase(ctx: _AnalysisContext, scene_rows: list[_SceneAnalysisRow]) -> list[_SegmentRow]:
    """Phase C：建立向量（字幕、畫面描述、OCR 文字分開 embed）。同一片段內的三個
    embedding 互相獨立，用 thread pool 平行送出縮短耗時；片段仍然照原順序一個一個
    處理，budget 檢查時機（一個片段的三個 embedding 都做完才檢查一次）不變，見
    docs/02-technical-decisions.md#分析流程平行化。

    字幕疑似是幻覺時不建立字幕 embedding，避免污染搜尋；`segments.transcript`
    仍然照實際 Whisper 輸出寫入，不隱藏原始內容，只是不讓它可被搜尋到，見
    docs/02-technical-decisions.md#asrwhisper-幻覺字幕過濾。兩種互補的判斷：模式 A
    （asr.is_hallucinated_transcript()，no_speech_prob 偏高）逐場景判斷；
    模式 B（asr.find_repetitive_transcript_indices()，連續場景被同一個詞
    主導）跨場景判斷，要先對整支影片的字幕算一次。
    """
    ctx.enter_stage("建立向量中")

    repetitive_indices = asr.find_repetitive_transcript_indices(
        [row.transcript_text for row in scene_rows]
    )

    segment_rows: list[_SegmentRow] = []
    for index, row in enumerate(scene_rows):
        is_hallucinated = asr.is_hallucinated_transcript(row.scores) or index in repetitive_indices
        transcript_for_embedding = row.transcript_text if row.transcript_text and not is_hallucinated else None
        embed_results = _embed_segment_texts(
            ctx.client, transcript=transcript_for_embedding, visual=row.description, ocr=row.ocr_text
        )

        # 三個模態的處理完全一樣（累加花費＋編碼成 bytes），照固定順序跑一次
        # 迴圈；沒有 embed 到的模態就不會出現在 blobs 裡，取值是 None。
        blobs: dict[str, bytes] = {}
        for kind in ("transcript", "visual", "ocr"):
            embed_result = embed_results.get(kind)
            if embed_result is None:
                continue
            ctx.spend(embed_result.cost_usd)
            blobs[kind] = embedding.encode_embedding(embed_result.vector)

        segment_rows.append(
            _SegmentRow(
                start_sec=row.start_sec,
                end_sec=row.end_sec,
                transcript_text=row.transcript_text,
                description=row.description,
                ocr_text=row.ocr_text,
                transcript_embedding=blobs.get("transcript"),
                visual_embedding=blobs.get("visual"),
                ocr_embedding=blobs.get("ocr"),
                scores=row.scores,
                frame_count=row.frame_count,
            )
        )

        if ctx.over_budget:
            break

    return segment_rows


def _embed_segment_texts(
    client: OpenAI, *, transcript: str | None, visual: str | None, ocr: str | None
) -> dict[str, embedding.EmbedResult]:
    """把一個片段裡存在的文字（字幕／畫面描述／OCR）平行送出 embedding 呼叫，
    回傳 {種類: EmbedResult}；呼叫端逐一累加花費，跟循序呼叫的結果完全一樣，
    只是三個獨立的網路呼叫改成同時發生。"""
    texts = {kind: text for kind, text in (("transcript", transcript), ("visual", visual), ("ocr", ocr)) if text}
    if not texts:
        return {}
    if len(texts) == 1:
        kind, text = next(iter(texts.items()))
        return {kind: embedding.embed_text(client, text)}

    with ThreadPoolExecutor(max_workers=len(texts)) as pool:
        futures = {kind: pool.submit(embedding.embed_text, client, text) for kind, text in texts.items()}
        return {kind: future.result() for kind, future in futures.items()}


def _write_segments(ctx: _AnalysisContext, segment_rows: list[_SegmentRow]) -> list[int]:
    """Phase D：把所有片段一次寫入 segments 表，回傳依序對應的 segment_id 清單。

    寫入前先清掉這支影片既有的片段。第一次分析時是沒有作用的 no-op；重新分析
    時它是「換掉舊索引」的那一刻——舊片段刻意留到這裡才刪，影片在重新分析的
    整段期間都還搜得到舊結果，而不是變成一支查不到東西的空殼。

    刪除與後面的 insert 不在同一個交易裡（`insert_segment()` 逐筆各自開連線），
    中間那個空窗只有寫入索引這幾百毫秒。真的在這中間爆掉的話，影片會被標記成
    failed、片段殘缺，跟既有的分析中途失敗是同一種結果，一樣靠重新分析復原。
    """
    ctx.enter_stage("寫入索引")
    db.clear_analysis_output(ctx.video_id)

    segment_ids: list[int] = []
    for row in segment_rows:
        segment_id = db.insert_segment(
            video_id=ctx.video_id,
            start_sec=row.start_sec,
            end_sec=row.end_sec,
            transcript=row.transcript_text or None,
            visual_description=row.description or None,
            ocr_text=row.ocr_text,
            transcript_embedding=row.transcript_embedding,
            visual_embedding=row.visual_embedding,
            ocr_embedding=row.ocr_embedding,
            asr_model=asr.MODEL_NAME,
            vlm_model=vlm.MODEL_NAME,
            embedding_model=embedding.MODEL_NAME,
            no_speech_prob=row.scores.no_speech_prob,
            avg_logprob=row.scores.avg_logprob,
            compression_ratio=row.scores.compression_ratio,
            vlm_frame_count=row.frame_count,
        )
        segment_ids.append(segment_id)
    return segment_ids


def _run_local_ocr(
    ctx: _AnalysisContext, segment_rows: list[_SegmentRow], segment_ids: list[int]
) -> None:
    """跑本地 OCR 掃描並把結果 embed、寫入 ocr_events；花費記進 ctx。
    只掃描 VLM-OCR 沒抓到文字的場景（segment_rows 的 ocr_text 為空）——本地 OCR
    的目的是補 VLM 單幀取樣漏掉的文字，不是重複掃描 VLM 已經找到文字的場景；
    用真實影片校準過，多數影片 VLM 已覆蓋 98~100% 場景，全面依序掃描只會把
    60 秒時間預算耗在早就有答案的前幾個場景上，反而讓真正需要補的場景完全
    沒被掃到（取樣策略的除錯過程見 docs/02-technical-decisions.md#vlm-與-ocr，
    尚未校準的參數見 docs/05-known-limitations-and-open-items.md）。
    本地辨識本身免費，但 embedding 是真的 OpenAI 呼叫，一樣受 BUDGET_USD 節制，
    避免本地 OCR 找到大量文字時不受控地把預算榨乾。
    """
    scenes_with_segment_id = [
        (row.start_sec, row.end_sec, segment_id)
        for row, segment_id in zip(segment_rows, segment_ids)
        if not row.ocr_text  # VLM-OCR 已經有文字的場景不用本地 OCR 複掃
    ]
    if not scenes_with_segment_id:
        return

    def _on_ocr_progress(percent: int) -> None:
        ctx.report_progress("本地 OCR 掃描中", f"{percent}%")

    ocr_events = ocr_service.scan_scenes(
        ctx.video_id, ctx.video_path, scenes_with_segment_id, on_progress=_on_ocr_progress
    )

    for event in ocr_events:
        if ctx.over_budget:
            break
        embed_result = embedding.embed_text(ctx.client, event.resolved_text)
        ctx.spend(embed_result.cost_usd)
        db.insert_ocr_event(
            video_id=event.video_id,
            segment_id=event.segment_id,
            start_sec=event.start_sec,
            end_sec=event.end_sec,
            frame_sec=event.frame_sec,
            raw_text=event.raw_text,
            resolved_text=event.resolved_text,
            confidence=event.confidence,
            bbox=json.dumps(event.bbox) if event.bbox else None,
            primary_engine=event.primary_engine,
            ocr_pipeline_version=ocr_service.PIPELINE_VERSION,
            embedding=embedding.encode_embedding(embed_result.vector),
        )


@dataclass
class _DocumentPhaseOutput:
    """Phase F 的產出，直接對應 `db.mark_video_analyzed()` 的五個可選欄位。

    全部是 None ＝這個 phase 什麼都沒產出（超支、沒有片段，或兩條路都失敗）；
    那種情況下 `mark_video_analyzed()` 的 COALESCE 會保留影片上原本的值。
    """
    summary: str | None = None
    summary_model: str | None = None
    document_json: str | None = None
    document_type: str | None = None
    document_model: str | None = None


def _run_document_phase(ctx: _AnalysisContext) -> _DocumentPhaseOutput:
    """Phase F：把全部片段整理成一份結構化文件，順便拿到摘要。

    **文件優先、摘要當退路**。原本這個 phase 只產摘要（`summary.generate_summary()`），
    文件要使用者自己去按「整理成文件」。兩者其實是同一件事的兩種輸出——
    `VideoDocument.overview` 的 prompt 就是照摘要的規格寫的，手動整理文件時本來
    就會一併覆蓋 `videos.summary`（見 `services/video_service.generate_document()`）
    ——所以這裡直接產文件，摘要當成它的副產品，省掉一次 LLM 呼叫。

    退路不能省：`videos.summary` 不只是顯示用的欄位，搜尋的影片層級篩選
    （pipeline/search/dense.py）與影片庫的主題分類（frontend lib/videoCategory.ts）
    都在讀它。文件整理失敗就整支沒有摘要的話，那支影片會在搜尋端被降權——那比
    「文件沒整理出來」嚴重得多，所以文件失敗時退回原本的 `generate_summary()`。

    兩條路都失敗只記 log、不影響其他分析結果，跟本地 OCR 同樣的失敗隔離原則；
    budget 已經超支就整段跳過，維持原本的行為。
    """
    ctx.enter_stage("整理文件與摘要中")

    if ctx.over_budget:
        return _DocumentPhaseOutput()

    fresh_segments = db.list_segments_for_video(ctx.video_id)
    if not fresh_segments:
        return _DocumentPhaseOutput()

    try:
        result = document_pipeline.generate_document(ctx.client, ctx.video_title, fresh_segments)
        ctx.spend(result.cost_usd)
        return _DocumentPhaseOutput(
            # summary_model 填文件的模型而不是 summary_pipeline 的：這段文字真的
            # 是它產的。手動整理文件那條路也是這樣寫的（db.update_video_document()
            # 把 document_model 同時寫進 summary_model），兩條路要一致。
            summary=result.document.overview,
            summary_model=document_pipeline.MODEL_NAME,
            document_json=result.document.model_dump_json(),
            document_type=result.document.doc_type,
            document_model=document_pipeline.MODEL_NAME,
        )
    except Exception:
        logger.warning("自動整理文件失敗，退回只產生摘要", exc_info=True)

    try:
        summary_result = summary_pipeline.generate_summary(ctx.client, fresh_segments)
        ctx.spend(summary_result.cost_usd)
        return _DocumentPhaseOutput(
            summary=summary_result.summary, summary_model=summary_pipeline.MODEL_NAME
        )
    except Exception:
        logger.warning("自動產生摘要也失敗，跳過（不影響其他分析結果）", exc_info=True)

    return _DocumentPhaseOutput()


def _run_local_ocr_and_document(
    ctx: _AnalysisContext, segment_rows: list[_SegmentRow], segment_ids: list[int]
) -> _DocumentPhaseOutput:
    """Phase E（本地 OCR）跟 Phase F（整理文件與摘要）互不依賴——F 只讀 Phase D
    寫入的 segments，不碰 Phase E 寫的 ocr_events 表——改成同時起跑縮短耗時。兩者
    各拿一個 `ctx.budget_branch()`：都以「進入這個函式那一刻」的金額當預算判斷
    基準，互相看不到對方的花費。`_run_document_phase()` 判斷要不要花這筆錢的依據
    因此是「本地 OCR 開始前」的金額而不是「跑完後」——極端情況下兩者合計可能讓
    總花費比 BUDGET_USD 多出一點點，是刻意接受的已知取捨，見
    docs/02-technical-decisions.md#分析流程平行化。
    """
    ocr_ctx = ctx.budget_branch()
    document_ctx = ctx.budget_branch()

    def _do_local_ocr() -> bool:
        """回傳有沒有成功跑完。本地 OCR 整段失敗只記 log、不往外拋——已經成功的
        分析結果不能因為它而被判定失敗，見
        docs/02-technical-decisions.md#vlm-與-ocr。"""
        ocr_ctx.enter_stage("本地 OCR 掃描中")
        try:
            _run_local_ocr(ocr_ctx, segment_rows, segment_ids)
            return True
        except Exception:
            logger.warning("本地 OCR 掃描階段失敗，跳過（不影響其他分析結果）", exc_info=True)
            return False

    with ThreadPoolExecutor(max_workers=1) as pool:
        ocr_future = pool.submit(_do_local_ocr)
        document_output = _run_document_phase(document_ctx)

    # 本地 OCR 整段失敗時不併回它的花費：維持重構前的語意（舊版把累加中的
    # 金額放在區域變數裡，例外一拋就整個丟掉，已經花掉的 embedding 錢不會被
    # 算進總額）。這其實是個小小的低估，但屬於行為，不在這次重構的範圍內改。
    if ocr_future.result():
        ctx.merge_branch(ocr_ctx)
    ctx.merge_branch(document_ctx)
    return document_output
