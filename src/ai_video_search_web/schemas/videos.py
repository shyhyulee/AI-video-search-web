from __future__ import annotations

from pydantic import BaseModel

from .. import db


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
            has_transcript=flags.has_transcript,
            has_visual=flags.has_visual,
            has_ocr=flags.has_ocr,
        )


class YoutubeDownloadRequest(BaseModel):
    url: str
