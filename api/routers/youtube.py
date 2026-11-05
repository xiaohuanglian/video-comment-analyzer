# -*- coding: utf-8 -*-
"""YouTube 评论采集 API。

- GET  /youtube/comments/targets   对标频道 + 将采哪几条视频
- POST /youtube/comments/collect   起一个后台采集任务
- GET  /youtube/comments/jobs      任务列表 / 单个任务
- GET  /youtube/comments/summary   本地已有数据统计
- GET  /youtube/comments/download  下载某个频道的 CSV
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.services.youtube import comments, jobs

router = APIRouter(prefix="/youtube/comments", tags=["youtube"])


@router.get("/targets")
async def list_targets(limit: int = Query(default=3, ge=1, le=20)) -> Dict[str, Any]:
    return {"targets": comments.list_targets(limit=limit)}


class CollectRequest(BaseModel):
    limit: int = Field(default=3, ge=1, le=20)
    channels: List[str] = Field(default_factory=list)
    max_comments: int = Field(default=comments.DEFAULT_MAX_COMMENTS, ge=20, le=3000)
    max_parents: int = Field(default=comments.DEFAULT_MAX_PARENTS, ge=5, le=500)
    max_replies: int = Field(default=comments.DEFAULT_MAX_REPLIES, ge=0, le=100)
    sort: str = Field(default="top", pattern="^(top|newest)$")


@router.post("/collect")
async def collect(req: CollectRequest) -> Dict[str, Any]:
    try:
        return jobs.start_collect(
            limit=req.limit,
            channels=req.channels or None,
            max_comments=req.max_comments,
            max_parents=req.max_parents,
            max_replies=req.max_replies,
            sort=req.sort,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs")
async def list_jobs(limit: int = Query(default=10, ge=1, le=50)) -> List[Dict[str, Any]]:
    return jobs.list_jobs(limit)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> Dict[str, Any]:
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在（重启后任务列表会清空，CSV 仍在）")
    return job


@router.get("/summary")
async def summary() -> Dict[str, Any]:
    items = [comments.channel_summary(c.name) for c in comments.list_channels()]
    items.sort(key=lambda i: -i["comments"])
    return {
        "channels": items,
        "total_comments": sum(i["comments"] for i in items),
        "out_dir": str(comments.OUT_DIR),
    }


@router.get("/download")
async def download(channel: str = Query(..., min_length=1)) -> Response:
    path: Optional[Path] = comments.channel_csv_path(channel)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"还没有采集数据：{channel}")
    content = path.read_bytes()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{path.parent.name}.csv"'},
    )
