# -*- coding: utf-8 -*-
"""公众号采集 API(原生内置,无外部工具依赖)。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services import wechat_native as wn

router = APIRouter(prefix="/wechat", tags=["wechat"])


class UrlBody(BaseModel):
    url: str


class CollectionBody(UrlBody):
    max_pages: int = 10


@router.get("/library")
async def library(limit: int = 100) -> list[dict[str, Any]]:
    return wn._load_index()[-limit:][::-1]


@router.delete("/library/{item_id}")
async def delete_item(item_id: str) -> dict[str, bool]:
    wn._save_index([i for i in wn._load_index() if i.get("id") != item_id])
    return {"ok": True}


@router.post("/article")
async def article(body: UrlBody) -> dict[str, Any]:
    if "mp.weixin.qq.com" not in body.url:
        raise HTTPException(status_code=400, detail="不是公众号文章链接")
    try:
        return await wn.download_article(body.url.strip())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"下载失败:{e}") from e


@router.post("/collection")
async def collection(body: CollectionBody) -> dict[str, Any]:
    if "appmsgalbum" not in body.url:
        raise HTTPException(status_code=400, detail="这不是合集链接(应含 appmsgalbum)")

    async def _run() -> None:
        await wn.run_collection_task(body.url.strip(), body.max_pages)

    asyncio.create_task(_run())
    return {"ok": True, "message": "合集任务已启动,正在解析文章列表并逐篇下载"}


@router.get("/task")
async def task() -> dict[str, Any]:
    return wn.task_status()
