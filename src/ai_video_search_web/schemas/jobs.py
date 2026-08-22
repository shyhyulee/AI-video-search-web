from __future__ import annotations

from pydantic import BaseModel

from .. import db


class JobOut(BaseModel):
    id: int
    job_type: str
    video_id: int | None
    status: str
    stage: str | None
    progress_percent: int | None
    progress_message: str | None
    error_message: str | None
    cost_usd: float | None
    created_at: str
    started_at: str | None
    completed_at: str | None

    @classmethod
    def from_record(cls, record: db.JobRecord) -> "JobOut":
        return cls(
            id=record.id, job_type=record.job_type, video_id=record.video_id, status=record.status,
            stage=record.stage, progress_percent=record.progress_percent,
            progress_message=record.progress_message, error_message=record.error_message,
            cost_usd=record.cost_usd, created_at=record.created_at, started_at=record.started_at,
            completed_at=record.completed_at,
        )
