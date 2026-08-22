from __future__ import annotations

from pydantic import BaseModel

from .. import db


class HeaderStatsOut(BaseModel):
    pending_count: int
    analyzed_count: int
    segment_count: int
    total_cost_usd: float

    @classmethod
    def from_data(cls, data: db.HeaderStatsData) -> "HeaderStatsOut":
        return cls(
            pending_count=data.pending_count,
            analyzed_count=data.analyzed_count,
            segment_count=data.segment_count,
            total_cost_usd=data.total_cost_usd,
        )
