# -*- coding: utf-8 -*-
"""费用统计 API:只读,不做任何限制。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from api.services import costs

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("/summary")
async def summary() -> dict[str, Any]:
    """总计/今日/按功能/按模型的消耗汇总;费用按当前价格配置回算。"""
    return costs.summary()


@router.get("/ledger")
async def ledger(limit: int = 100) -> list[dict[str, Any]]:
    """最近的调用记录(新→旧):时间/功能/模型/tokens/耗时/成败。"""
    return costs.ledger(limit)
