# -*- coding: utf-8 -*-
"""YouVibe 数据查询 API(工作台内嵌 youvibe-analytics-query)。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services import youvibe_analytics

router = APIRouter(prefix="/youvibe", tags=["youvibe"])


class QueryItem(BaseModel):
    name: str
    endpoint: str
    params: dict[str, Any] = {}


class QueryRequest(BaseModel):
    queries: list[QueryItem]


@router.get("/endpoints")
async def endpoints() -> dict[str, Any]:
    """列出工作台可用的接口别名及说明文档位置。"""
    return {
        "open": youvibe_analytics.OPEN_ENDPOINTS,
        "admin_only": youvibe_analytics.ADMIN_ENDPOINTS,
        "docs": "tools/youvibe-analytics-query/references/api-map.md",
        "note": "admin_only 接口需管理员凭证,暂不在工作台开放;口径说明见 references/metrics-glossary.md",
    }


@router.post("/query")
async def query(body: QueryRequest) -> dict[str, Any]:
    try:
        return await youvibe_analytics.run_queries(
            [q.model_dump() for q in body.queries]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"查询失败:{e}") from e
