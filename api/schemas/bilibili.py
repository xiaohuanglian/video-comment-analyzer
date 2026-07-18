# -*- coding: utf-8 -*-

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


FetchOrderType = Literal["default", "pubdate", "click", "dm", "stow"]


class CreatorCommentRankRequest(BaseModel):
    creator_url: str = Field(..., min_length=1, description="Bilibili creator space URL or UID")
    top_n: int = Field(default=10, ge=1, le=50)
    scan_all: bool = Field(
        default=True,
        description="Scan all creator uploads (recommended). If false, only scan first max_videos.",
    )
    max_videos: int = Field(
        default=0,
        ge=0,
        le=2000,
        description="Safety cap when scan_all=true (0 = no cap). Hard limit when scan_all=false.",
    )
    fetch_order: FetchOrderType = Field(
        default="default",
        description="Bilibili list traversal order. Does not affect final comment ranking.",
    )


class CreatorVideoRankItem(BaseModel):
    rank: int
    bvid: str
    aid: str = ""
    title: str
    comment_count: int
    play_count: int = 0
    danmaku_count: int = 0
    url: str
    created: Optional[int] = None


class CreatorCommentRankResponse(BaseModel):
    creator_id: str
    creator_name: str = ""
    total_videos: int = 0
    total_scanned: int
    scan_complete: bool = False
    scan_all: bool = True
    fetch_order: str = "default"
    top_videos: List[CreatorVideoRankItem]
