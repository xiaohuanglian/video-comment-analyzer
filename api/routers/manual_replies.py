"""Three-platform shortlist for people who reply in the official platform UI."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.services import manual_replies as service

Platform = Literal["bili", "dy", "xhs"]
router = APIRouter(prefix="/manual-replies", tags=["manual-replies"])


class ScreenRequest(BaseModel):
    mode: Literal["ai", "rules"] = "ai"
    profile_id: str = ""
    goal: str = Field(default="", max_length=2000)
    limit: int = Field(default=30, ge=1, le=100)
    days: int = Field(default=30, ge=1, le=365)


class MarkRequest(BaseModel):
    status: Literal["pending", "done", "skipped"]


@router.get("")
def listing(platform: Platform = "bili", status: Literal["pending", "done", "skipped"] = "pending", profile_id: str = "", offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return service.list_items(platform, status, profile_id, offset, limit)


@router.post("/screen")
async def screen(body: ScreenRequest, platform: Platform = "bili"):
    try:
        return service.start(platform, body.mode, body.profile_id, body.goal, body.limit, body.days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{item_id}/mark")
def mark(item_id: str, body: MarkRequest, platform: Platform = "bili"):
    try:
        return service.mark(platform, item_id, body.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="列表条目不存在，请刷新后重试") from exc
