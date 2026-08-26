"""工作狀態 API：查詢與重試背景工作，見 docs/09-web-ui-migration-plan.md
3.2 節。"""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas.jobs import JobOut
from ..services import job_manager

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(video_id: int | None = None) -> list[JobOut]:
    return [JobOut.from_record(j) for j in job_manager.list_jobs(video_id=video_id)]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int) -> JobOut:
    return JobOut.from_record(job_manager.get_job_or_raise(job_id))


@router.post("/{job_id}/retry", response_model=JobOut, status_code=202)
def retry_job(job_id: int) -> JobOut:
    new_job_id = job_manager.retry_job(job_id)
    return JobOut.from_record(job_manager.get_job_or_raise(new_job_id))
