# -*- coding: utf-8 -*-
"""账号策略档案 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from api.services import strategy

router = APIRouter(prefix="/strategy", tags=["strategy"])


class StrategyBody(BaseModel):
    niche: str = ""
    target_audience: str = ""
    monetization: str = ""
    tone_rules: list[str] = []
    forbidden: list[str] = []
    reference_styles: list[str] = []


@router.get("")
async def get_strategy() -> dict[str, Any]:
    return strategy.load() or {"exists": False}


@router.put("")
async def put_strategy(body: StrategyBody) -> dict[str, Any]:
    return strategy.save(body.model_dump())
