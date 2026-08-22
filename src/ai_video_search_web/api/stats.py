"""GET /api/v1/stats"""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas.stats import HeaderStatsOut
from ..services import stats_service

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=HeaderStatsOut)
def get_stats() -> HeaderStatsOut:
    return HeaderStatsOut.from_data(stats_service.get_header_stats())
