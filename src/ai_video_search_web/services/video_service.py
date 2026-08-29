"""影片相關的 Application Service：包裝 db.videos／downloader／analyzer 的呼叫，
讓 api/ 不必直接依賴 pipeline/ 與 db/，見 docs/09-web-ui-migration-plan.md。

多數函式是一行委派，刻意保留：它們標記的是「api 只能經過這裡」這條邊界。
下載／分析的實際觸發（downloader.start_download／analyzer.start_analysis）
不在這裡，由 services/job_manager.py 負責，見計畫文件 4.2 節。

三個 db 型別（VideoRecord／SegmentRecord／ModalityFlags）從這裡一併匯出：
api/ 需要它們做型別註記，但為此 import db 就等於在邊界上開一個洞——洞開著
的話「api 只能經過這裡」下次就會被當成沒那麼絕對。跟 search_service 匯出
SearchResult、stats_service 匯出 HeaderStatsData 是同一個作法。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import BinaryIO

from .. import db, downloader
from ..db import ModalityFlags, SegmentRecord, VideoRecord
from ..pipeline import analyzer, document as document_pipeline, media, summary as summary_pipeline
from ..pipeline.openai_client import get_client

logger = logging.getLogger(__name__)

_THUMBNAIL_SIZE = (320, 180)

#: 上傳的檔案放在影片目錄底下的這個子目錄，跟下載的影片（job-{id}/）分開。
_UPLOAD_SUBDIR = "uploads"


def is_youtube_url(url: str) -> bool:
    return downloader.is_youtube_url(url)


def find_existing_by_url(source_url: str) -> VideoRecord | None:
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
        return round(float(media.run_ffprobe(
            ["-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)]
        )))
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def store_upload(source: BinaryIO, suffix: str) -> Path:
    """把上傳的檔案內容存進上傳目錄，回傳落檔路徑。

    檔名用系統產生的 uuid4、不沿用使用者上傳的檔名，避免 Path Traversal 與
    覆蓋既有檔案，見 docs/08-web-ui-migration-design.md 第 11 節；副檔名由呼叫
    端驗證後傳入（那是 HTTP 層的輸入驗證，422 屬於 api/）。

    「檔案放在哪、叫什麼名字」是這一層的事，不是 api/ 的事：刪除影片時把檔案
    一起 unlink 的 `delete_video()` 本來就在這裡，落檔卻寫在端點裡，等於檔案
    生命週期的兩端各住一層。每次呼叫都讀一次 `downloader.VIDEO_DIR`（不是在
    模組載入時算好），測試才能用 monkeypatch 換掉影片目錄。
    """
    upload_dir = downloader.VIDEO_DIR / _UPLOAD_SUBDIR
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_path = upload_dir / f"{uuid.uuid4().hex}{suffix}"
    with dest_path.open("wb") as out:
        shutil.copyfileobj(source, out)
    return dest_path


def register_uploaded_video(title: str, file_path: Path, duration_sec: int | None) -> int:
    """磁碟檔名是系統產生的 uuid（見 `store_upload()`），跟使用者看到的標題是
    兩件事，標題要由呼叫端另外傳入，不能沿用 file_path.stem。
    """
    return db.insert_video(
        title=title,
        source=db.SOURCE_LOCAL,
        source_url=None,
        file_path=str(file_path),
        duration_sec=duration_sec,
    )


def list_unanalyzed_videos() -> list[VideoRecord]:
    return db.list_unanalyzed_videos()


def list_library_videos() -> list[VideoRecord]:
    return db.list_library_videos()


def get_video(video_id: int) -> VideoRecord | None:
    return db.get_video(video_id)


def list_segments_for_video(video_id: int) -> list[SegmentRecord]:
    return db.list_segments_for_video(video_id)


def modality_flags(video_ids: list[int] | None = None) -> dict[int, ModalityFlags]:
    """每支影片有哪些模態的內容（給 VideoOut 的三個旗標用），一次查完。
    沒有片段的影片不會出現在回傳的 dict 裡。"""
    return db.modality_flags_by_video(video_ids)


def is_within_duration_limit(duration_sec: int | None) -> bool:
    return analyzer.is_within_duration_limit(duration_sec)


def max_duration_minutes() -> int:
    return analyzer.MAX_DURATION_SEC // 60


def delete_video(video_id: int) -> tuple[VideoRecord | None, str | None]:
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


def prepare_reanalysis(video: VideoRecord) -> None:
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


def regenerate_summary(video_id: int, segments: list[SegmentRecord]) -> summary_pipeline.SummaryResult:
    client = get_client()
    result = summary_pipeline.generate_summary(client, segments)
    db.update_video_summary(video_id, result.summary, summary_pipeline.MODEL_NAME, result.cost_usd)
    return result


def generate_document(
    video: VideoRecord, segments: list[SegmentRecord]
) -> document_pipeline.DocumentResult:
    """整理出一份結構化文件**與摘要**並存回影片記錄上（重複呼叫＝重新整理，
    直接覆蓋）。

    文件的 overview 一稿兩用，同時寫進 videos.summary——所以「整理成文件」這
    一顆按鈕會同時更新兩者，不需要另外再產一次摘要。`videos.summary` 不能只
    當顯示欄位放著不管：搜尋的影片層級篩選（pipeline/search/dense.py）與影片庫
    的主題分類、庫內搜尋（lib/videoCategory.ts）都在讀它。

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
        result.document.overview,
        result.cost_usd,
    )
    return result


def document_model_name() -> str:
    """產生文件用的模型名稱，給 api/ 填進回應。

    用函式而不是模組層常數：常數會在 import 時就把值定死，測試改
    `document_pipeline.MODEL_NAME` 就不會生效——而測試正是這樣改的
    （見 tests/test_services_video.py）。
    """
    return document_pipeline.MODEL_NAME


def load_document(video: VideoRecord) -> document_pipeline.VideoDocument | None:
    """讀回已經整理過的文件；沒整理過回 None。"""
    if not video.document_json:
        return None
    return document_pipeline.VideoDocument.model_validate_json(video.document_json)


def generate_thumbnail(video: VideoRecord, size: tuple[int, int] = _THUMBNAIL_SIZE) -> bytes | None:
    """在影片時間中點用 ffmpeg 擷取一張縮圖，回傳 PNG bytes；擷取失敗回傳
    None。每次呼叫都重新產生，尚未做 docs/09-web-ui-migration-plan.md Phase 3
    規劃的「分析完成時就產生並保存」。
    """
    if not video.file_path or not Path(video.file_path).exists():
        return None

    mid_sec = (video.duration_sec or 0) / 2
    thumb_path = media.new_temp_path(".png")
    try:
        media.run_ffmpeg(
            [
                "-ss", str(max(mid_sec, 0.0)), "-i", video.file_path,
                "-vf", f"scale={size[0]}:{size[1]}",
                "-frames:v", "1",
                str(thumb_path),
            ],
            timeout=media.FRAME_TIMEOUT_SEC,
        )
        return thumb_path.read_bytes()
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        thumb_path.unlink(missing_ok=True)
