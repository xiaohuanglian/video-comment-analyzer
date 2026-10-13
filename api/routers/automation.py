# -*- coding: utf-8 -*-
"""B 站回复自动化 · 监工界面 API。"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services.insight import reply_automation as auto

router = APIRouter(prefix="/automation", tags=["automation"])


class CandidateDecision(BaseModel):
    draft: str = ""


class ConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    auto_draft: Optional[bool] = None
    keywords: Optional[list[str]] = None
    keywords_text: Optional[str] = None
    collect_interval_hours: Optional[int] = None
    max_notes_per_keyword: Optional[int] = None
    max_comments_per_video: Optional[int] = None
    freshness_a_hours: Optional[int] = None
    freshness_b_hours: Optional[int] = None
    max_new_candidates_per_cycle: Optional[int] = None
    daily_send_limit: Optional[int] = None
    send_interval_seconds: Optional[int] = None
    send_jitter_seconds: Optional[int] = None
    send_window_start: Optional[str] = None
    send_window_end: Optional[str] = None


def _store() -> auto.AutomationStore:
    return auto.get_store()


def _funnel(store: auto.AutomationStore) -> dict[str, int]:
    items = store.items
    return {
        "pending_review": sum(1 for i in items if i["status"] == "pending_review"),
        "approved": sum(1 for i in items if i["status"] == "approved"),
        "sent": sum(1 for i in items if i["status"] == "sent"),
        "failed": sum(1 for i in items if i["status"] == "failed"),
        "rejected": sum(1 for i in items if i["status"] == "rejected"),
    }


@router.get("/status")
async def status() -> dict[str, Any]:
    store = _store()
    cfg = store.config
    sender = store.sender_state()
    ok, wait_reason = store.can_send_now()
    return {
        "enabled": cfg.get("enabled", False),
        "config": cfg,
        "funnel": _funnel(store),
        "stats": store._state["stats"],
        "cycle": store._state["cycle"],
        "sender": {
            **sender,
            "can_send": ok,
            "wait_reason": wait_reason,
            "cookie_cached": bool(auto._cached_cookie()),
        },
    }


@router.get("/candidates")
async def candidates(status: str = "pending_review", limit: int = 60) -> list[dict[str, Any]]:
    store = _store()
    items = [i for i in store.items if i["status"] == status]
    items.sort(key=lambda i: (0 if i.get("tier") == "A" else 1, -i.get("like_count", 0)))
    return items[-limit:][::-1]


@router.post("/candidates/{item_id}/approve")
async def approve(item_id: str, body: CandidateDecision) -> dict[str, Any]:
    store = _store()
    item = store.decide(item_id, "approve", draft=body.draft)
    if not item:
        raise HTTPException(status_code=400, detail="条目不存在、已处理或草稿为空")
    return {"ok": True, "item": item}


@router.post("/candidates/{item_id}/reject")
async def reject(item_id: str) -> dict[str, Any]:
    store = _store()
    item = store.decide(item_id, "reject")
    if not item:
        raise HTTPException(status_code=400, detail="条目不存在或已处理")
    return {"ok": True}


@router.post("/candidates/{item_id}/draft")
async def redraft(item_id: str) -> dict[str, Any]:
    store = _store()
    item = store.find(item_id)
    if not item or item["status"] != "pending_review":
        raise HTTPException(status_code=400, detail="条目不存在或已处理")
    draft = await auto.draft_with_llm(item)
    if not draft:
        raise HTTPException(status_code=400, detail="起草失败：模型未配置或调用失败，可手动填写")
    updated = store.update_draft(item_id, draft, source="llm")
    return {"ok": True, "item": updated}


@router.post("/candidates/{item_id}/draft-manual")
async def draft_manual(item_id: str, body: CandidateDecision) -> dict[str, Any]:
    store = _store()
    updated = store.update_draft(item_id, body.draft or "", source="manual")
    if not updated:
        raise HTTPException(status_code=400, detail="条目不存在或已处理")
    return {"ok": True, "item": updated}


@router.post("/collect-now")
async def collect_now() -> dict[str, Any]:
    store = _store()
    if store._state["cycle"].get("running"):
        raise HTTPException(status_code=409, detail="采集周期已在运行")
    asyncio.create_task(auto.run_cycle(store))
    return {"ok": True, "message": "采集周期已启动（后台运行，稍后刷新查看）"}


@router.post("/config")
async def update_config(body: ConfigUpdate) -> dict[str, Any]:
    store = _store()
    partial: dict[str, Any] = {}
    for key, value in body.dict(exclude_none=True).items():
        if key == "keywords_text":
            partial["keywords"] = value
        else:
            partial[key] = value
    cfg = store.update_config(partial)
    return {"ok": True, "config": cfg}


@router.post("/cookie-refresh")
async def cookie_refresh() -> dict[str, Any]:
    try:
        cookie = await auto.refresh_bili_cookie()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)[:200])
    return {"ok": True, "message": f"Cookie 已刷新（{len(cookie)} 字符）"}
