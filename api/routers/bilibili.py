# -*- coding: utf-8 -*-

from fastapi import APIRouter, HTTPException

from ..schemas.bilibili import CreatorCommentRankRequest as BiliCreatorCommentRankRequest
from ..schemas.creator_rank import CreatorCommentRankResponse
from ..services import crawler_manager, operation_coordinator
from ..services.creator_rank import rank_creator_videos_by_comments

router = APIRouter(prefix="/bilibili", tags=["bilibili"])


@router.post("/creator/comment-rank", response_model=CreatorCommentRankResponse)
async def creator_comment_rank(request: BiliCreatorCommentRankRequest):
    """Backward-compatible Bilibili creator rank endpoint."""
    if crawler_manager.status in {"running", "stopping"}:
        raise HTTPException(
            status_code=409,
            detail="评论抓取任务正在运行，请等待结束后再查询创作者排行",
        )
    if not await operation_coordinator.try_acquire("rank"):
        raise HTTPException(status_code=409, detail="其他浏览器任务正在运行，请稍后再试")

    try:
        return await rank_creator_videos_by_comments(
            platform="bili",
            creator_url=request.creator_url.strip(),
            top_n=request.top_n,
            scan_all=request.scan_all,
            max_videos=request.max_videos,
            fetch_order=request.fetch_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"查询失败: {exc}") from exc
    finally:
        await operation_coordinator.release("rank")
