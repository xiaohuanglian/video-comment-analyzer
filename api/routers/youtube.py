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
    max_parents: Optional[int] = Field(default=None, ge=5, le=2000)
    max_replies: Optional[int] = Field(default=None, ge=0, le=500)
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


class ReportRequest(BaseModel):
    channels: List[str] = Field(default_factory=list)
    keywords: str = ""
    max_videos: int = Field(default=8, ge=1, le=20)
    sample_per_video: int = Field(default=8, ge=3, le=30)


@router.post("/report")
async def build_report(req: ReportRequest) -> Dict[str, Any]:
    """用已采的 YouTube 评论出一份对标报告（存进 reports.json，历史里可见）。"""
    from api.services.youtube import report as report_service

    available = [c.name for c in comments.list_channels()]
    wanted = req.channels or available
    rows: List[Dict[str, Any]] = []
    for channel in wanted:
        rows.extend(comments.read_csv(comments.channel_csv_path(channel)).values())
    if not rows:
        raise HTTPException(status_code=400, detail="这些频道还没有采到评论，先跑采集")

    scope = "YouTube 对标 " + ("、".join(wanted[:4]) + ("…" if len(wanted) > 4 else ""))
    try:
        return await report_service.analyze(
            rows,
            scope=scope,
            keywords=req.keywords,
            max_videos=req.max_videos,
            sample_per_video=req.sample_per_video,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"报告生成失败：{exc}") from exc
