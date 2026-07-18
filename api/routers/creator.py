# -*- coding: utf-8 -*-

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from playwright._impl._errors import TargetClosedError

from ..schemas.creator_rank import CreatorCommentRankRequest, CreatorCommentRankResponse
from ..services import crawler_manager, operation_coordinator
from ..services.creator_rank import rank_creator_videos_by_comments

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/creator", tags=["creator"])
_active_rank_task: Optional[asyncio.Task] = None
_rank_started_at: Optional[datetime] = None
RANK_TIMEOUT_SECONDS = 10 * 60


def _rank_error_message(exc: Exception) -> str:
    text = str(exc).strip()
    if isinstance(exc, TargetClosedError) or "TargetClosedError" in type(exc).__name__:
        return "浏览器窗口已关闭。请不要关闭自动打开的 Chrome，然后重新点击「查找高评论内容」。"
    lowered = text.lower()
    if any(token in lowered for token in ("rate", "频繁", "风控", "稍后再试", "412", "429")):
        return "B 站请求过于频繁，请等待 1-2 分钟后重试。"
    if "Browser failed to start" in text or "Cannot connect to existing browser" in text:
        return "浏览器启动失败。请关闭其他 Chrome 窗口后执行 ./run_web.sh 重启服务。"
    return text or "排行查询失败，请稍后重试。"


@router.post("/comment-rank", response_model=CreatorCommentRankResponse)
async def creator_comment_rank(request: CreatorCommentRankRequest):
    """Rank a creator's posts/videos by comment count on any supported platform."""
    global _active_rank_task, _rank_started_at
    if crawler_manager.status in {"running", "stopping"}:
        raise HTTPException(
            status_code=409,
            detail="评论采集任务正在运行，请等待结束后再查询创作者排行",
        )
    if not await operation_coordinator.try_acquire("rank"):
        active = operation_coordinator.snapshot().kind or "其他"
        raise HTTPException(status_code=409, detail=f"{active}任务正在运行，请稍后再试")

    try:
        _rank_started_at = datetime.now()
        _active_rank_task = asyncio.create_task(
            rank_creator_videos_by_comments(
                platform=request.platform,
                creator_url=request.creator_url.strip(),
                top_n=request.top_n,
                scan_all=request.scan_all,
                max_videos=request.max_videos,
                fetch_order=request.fetch_order,
            )
        )
        return await asyncio.wait_for(_active_rank_task, timeout=RANK_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="创作者内容扫描超过 10 分钟，已自动停止。请缩小扫描范围后重试。",
        ) from exc
    except asyncio.CancelledError as exc:
        raise HTTPException(status_code=499, detail="创作者内容扫描已取消") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[CreatorRank] comment-rank failed")
        raise HTTPException(status_code=500, detail=_rank_error_message(exc)) from exc
    finally:
        _active_rank_task = None
        _rank_started_at = None
        await operation_coordinator.release("rank")


@router.get("/status")
async def creator_rank_status():
    """Return the current creator-rank operation state."""
    running = _active_rank_task is not None and not _active_rank_task.done()
    return {
        "status": "running" if running else "idle",
        "started_at": _rank_started_at.isoformat() if _rank_started_at else None,
    }


@router.post("/cancel")
async def cancel_creator_rank():
    """Cancel the active creator-rank scan."""
    if _active_rank_task is None or _active_rank_task.done():
        raise HTTPException(status_code=400, detail="当前没有正在进行的创作者扫描")
    _active_rank_task.cancel()
    return {"status": "ok", "message": "已请求取消创作者扫描"}
