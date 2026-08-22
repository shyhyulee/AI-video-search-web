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
        cls, record: db.VideoRecord, segments: list[db.SegmentRecord] | None = None
    ) -> "VideoOut":
        # file_path 刻意不外流（不向前端回傳伺服器實體路徑）。has_transcript／
        # has_visual／has_ocr 是從 segments 衍生的旗標，跟 ui/library_tab.py
        # 的 _build_row() 邏輯一致；segments 是 None（例如 pending 影片還沒
        # 有任何片段）時三者皆 False。
        segments = segments or []
        return cls(
            id=record.id, title=record.title, source=record.source, source_url=record.source_url,
            duration_sec=record.duration_sec, status=record.status, pipeline_stage=record.pipeline_stage,
            created_at=record.created_at, analyzed_at=record.analyzed_at, segment_count=record.segment_count,
            cost_usd=record.cost_usd, summary=record.summary,
            has_transcript=any(s.transcript for s in segments),
            has_visual=any(s.visual_description for s in segments),
            has_ocr=any(s.ocr_text for s in segments),
        )


class YoutubeDownloadRequest(BaseModel):
    url: str
