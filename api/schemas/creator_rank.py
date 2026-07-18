# -*- coding: utf-8 -*-

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


PlatformType = Literal["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"]
FetchOrderType = Literal["default", "pubdate", "click", "dm", "stow"]


class CreatorCommentRankRequest(BaseModel):
    platform: PlatformType = Field(..., description="Target platform")
    creator_url: str = Field(..., min_length=1, description="Creator homepage URL or platform ID")
    top_n: int = Field(default=10, ge=1, le=50)
    scan_all: bool = Field(
        default=True,
        description="Scan all creator uploads when supported.",
    )
    max_videos: int = Field(
        default=0,
        ge=0,
        le=2000,
        description="Safety cap when scan_all=true (0 = scan all). Hard limit when scan_all=false.",
    )
    fetch_order: FetchOrderType = Field(
        default="default",
        description="List traversal order (Bilibili only). Final ranking is always by comment count.",
    )


class CreatorVideoRankItem(BaseModel):
    rank: int
    video_id: str
    title: str
    comment_count: int
    play_count: int = 0
    url: str = ""
    id_label: str = ""
    metric_label: str = "平台互动"
    bvid: str = ""
    aid: str = ""
    created: Optional[int] = None


class CreatorCommentRankResponse(BaseModel):
    platform: PlatformType
    creator_id: str
    creator_name: str = ""
    total_videos: int = 0
    total_scanned: int
    scan_complete: bool = False
    scan_all: bool = True
    fetch_order: str = "default"
    capabilities: Dict[str, str] = Field(default_factory=dict)
    top_videos: List[CreatorVideoRankItem]
