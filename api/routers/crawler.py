from fastapi import APIRouter, HTTPException

from tools.crawl_pacing import ERROR_HINTS, format_duration, platform_cooldown

from ..schemas import CrawlerStartRequest, CrawlerStatusResponse
from ..services import crawler_manager, operation_coordinator
from ..services.collect_inventory import local_data_inventory
from ..services.xhs_notes_inventory import get_notes

router = APIRouter(prefix="/crawler", tags=["crawler"])


@router.post("/start")
async def start_crawler(request: CrawlerStartRequest):
    """Start crawler task"""
    success = await crawler_manager.start(request)
    if not success:
        cooldown = platform_cooldown(request.platform.value)
        if cooldown:
            # 平台冷却中：告诉用户"还需等多久"，比笼统的启动失败有用
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{request.platform.value} 平台冷却中：还需等待 "
                    f"{format_duration(float(cooldown.get('retry_after_seconds') or 0))}。"
                    f"{ERROR_HINTS.get(str(cooldown.get('code') or ''), '')}"
                ),
            )
        active_operation = operation_coordinator.snapshot().kind
        if active_operation == "rank":
            raise HTTPException(
                status_code=409,
                detail="创作者内容扫描正在运行，请等待结束或取消后再开始采集",
            )
        # Handle concurrent/duplicate requests: if process is already running, return 400 instead of 500
        if crawler_manager.process and crawler_manager.process.poll() is None:
            raise HTTPException(status_code=409, detail="已有评论采集任务正在运行")
        raise HTTPException(status_code=500, detail="评论采集任务启动失败")

    return {"status": "ok", "message": "Crawler started successfully"}


@router.post("/stop")
async def stop_crawler():
    """Stop crawler task"""
    success = await crawler_manager.stop()
    if not success:
        # Handle concurrent/duplicate requests: if process already exited/doesn't exist, return 400 instead of 500
        if not crawler_manager.process or crawler_manager.process.poll() is not None:
            raise HTTPException(status_code=400, detail="No crawler is running")
        raise HTTPException(status_code=500, detail="Failed to stop crawler")

    return {"status": "ok", "message": "Crawler stopped successfully"}


@router.get("/status", response_model=CrawlerStatusResponse)
async def get_crawler_status(refresh_progress: bool = False):
    """Get crawler status"""
    return crawler_manager.get_status(refresh_progress=refresh_progress)


@router.get("/logs")
async def get_logs(limit: int = 100):
    """Get recent logs"""
    logs = crawler_manager.logs[-limit:] if limit > 0 else crawler_manager.logs
    return {"logs": [log.model_dump() for log in logs]}


@router.get("/local-data")
async def get_local_data():
    """本地已采数据盘点:各平台采回了多少笔记/评论,按批次列出。

    采集页的「本地已采数据」概览用,回答"我到底采回了什么"。
    """
    return local_data_inventory()


@router.get("/xhs-notes")
async def get_xhs_notes(
    batch: str = "",
    q: str = "",
    sort: str = "liked",
    limit: int = 500,
    offset: int = 0,
):
    """小红书关键词笔记清单（采集页「笔记列表」用）。

    数据来自 `data/xhs_search/<批次>/notes.csv`，是「只有笔记、没有评论」的
    搜索结果；这里只读不写。`batch` 留空就给最新一批。
    """
    try:
        return get_notes(batch=batch, q=q, sort=sort, limit=limit, offset=offset)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
