# -*- coding: utf-8 -*-
"""评论区回复自动化 · 监工界面 API（B 站 + 小红书双通道，platform 查询参数区分）。"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.services.outreach import reply_automation as auto

router = APIRouter(prefix="/automation", tags=["automation"])


class CandidateDecision(BaseModel):
    draft: str = ""


class ConfigUpdate(BaseModel):
    profile_id: Optional[str] = None
    reply_goal: Optional[str] = None
    reply_mode: Optional[str] = None
    enabled: Optional[bool] = None
    auto_draft: Optional[bool] = None
    keywords: Optional[list[str]] = None
    keywords_text: Optional[str] = None
    note_urls: Optional[list[str]] = None
    note_urls_text: Optional[str] = None
    collect_mode: Optional[str] = None
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
    sender_pause_hours: Optional[int] = None
    # 热评通道（根评论）：开关、每周期配额、竞争判定阈值
    hot_comment_enabled: Optional[bool] = None
    hot_comment_max_per_cycle: Optional[int] = None
    hot_comment_min_play: Optional[int] = None
    hot_comment_cold_comments: Optional[int] = None
    hot_comment_crowd_multiple: Optional[float] = None
    hot_comment_crowd_floor: Optional[int] = None
    hot_comment_open_ratio: Optional[float] = None
    hot_comment_min_sample: Optional[int] = None
    hot_comment_max_silence_hours: Optional[int] = None


def _store(platform: str = "bili") -> auto.AutomationStore:
    if platform not in auto.PLATFORMS:
        raise HTTPException(status_code=400, detail=f"不支持的平台：{platform}（可选 {', '.join(auto.PLATFORMS)}）")
    return auto.get_store(platform)


def _matches_profile(item: dict[str, Any], profile_id: str) -> bool:
    return not profile_id or (not item.get("profile_id") if profile_id == "__unbound__" else item.get("profile_id") == profile_id)


def _funnel(store: auto.AutomationStore, profile_id: str = "") -> dict[str, int]:
    items = [it for it in store.items if _matches_profile(it, profile_id)]
    return {
        "pending_review": sum(1 for i in items if i["status"] == "pending_review"),
        "approved": sum(1 for i in items if i["status"] == "approved"),
        # 2026-11-11：sending 原先不在统计里——卡住的条目在监工台上完全不可见。
        "sending": sum(1 for i in items if i["status"] == "sending"),
        "sent": sum(1 for i in items if i["status"] == "sent"),
        "failed": sum(1 for i in items if i["status"] == "failed"),
        "rejected": sum(1 for i in items if i["status"] == "rejected"),
    }


@router.get("/status")
async def status(platform: str = "bili", profile_id: str = "") -> dict[str, Any]:
    store = _store(platform)
    cfg = store.config
    sender = store.sender_state()
    ok, wait_reason = store.can_send_now()
    return {
        "platform": store.platform,
        "enabled": cfg.get("enabled", False),
        "config": cfg,
        "funnel": _funnel(store, profile_id),
        "stats": store._state["stats"],
        "cycle": store._state["cycle"],
        "sender": {
            **sender,
            "can_send": ok,
            "wait_reason": wait_reason,
            # bili：缓存 Cookie 状态；xhs：依赖本机已登录的 CDP 浏览器
            "cookie_cached": bool(auto._cached_cookie()) if store.platform == "bili" else None,
            "account": auto.cached_account_info() if store.platform == "bili" else {},
            "login_flow": store._state["sender"].get("login_flow") or {"running": False, "message": ""},
        },
    }


@router.get("/candidates")
async def candidates(status: str = "pending_review", limit: int = 60, platform: str = "bili", profile_id: str = "") -> list[dict[str, Any]]:
    store = _store(platform)
    items = [i for i in store.items if i["status"] == status and _matches_profile(i, profile_id)]
    items.sort(key=lambda i: (-i.get("worth", 0), 0 if i.get("tier") == "A" else 1, -i.get("like_count", 0)))
    from api.services.outreach.reply_campaign import product_source_outdated

    return [{**item, "product_source_outdated": product_source_outdated(item)} for item in items[:max(1, min(limit, 1000))]]


@router.post("/candidates/{item_id}/approve")
async def approve(item_id: str, body: CandidateDecision, platform: str = "bili") -> dict[str, Any]:
    store = _store(platform)
    existing = store.find(item_id)
    if existing and not existing.get("profile_id"):
        raise HTTPException(status_code=400, detail="历史条目未记录产品归属，请选择产品重新筛选后再批准")
    try:
        item = store.decide(item_id, "approve", draft=body.draft)
    except ValueError as exc:  # 相似度闸 / 小红书硬校验拦截
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=400, detail="条目不存在、已处理或草稿为空")
    # 批准后立刻告知阻塞项，避免「批了却没反应」的无声状态
    warnings: list[str] = []
    if not store.config.get("enabled"):
        warnings.append("已批准，但自动化总开关未启动——点右上角「启动自动化」后才会发送")
    if store.platform == "xhs":
        warnings.append("小红书发送依赖本机已登录小红书的浏览器（CDP 调试端口）保持开启")
    elif store.platform == "dy":
        warnings.append("抖音发送依赖本机已登录抖音的浏览器（CDP 调试端口）保持开启")
    elif not auto._cached_cookie():
        warnings.append("B 站登录 Cookie 未就绪——启动后首次采集会弹出扫码窗口，扫一次即恢复")
    return {"ok": True, "item": item, "warnings": warnings}


@router.post("/candidates/{item_id}/retract")
async def retract(item_id: str, platform: str = "bili") -> dict[str, Any]:
    store = _store(platform)
    item = store.retract(item_id)
    if not item:
        raise HTTPException(status_code=400, detail="条目不存在或不在已批准状态")
    return {"ok": True, "item": item}


@router.post("/candidates/{item_id}/reject")
async def reject(item_id: str, platform: str = "bili") -> dict[str, Any]:
    store = _store(platform)
    item = store.decide(item_id, "reject")
    if not item:
        raise HTTPException(status_code=400, detail="条目不存在或已处理")
    return {"ok": True}


@router.post("/candidates/{item_id}/draft")
async def redraft(item_id: str, platform: str = "bili") -> dict[str, Any]:
    store = _store(platform)
    item = store.find(item_id)
    if not item or item["status"] != "pending_review":
        raise HTTPException(status_code=400, detail="条目不存在或已处理")
    if not item.get("profile_snapshot"):
        raise HTTPException(status_code=400, detail="历史条目没有产品档案快照，请选择产品重新筛选，不能按全局档案重写")
    from api.services.outreach.reply_campaign import product_source_outdated

    if product_source_outdated(item):
        raise HTTPException(status_code=400, detail="产品公开能力已更新，请按当前产品重新筛选，不能用旧依据重写")
    draft = await auto.draft_with_llm(item)
    if not draft:
        raise HTTPException(status_code=400, detail="起草失败：模型未配置或调用失败，可手动填写")
    updated = store.update_draft(item_id, draft, source="llm")
    return {"ok": True, "item": updated}


@router.post("/candidates/{item_id}/draft-manual")
async def draft_manual(item_id: str, body: CandidateDecision, platform: str = "bili") -> dict[str, Any]:
    store = _store(platform)
    updated = store.update_draft(item_id, body.draft or "", source="manual")
    if not updated:
        raise HTTPException(status_code=400, detail="条目不存在或已处理")
    return {"ok": True, "item": updated}


@router.post("/candidates/{item_id}/attachments")
async def add_attachment(item_id: str, request: Request, platform: str = "bili", filename: str = "图片") -> dict[str, Any]:
    from api.services.outreach import reply_attachments as attachments

    store = _store(platform)
    item = store.find(item_id)
    if not item or item.get("status") != "pending_review":
        raise HTTPException(status_code=400, detail="只有待审草稿可以添加图片；已批准条目请先撤回")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > attachments.MAX_BYTES:
            raise HTTPException(status_code=413, detail="单张图片最多8MB")
    try:
        metadata = await asyncio.to_thread(attachments.inspect_image, bytes(content), filename)
        # 上传过程中可能已被批准，读取后再次确认；随后修改和保存之间不让出事件循环。
        item = store.find(item_id)
        if not item or item.get("status") != "pending_review":
            raise ValueError("条目状态已改变，请先撤回批准再编辑附件")
        existing = item.get("attachments") or []
        if len(existing) >= attachments.MAX_IMAGES:
            raise ValueError("一条回复最多添加3张图片")
        if any(a.get("attachment_id") == metadata["attachment_id"] for a in existing):
            raise ValueError("这张图片已经添加")
        attachments.store_image(bytes(content), metadata)
        item["attachments"] = [*existing, metadata]
        store.save()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "item": item}


@router.get("/candidates/{item_id}/attachments/{attachment_id}")
async def get_attachment(item_id: str, attachment_id: str, platform: str = "bili"):
    from api.services.outreach.reply_attachments import image_path

    item = _store(platform).find(item_id)
    metadata = next((a for a in (item or {}).get("attachments", []) if a.get("attachment_id") == attachment_id), None)
    if not metadata:
        raise HTTPException(status_code=404, detail="图片附件不存在")
    try:
        path = image_path(metadata)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片文件不存在，请重新添加")
    return FileResponse(path, media_type=metadata["mime_type"], filename=metadata.get("original_name") or path.name, content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.delete("/candidates/{item_id}/attachments/{attachment_id}")
async def remove_attachment(item_id: str, attachment_id: str, platform: str = "bili") -> dict[str, Any]:
    store = _store(platform)
    item = store.find(item_id)
    if not item or item.get("status") != "pending_review":
        raise HTTPException(status_code=400, detail="只有待审草稿可以修改图片；请先撤回批准")
    item["attachments"] = [a for a in item.get("attachments", []) if a.get("attachment_id") != attachment_id]
    store.save()
    return {"ok": True, "item": item}


class ScreenRequest(BaseModel):
    profile_id: str = ""
    reply_goal: str = ""
    reply_mode: str = "recommend"
    max_candidates: int = 50
    auto_draft: bool = True
    source: str = "both"  # both=双目录合并(默认) | bulk=手动批量(data/comments) | cycle=自动周期(各平台目录)


@router.post("/candidates/bulk-approve")
async def bulk_approve(platform: str = "bili", profile_id: str = "") -> dict[str, Any]:
    """批量批准全部 LLM 精筛且已有草稿的待审条目(规则筛遗留与无草稿的不动)。"""
    store = _store(platform)
    if not profile_id or profile_id == "__unbound__":
        raise HTTPException(status_code=400, detail="请先选择产品，批量批准仅作用于该产品")
    approved, skipped, skipped_similar = store.bulk_approve_llm_screened(profile_id=profile_id)
    return {"ok": True, "approved": approved, "skipped_no_draft": skipped, "skipped_similar": skipped_similar}


@router.post("/candidates/bulk-reject")
async def bulk_reject(platform: str = "bili", profile_id: str = "") -> dict[str, Any]:
    """一键拒绝全部旧规则筛的待审条目(仅限 screened_by != llm 的遗留项)。"""
    store = _store(platform)
    if not profile_id:
        raise HTTPException(status_code=400, detail="请明确选择产品或历史条目，批量拒绝仅作用于该范围")
    n = store.bulk_reject_rules_screened(profile_id=profile_id)
    return {"ok": True, "rejected": n}


@router.post("/screen-collected")
async def screen_collected(body: ScreenRequest, platform: str = "bili") -> dict[str, Any]:
    """从手动批量采集的存量数据里筛目标用户 + LLM 起草。"""
    store = _store(platform)
    if store._state["cycle"].get("running"):
        raise HTTPException(status_code=409, detail="已有筛选/采集任务在运行")

    from api.services.outreach.reply_campaign import make_campaign

    try:
        campaign = make_campaign(body.profile_id, body.reply_goal, body.reply_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def _run() -> None:
        from api.services.outreach.reply_automation import BULK_COMMENT_DIR, comment_dir_for

        source_dir = (
            comment_dir_for(store.platform) if body.source == "cycle"
            else BULK_COMMENT_DIR if body.source == "bulk"
            else None  # both:双目录合并
        )
        await auto.screen_collected(
            store, max_candidates=body.max_candidates, auto_draft=body.auto_draft,
            source_dir=source_dir, campaign=campaign,
        )

    asyncio.create_task(_run())
    return {"ok": True, "message": f"已从存量数据开始筛选(上限 {body.max_candidates} 条),后台运行,稍后刷新待批准"}


@router.post("/collect-now")
async def collect_now(mode: str = "", platform: str = "bili", body: Optional[ScreenRequest] = None) -> dict[str, Any]:
    """立即跑一轮采集。mode 可临时覆盖采集模式：list(竞品清单)/search(关键词扫描)。"""
    store = _store(platform)
    if store._state["cycle"].get("running"):
        raise HTTPException(status_code=409, detail="采集周期已在运行")
    if mode and mode not in ("list", "search"):
        raise HTTPException(status_code=400, detail="mode 仅支持 list / search")
    from api.services.outreach.reply_campaign import make_campaign

    try:
        campaign = make_campaign(body.profile_id if body else str(store.config.get("profile_id") or ""),
                                 body.reply_goal if body else str(store.config.get("reply_goal") or ""),
                                 body.reply_mode if body else str(store.config.get("reply_mode") or "recommend"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(auto.run_cycle(store, mode_override=mode, campaign=campaign))
    return {"ok": True, "message": "采集周期已启动（后台运行，稍后刷新查看）"}


@router.post("/config")
async def update_config(body: ConfigUpdate, platform: str = "bili") -> dict[str, Any]:
    store = _store(platform)
    partial: dict[str, Any] = {}
    for key, value in body.dict(exclude_none=True).items():
        if key == "keywords_text":
            partial["keywords"] = value
        elif key == "note_urls_text":
            partial["note_urls"] = value
        else:
            partial[key] = value
    try:
        cfg = store.update_config(partial)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "config": cfg}


@router.post("/sender-resume")
async def sender_resume(platform: str = "bili") -> dict[str, Any]:
    """人工解除停损暂停（确认账号没问题后手动恢复发送）。"""
    store = _store(platform)
    store.clear_pause()
    return {"ok": True, "message": "已解除发送暂停"}


@router.post("/bili-login")
async def bili_login() -> dict[str, Any]:
    """打开可见浏览器扫码恢复 B 站登录(后台运行,状态见 /status 的 sender.login_flow)。"""
    store = _store("bili")
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
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc
    return {"ok": True, "message": f"Cookie 已刷新（{len(cookie)} 字符）"}


class HumanTouchRequest(BaseModel):
    pass


@router.post("/candidates/{item_id}/human-touch")
async def human_touch(item_id: str, platform: str = "bili") -> dict[str, Any]:
    """AI 味检测:对草稿逐句扫机器痕迹(姿态/结构/用词/内容/群发味),出报告不改稿。

    检测维度参考风物执守·XY 操盘系统 xy-human-touch 的公开思路(自研实现)。
    """
    store = _store(platform)
    item = store.find(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    draft = (item.get("draft") or "").strip()
    if not draft:
        raise HTTPException(status_code=400, detail="该条目没有草稿")

    platform_name = {"xhs": "小红书", "dy": "抖音"}.get(store.platform, "B站")
    system = f"""你是{platform_name}评论回复的 AI 味质检员。对草稿逐句扫描,找出像机器写的痕迹,按原文顺序报告。命中才报,干净就明说干净。每处一行:级别(🔴严重/⚠️轻度)+ 引原句(≤20字)+ 问题 + 一句修改方向。最后给一行总评。不重写全文。

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
async def refresh_engagement(platform: str = "bili") -> dict[str, Any]:
    """回采已发回复在B站的实时互动(点赞/被回复数/楼中楼预览),写入条目。"""
    store = _store(platform)
    if store.platform != "bili":
        raise HTTPException(status_code=400, detail="互动回采仅支持 B 站通道（小红书/抖音发送即验，不额外读平台）")
    result = await auto.refresh_sent_engagement(store)
    return result
