"""影片相關的 Application Service：包裝 db.videos／downloader／analyzer 的呼叫，
讓 api/ 不必直接依賴 pipeline/ 與 db/，見 docs/09-web-ui-migration-plan.md。

多數函式是一行委派，刻意保留：它們標記的是「api 只能經過這裡」這條邊界。
下載／分析的實際觸發（downloader.start_download／analyzer.start_analysis）
不在這裡，由 services/job_manager.py 負責，見計畫文件 4.2 節。
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from .. import db, downloader
from ..pipeline import analyzer, document as document_pipeline, summary as summary_pipeline
from ..pipeline.openai_client import get_client

logger = logging.getLogger(__name__)

_THUMBNAIL_SIZE = (320, 180)


def is_youtube_url(url: str) -> bool:
    return downloader.is_youtube_url(url)


def find_existing_by_url(source_url: str) -> db.VideoRecord | None:
    return db.find_by_source_url(source_url)


def register_downloaded_video(
    title: str, source_url: str, file_path: Path, duration_sec: int | None
) -> int:
    return db.insert_video(
        title=title,
        source=db.SOURCE_YOUTUBE,
        source_url=source_url,
        file_path=str(file_path),
        duration_sec=duration_sec,
    )


def probe_local_duration(video_path: Path) -> int | None:
    """用 ffprobe 讀取本機影片長度；讀不到就回傳 None，不擋住新增流程。"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return round(float(result.stdout.strip()))
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def register_uploaded_video(title: str, file_path: Path, duration_sec: int | None) -> int:
    """磁碟檔名是系統產生的 uuid（避免 Path Traversal／檔名衝突，見
    api/videos.py 上傳端點），跟使用者看到的標題是兩件事，標題要由呼叫端
    另外傳入，不能沿用 file_path.stem。
    """
    return db.insert_video(
        title=title,
        source=db.SOURCE_LOCAL,
        source_url=None,
        file_path=str(file_path),
        duration_sec=duration_sec,
    )


def list_unanalyzed_videos() -> list[db.VideoRecord]:
    return db.list_unanalyzed_videos()


def list_library_videos() -> list[db.VideoRecord]:
    return db.list_library_videos()


def get_video(video_id: int) -> db.VideoRecord | None:
    return db.get_video(video_id)


def list_segments_for_video(video_id: int) -> list[db.SegmentRecord]:
    return db.list_segments_for_video(video_id)


def modality_flags(video_ids: list[int] | None = None) -> dict[int, db.ModalityFlags]:
    """每支影片有哪些模態的內容（給 VideoOut 的三個旗標用），一次查完。
    沒有片段的影片不會出現在回傳的 dict 裡。"""
    return db.modality_flags_by_video(video_ids)


def is_within_duration_limit(duration_sec: int | None) -> bool:
    return analyzer.is_within_duration_limit(duration_sec)


def max_duration_minutes() -> int:
    return analyzer.MAX_DURATION_SEC // 60


def delete_video(video_id: int) -> tuple[db.VideoRecord | None, str | None]:
    """刪除影片 DB 紀錄與磁碟檔案。回傳 (被刪除的紀錄或 None, 檔案刪除失敗時的
    錯誤訊息或 None)。檔案刪除失敗會記錄完整 log（含 traceback），但不影響 DB
    紀錄已刪除的事實；錯誤訊息文字交給呼叫端決定如何呈現（目前 api/videos.py
    選擇忽略它，只回報 DB 紀錄已刪除）。
    """
    record = db.delete_video(video_id)
    if record is None:
        return None, None
    file_path = Path(record.file_path)
    try:
        file_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.error("「%s」的檔案刪除失敗：%s", record.title, exc, exc_info=True)
        return record, str(exc)
    return record, None


def reset_to_pending(video_id: int) -> None:
    db.reset_to_pending(video_id)


def prepare_reanalysis(video: db.VideoRecord) -> None:
    """把影片切到「準備重新分析」的狀態，供 submit_analysis() 接手。

    分兩種情況，差別在這支影片有沒有產出過結果：

    - 已經分析成功過（`analyzed_at` 有值）：只改 status，segments 與所有分析
      欄位原封不動。影片留在影片庫、舊結果照樣搜得到，直到 analyzer 寫入新
      片段時才換掉（見 `analyzer._write_segments()`）。若清空後才開始跑，影片
      會在整段重新分析期間變成一支查不到東西的空殼，還會因為 `analyzed_at`
      被清掉而從影片庫掉到「影片與分析」再跳回來。
    - 從沒成功過（第一次就失敗）：`reset_to_pending()`，清掉部分寫入的殘骸。
      它本來就沒有可保留的結果，而回到 pending 也正確反映了「這支還沒有東西」。
    """
    if video.analyzed_at is not None:
        db.update_video_status(video.id, db.STATUS_ANALYZING, "等待重新分析")
    else:
        db.reset_to_pending(video.id)


def regenerate_summary(video_id: int, segments: list[db.SegmentRecord]) -> summary_pipeline.SummaryResult:
    client = get_client()
    result = summary_pipeline.generate_summary(client, segments)
    db.update_video_summary(video_id, result.summary, summary_pipeline.MODEL_NAME, result.cost_usd)
    return result


def generate_document(
    video: db.VideoRecord, segments: list[db.SegmentRecord]
) -> document_pipeline.DocumentResult:
    """整理出一份結構化文件並存回影片記錄上（重複呼叫＝重新整理，直接覆蓋）。

    存的是整包 JSON 而不是拆成欄位：文件的形狀由 pipeline 的 pydantic 模型
    決定，之後 schema 演進時只要動那一個地方，DB 不用跟著改。
    """
    client = get_client()
    result = document_pipeline.generate_document(client, video.title, segments)
    db.update_video_document(
        video.id,
        result.document.model_dump_json(),
        result.document.doc_type,
        document_pipeline.MODEL_NAME,
        result.cost_usd,
    )
    return result


def load_document(video: db.VideoRecord) -> document_pipeline.VideoDocument | None:
    """讀回已經整理過的文件；沒整理過回 None。"""
    if not video.document_json:
        return None
    return document_pipeline.VideoDocument.model_validate_json(video.document_json)


def generate_thumbnail(video: db.VideoRecord, size: tuple[int, int] = _THUMBNAIL_SIZE) -> bytes | None:
    """在影片時間中點用 ffmpeg 擷取一張縮圖，回傳 PNG bytes；擷取失敗回傳
    None。每次呼叫都重新產生，尚未做 docs/09-web-ui-migration-plan.md Phase 3
    規劃的「分析完成時就產生並保存」。
    """
    if not video.file_path or not Path(video.file_path).exists():
        return None

    mid_sec = (video.duration_sec or 0) / 2
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    thumb_path = Path(tmp_path)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(max(mid_sec, 0.0)), "-i", video.file_path,
                "-vf", f"scale={size[0]}:{size[1]}",
                "-frames:v", "1",
                str(thumb_path),
            ],
            check=True, capture_output=True, timeout=15,
        )
        return thumb_path.read_bytes()
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        thumb_path.unlink(missing_ok=True)
