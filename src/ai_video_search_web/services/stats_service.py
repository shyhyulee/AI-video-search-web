"""統計資料 Application Service：薄包裝 db.get_header_stats()。"""
from __future__ import annotations

from .. import db
from ..db import HeaderStatsData

__all__ = ["HeaderStatsData", "get_header_stats"]


def get_header_stats() -> HeaderStatsData:
    return db.get_header_stats()
