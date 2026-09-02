"""工作狀態 API：查詢與重試背景工作，見 docs/archive/09-web-ui-migration-plan.md
3.2 節。"""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas.jobs import JobOut
from ..services import job_manager

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(
    video_id: int | None = None, active: bool = False, job_type: str | None = None
) -> list[JobOut]:
    """`active=true` 只回還沒到終態（queued／running）的工作。

    前端載入「影片分析」頁時用 `?active=true&job_type=analysis` 把進行中的
    分析接回進度顯示——追蹤清單原本只活在 React state，重新整理就沒了。
    active 與 video_id 不併用（前端只需要其中一種查法），給了 active 就以它為準。
    """
    records = (
        job_manager.list_active_jobs(job_type=job_type)
        if active
        else job_manager.list_jobs(video_id=video_id)
    )
    return [JobOut.from_record(j) for j in records]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int) -> JobOut:
    return JobOut.from_record(job_manager.get_job_or_raise(job_id))


@router.post("/{job_id}/retry", response_model=JobOut, status_code=202)
def retry_job(job_id: int) -> JobOut:
    new_job_id = job_manager.retry_job(job_id)
    return JobOut.from_record(job_manager.get_job_or_raise(new_job_id))
