from __future__ import annotations

from pydantic import BaseModel

from .. import db
from ..pipeline.document import VideoDocument


class VideoOut(BaseModel):
    id: int
    title: str
    source: str
    source_url: str | None
    duration_sec: int | None
    status: str
    pipeline_stage: str | None
    created_at: str
    analyzed_at: str | None
    segment_count: int | None
    cost_usd: float | None
    summary: str | None
    #: 這支影片整理過的文件類型（None＝還沒整理過）。刻意**只帶類型、不帶內容**：
    #: 影片庫清單每 3 秒輪詢一次，整包文件有數 KB，乘上整個清單的量太浪費。
    #: 完整內容走 GET /videos/{id}/document，只有真的要看的時候才取。
    document_type: str | None
    has_transcript: bool
    has_visual: bool
    has_ocr: bool

    @classmethod
    def from_record(
        cls, record: db.VideoRecord, flags: db.ModalityFlags | None = None
    ) -> "VideoOut":
        # file_path 刻意不外流（不向前端回傳伺服器實體路徑）。has_transcript／
        # has_visual／has_ocr 由 db.modality_flags_by_video() 聚合查詢算出，
        # 呼叫端負責一次查好再傳進來；flags 是 None（例如 pending 影片還沒有
        # 任何片段）時三者皆 False。
        flags = flags or db.ModalityFlags()
        return cls(
            id=record.id, title=record.title, source=record.source, source_url=record.source_url,
            duration_sec=record.duration_sec, status=record.status, pipeline_stage=record.pipeline_stage,
            created_at=record.created_at, analyzed_at=record.analyzed_at, segment_count=record.segment_count,
            cost_usd=record.cost_usd, summary=record.summary,
            document_type=record.document_type,
            has_transcript=flags.has_transcript,
            has_visual=flags.has_visual,
            has_ocr=flags.has_ocr,
        )


class VideoDocumentOut(BaseModel):
    """整理出來的文件內容。document 直接沿用 pipeline 的 pydantic 模型當契約——
    它本來就是 LLM 的 response_format，多包一層轉換只會多一個要同步維護的地方。
    """
    video_id: int
    document: VideoDocument
    model: str | None


class YoutubeDownloadRequest(BaseModel):
    url: str


class FrameQATurn(BaseModel):
    """同一格畫面先前的一組問答，供追問時帶上下文。"""
    question: str
    answer: str


class FrameQARequest(BaseModel):
    at_sec: float
    question: str
    #: 同一格畫面的先前問答。**由前端保管、時間點一變就清空**——帶著別格畫面的
    #: 問答會讓模型答錯格。存前端而不是伺服器，理由跟對話搜尋的 video_ids 相同：
    #: 它屬於「使用者現在正在看的那一格」，不是需要跨請求持久化的狀態。
    history: list[FrameQATurn] = []


class FrameQAOut(BaseModel):
    #: 回傳問的是哪一秒：前端送出後使用者可能又把影片拖走了，答案要標得出來源。
    at_sec: float
    answer: str
    cost_usd: float
