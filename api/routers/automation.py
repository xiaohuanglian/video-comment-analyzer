# -*- coding: utf-8 -*-
"""B 站回复自动化 · 监工界面 API。"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services.outreach import reply_automation as auto

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
            "account": auto.cached_account_info(),
            "login_flow": store._state["sender"].get("login_flow") or {"running": False, "message": ""},
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
    try:
        item = store.decide(item_id, "approve", draft=body.draft)
    except ValueError as exc:  # 相似度闸拦截
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=400, detail="条目不存在、已处理或草稿为空")
    # 批准后立刻告知阻塞项，避免「批了却没反应」的无声状态
    warnings: list[str] = []
    if not store.config.get("enabled"):
        warnings.append("已批准，但自动化总开关未启动——点右上角「启动自动化」后才会发送")
    if not auto._cached_cookie():
        warnings.append("B 站登录 Cookie 未就绪——启动后首次采集会弹出扫码窗口，扫一次即恢复")
    return {"ok": True, "item": item, "warnings": warnings}


@router.post("/candidates/{item_id}/retract")
async def retract(item_id: str) -> dict[str, Any]:
    store = _store()
    item = store.retract(item_id)
    if not item:
        raise HTTPException(status_code=400, detail="条目不存在或不在已批准状态")
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


class ScreenRequest(BaseModel):
    max_candidates: int = 50
    auto_draft: bool = True


@router.post("/candidates/bulk-approve")
async def bulk_approve() -> dict[str, Any]:
    """批量批准全部 LLM 精筛且已有草稿的待审条目(规则筛遗留与无草稿的不动)。"""
    store = _store()
    approved, skipped, skipped_similar = store.bulk_approve_llm_screened()
    return {"ok": True, "approved": approved, "skipped_no_draft": skipped, "skipped_similar": skipped_similar}


@router.post("/candidates/bulk-reject")
async def bulk_reject() -> dict[str, Any]:
    """一键拒绝全部旧规则筛的待审条目(仅限 screened_by != llm 的遗留项)。"""
    store = _store()
    n = store.bulk_reject_rules_screened()
    return {"ok": True, "rejected": n}


@router.post("/screen-collected")
async def screen_collected(body: ScreenRequest) -> dict[str, Any]:
    """从手动批量采集的存量数据(data/comments)里筛目标用户 + LLM 起草。"""
    store = _store()
    if store._state["cycle"].get("running"):
        raise HTTPException(status_code=409, detail="已有筛选/采集任务在运行")

    async def _run() -> None:
        await auto.screen_collected(
            store, max_candidates=body.max_candidates, auto_draft=body.auto_draft
        )

    asyncio.create_task(_run())
    return {"ok": True, "message": f"已从存量数据开始筛选(上限 {body.max_candidates} 条),后台运行,稍后刷新待批准"}


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


@router.post("/bili-login")
async def bili_login() -> dict[str, Any]:
    """打开可见浏览器扫码恢复 B 站登录(后台运行,状态见 /status 的 sender.login_flow)。"""
    store = _store()
    flow = store._state["sender"].get("login_flow") or {}
    if flow.get("running"):
        raise HTTPException(status_code=409, detail="登录窗口已开启,请先完成或等它超时")

    async def _run() -> None:
        store._state["sender"]["login_flow"] = {"running": True, "message": "登录窗口已打开,请在弹出的浏览器里扫码"}
        store.save()
        try:
            await auto.login_bili_qrcode()
            store._state["sender"]["login_flow"] = {"running": False, "message": "登录成功,Cookie 已生效"}
            store._state["sender"]["last_error"] = ""
            store.save()
        except Exception as exc:  # noqa: BLE001
            store._state["sender"]["login_flow"] = {"running": False, "message": f"登录未完成:{str(exc)[:120]}"}
            store.save()

    asyncio.create_task(_run())
    return {"ok": True, "message": "登录窗口已打开,请在弹出的浏览器里扫码(3 分钟内完成)"}


@router.post("/cookie-refresh")
async def cookie_refresh() -> dict[str, Any]:
    try:
        cookie = await auto.refresh_bili_cookie()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)[:200])
    return {"ok": True, "message": f"Cookie 已刷新（{len(cookie)} 字符）"}


class HumanTouchRequest(BaseModel):
    pass


@router.post("/candidates/{item_id}/human-touch")
async def human_touch(item_id: str) -> dict[str, Any]:
    """AI 味检测:对草稿逐句扫机器痕迹(姿态/结构/用词/内容/群发味),出报告不改稿。

    检测维度参考风物执守·XY 操盘系统 xy-human-touch 的公开思路(自研实现)。
    """
    store = _store()
    item = store.find(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    draft = (item.get("draft") or "").strip()
    if not draft:
        raise HTTPException(status_code=400, detail="该条目没有草稿")

    system = """你是B站评论回复的 AI 味质检员。对草稿逐句扫描,找出像机器写的痕迹,按原文顺序报告。命中才报,干净就明说干净。每处一行:级别(🔴严重/⚠️轻度)+ 引原句(≤20字)+ 问题 + 一句修改方向。最后给一行总评。不重写全文。

检测维度:
1 姿态:替读者编错想法再否定;「不是X而是Y」翻案连用;每段收金句;升维收尾(本质上/归根结底);全篇没有一处不确定或踩坑自白(太权威=太假)
2 结构:钩子+痛点+承诺式开场;匀速排比/三点式万能结构;句句等长;结尾祝福或求互动;堵死所有反驳(有人会说…但是…)
3 用词:固定连接词堆叠(然而/事实上/值得注意的是);翻译腔(进行X/作为/基于);大词无数字(赋能/闭环/底层逻辑);编造的精确细节(没量过的数字)
4 内容:正确的废话(没有一步明天能照做);无细节的「我有个朋友」故事;承诺句(跟着做你也能/月入X)
5 群发味:亲/家人们;全员同款腔;一眼群发的热情"""
    user = f"对方评论:{item.get('comment_text','')}\n\n待检草稿:\n{draft}"
    try:
        from api.services.llm import complete

        report = await complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2, timeout=90, feature="human_touch",
        ) or "(检测无返回)"
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"检测调用失败:{e}") from e
    return {"ok": True, "item_id": item_id, "report": report.strip()}


@router.post("/candidates/refresh-engagement")
async def refresh_engagement() -> dict[str, Any]:
    """回采已发回复在B站的实时互动(点赞/被回复数/楼中楼预览),写入条目。"""
    store = _store()
    result = await auto.refresh_sent_engagement(store)
    return result
