"""分析執行緒的入口與事件契約：起執行緒、保證送出剛好一個終端事件、
依序呼叫 phases，最後把結果寫回資料庫。

流程的順序只寫在這裡；phases 自己不知道誰先誰後。長度上限也放這裡——那是
進門前的准入判斷（`services/video_service.py` 也在用），不是某個 phase 的事。
"""
from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

from ... import db
from .. import asr, embedding, vlm
from ..openai_client import get_client
from . import context
from .context import _AnalysisContext
from .events import AnalysisError, AnalysisProgress, AnalysisResult
from .phases import (
    _run_embedding_phase,
    _run_local_ocr_and_document,
    _run_scene_detection_and_transcription,
    _run_vlm_phase,
    _write_segments,
)

logger = logging.getLogger(__name__)

# 原本 20 分鐘，2026-08-26 依使用者要求放寬到 1 小時；BUDGET_USD 同時由 $0.30
# 調到 $0.80 配合它。$0.80 是依實測 10 支影片（1.0~18.6 分鐘）反推的：
#
#   成本 ≈ ASR($0.006/分，asr.PRICE_PER_MINUTE_USD 固定值)
#          + 每片段 $0.00050~$0.00090（VLM＋embedding＋摘要，實測區間）
#
# 60 分鐘影片：實測密度下平均約 $0.55、最壞觀測費率約 $0.70。片段密度不會失控
# ——scene_detect 會把場景正規化成 8~12 秒（MERGE_BELOW_SEC／SPLIT_ABOVE_SEC），
# 所以密度的結構上限是 60/8 = 7.5 個/分，快剪內容也一樣。用「結構上限密度 ×
# 最高觀測每片段費率」算出的最壞情況是 $0.765，仍在 $0.80 內（餘裕僅 4.6%）。
#
# 注意：$0.80 不是 60 分鐘影片真正的瓶頸。asr._extract_audio() 固定輸出 64kbps
# 單聲道 mp3（實測 7,998 bytes/s），Whisper 的 25MB 上傳上限換算後約 52~55
# 分鐘，且 ASR 例外會讓整支分析失敗（不是略過字幕）。所以超過約 52 分鐘的影片
# 會先卡在 ASR，不會走到預算判斷。完整推導與實測資料見 docs/05 §8.12。
MAX_DURATION_SEC = 60 * 60


def is_within_duration_limit(duration_sec: int | None) -> bool:
    return duration_sec is not None and duration_sec <= MAX_DURATION_SEC


def start_analysis(video_id: int, progress_queue: "queue.Queue[object]") -> threading.Thread:
    thread = threading.Thread(target=_analyze_worker, args=(video_id, progress_queue), daemon=True)
    thread.start()
    return thread


def _analyze_worker(video_id: int, progress_queue: "queue.Queue[object]") -> None:
    """分析執行緒的最外層。唯一的職責是保證「不管發生什麼事，都會送出剛好一個
    終端事件」（AnalysisResult 或 AnalysisError）。

    這件事是硬需求不是防禦性程式碼：job_manager 的 pump thread 用
    `queue.get()` 等終端事件、收到才會 break 並釋放分析 slot。少送一次，
    pump 就永遠停在那裡、slot 永遠不會釋放，**之後每一支影片的分析都會卡在
    queued，只能重啟伺服器**。實際踩得到的路徑是 `_run_analysis()` 進到自己
    的 try 之前那幾行（讀影片紀錄、更新狀態、`get_client()`——缺 API 金鑰時
    OpenAI() 會直接拋）。
    """
    try:
        _run_analysis(video_id, progress_queue)
    except Exception as exc:
        # 走到這裡代表 _run_analysis() 內層的 except 沒接到（例如例外發生在它
        # 自己的 try 之前，或連內層處理本身都失敗了）。訊息用最原始的形式，
        # 不假設任何前置資料（例如影片標題）拿得到。
        logger.error("分析執行緒異常結束（video_id=%s）：%s", video_id, exc, exc_info=True)
        try:
            db.update_video_status(video_id, db.STATUS_FAILED, f"分析失敗：{exc}")
        except Exception:
            logger.error("連標記分析失敗都寫不進資料庫（video_id=%s）", video_id, exc_info=True)
        progress_queue.put(AnalysisError(video_id=video_id, message=str(exc)))


def _run_analysis(video_id: int, progress_queue: "queue.Queue[object]") -> None:
    video = db.get_video(video_id)
    if video is None:
        progress_queue.put(AnalysisError(video_id=video_id, message="找不到這支影片的紀錄"))
        return

    video_path = Path(video.file_path)
    if not video_path.exists():
        db.update_video_status(video_id, db.STATUS_FAILED, "找不到影片檔案")
        progress_queue.put(AnalysisError(video_id=video_id, message="找不到影片檔案"))
        return

    # 這個階段切換刻意不透過 ctx：建立 context 需要 client，而 get_client()
    # 必須留在「場景切分中」寫進 DB／送出事件之後——維持重構前的順序，
    # get_client() 失敗（例如缺 API 金鑰）時的可觀察狀態才會跟以前一致。
    db.update_video_status(video_id, db.STATUS_ANALYZING, "場景切分中")
    progress_queue.put(AnalysisProgress(stage="場景切分中"))

    ctx = _AnalysisContext(
        video_id=video_id, video_path=video_path, client=get_client(), progress_queue=progress_queue,
        video_title=video.title,
    )

    try:
        duration_sec = float(video.duration_sec or 0)

        scenes, transcribe_result = _run_scene_detection_and_transcription(ctx, duration_sec)

        scene_rows, vlm_failed_count = _run_vlm_phase(ctx, scenes, transcribe_result)

        segment_rows = _run_embedding_phase(ctx, scene_rows)

        segment_ids = _write_segments(ctx, segment_rows)

        segment_count = len(segment_rows)
        partial = segment_count < len(scenes)
        # 預算截斷跟「單一場景 VLM 失敗」是兩件互相獨立的事，各自有各自的訊息，
        # 可能同時發生，用「；」串起來——不能共用同一個 partial 判斷或同一句
        # 文字，不然使用者會看到誤導的原因（例如明明是內容審查拒絕，卻顯示
        # 「已達預算上限」），見 docs/00-overview.md#33-整體資料流。
        stage_notes = []
        if partial:
            stage_notes.append(f"已達預算上限（US${context.BUDGET_USD:.2f}），完成 {segment_count}/{len(scenes)} 片段")
        if vlm_failed_count:
            stage_notes.append(f"{vlm_failed_count} 個場景畫面分析失敗，已略過（保留字幕，無畫面描述）")
        pipeline_stage = "；".join(stage_notes) or None

        # Phase E（本地 OCR）／Phase F（整理文件與摘要）互不依賴，同時起跑縮短
        # 耗時，見 docs/02-technical-decisions.md#分析流程平行化。本地 OCR 整段
        # 失敗只記 log、不能讓已經成功的分析結果被判定為失敗，見
        # docs/02-technical-decisions.md#vlm-與-ocr。
        document_output = _run_local_ocr_and_document(ctx, segment_rows, segment_ids)

        db.mark_video_analyzed(
            video_id=video_id,
            segment_count=segment_count,
            cost_usd=ctx.total_cost,
            asr_model=asr.MODEL_NAME,
            vlm_model=vlm.MODEL_NAME,
            embedding_model=embedding.MODEL_NAME,
            pipeline_stage=pipeline_stage,
            # 文件的花費已經透過 ctx.spend() 進了上面的 cost_usd，所以文件三欄
            # 跟著這一句一起寫，不能改呼叫 db.update_video_document()——那支是
            # 累加語意，會把同一次呼叫的錢算兩次。
            summary=document_output.summary,
            summary_model=document_output.summary_model,
            document_json=document_output.document_json,
            document_type=document_output.document_type,
            document_model=document_output.document_model,
        )
        progress_queue.put(
            AnalysisResult(
                video_id=video_id, segment_count=segment_count, cost_usd=ctx.total_cost, partial=partial,
                vlm_failed_count=vlm_failed_count,
            )
        )

    except Exception as exc:  # 分析過程各種例外統一攔截，避免背景執行緒讓整支程式崩潰
        current = db.get_video(video_id)  # 必須在下面 STATUS_FAILED 覆蓋 pipeline_stage 之前先讀
        stage_label = (current.pipeline_stage if current else None) or "分析"
        logger.error("「%s」在「%s」階段分析失敗：%s", video.title, stage_label, exc, exc_info=True)
        db.update_video_status(video_id, db.STATUS_FAILED, f"分析失敗：{exc}")
        progress_queue.put(AnalysisError(video_id=video_id, message=str(exc)))
