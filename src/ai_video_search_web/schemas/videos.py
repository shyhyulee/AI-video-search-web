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

    @classmethod
    def from_record(cls, record: db.VideoRecord) -> "VideoOut":
        # file_path 刻意不外流（不向前端回傳伺服器實體路徑）。
        return cls(
            id=record.id, title=record.title, source=record.source, source_url=record.source_url,
            duration_sec=record.duration_sec, status=record.status, pipeline_stage=record.pipeline_stage,
            created_at=record.created_at, analyzed_at=record.analyzed_at, segment_count=record.segment_count,
            cost_usd=record.cost_usd, summary=record.summary,
        )


class YoutubeDownloadRequest(BaseModel):
    url: str
