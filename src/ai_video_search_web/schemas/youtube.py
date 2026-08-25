from __future__ import annotations

import dataclasses

from pydantic import BaseModel

from ..services.youtube_search_service import YoutubeSearchItem


class YoutubeSearchItemOut(BaseModel):
    video_id: str
    title: str
    url: str
    description: str
    duration_sec: int | None
    channel: str
    view_count: int | None
    thumbnail_url: str | None

    @classmethod
    def from_item(cls, item: YoutubeSearchItem) -> "YoutubeSearchItemOut":
        return cls(**dataclasses.asdict(item))


class YoutubeSearchResponseOut(BaseModel):
    items: list[YoutubeSearchItemOut]
