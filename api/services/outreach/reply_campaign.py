"""回复任务的产品与目标快照。任务启动后不再依赖全局当前档案。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from api.services import strategy
from api.services.insight.project_profiles import get_profile, is_configured


def make_campaign(profile_id: str, goal: str = "", mode: str = "recommend") -> dict[str, Any]:
    profile_id = str(profile_id or "").strip()
    profile = get_profile(profile_id) if profile_id else None
    if profile is None or not is_configured(profile):
        raise ValueError("请明确选择已配置的产品档案，再启动回复任务")
    data = strategy.load(profile.profile_id)
    snapshot = {key: data.get(key) for key in (
        "profile_id", "name", "niche", "domain", "target_audience", "research_goal", "goal",
        "context_compact", "context_full", "tone_rules", "forbidden", "forbidden_claims",
        "reference_styles", "evidence", "target_scenarios", "updated_at",
        "product_offerings", "product_source_urls", "product_verified_at",
    ) if data.get(key) is not None}
    goal = str(goal or snapshot.get("goal") or profile.research_goal or "").strip()
    if not goal:
        raise ValueError("请填写这次回复希望达成的目标")
    if mode not in ("recommend", "trust"):
        raise ValueError("回复方式仅支持 recommend / trust")
    key = hashlib.sha256(json.dumps({"screening_policy": 3, "profile_id": profile.profile_id, "goal": goal, "mode": mode, "snapshot": snapshot}, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return {"campaign_key": key, "profile_id": profile.profile_id, "profile_name": profile.name,
            "reply_goal": goal[:2000], "reply_mode": mode, "profile_snapshot": snapshot}


def campaign_prompt(campaign: dict[str, Any]) -> str:
    import json

    mode = campaign.get("reply_mode", "recommend")
    instruction = (
        "先回应对方的具体需要。只有产品确实解决这个需要时，才自然提一次本产品名称，"
        "说清产品里的哪一种做法或内容能帮到他；不硬塞品牌，不写空泛广告。"
        "与本产品没有具体关联的人不应为凑数入选。"
        if mode == "recommend" else
        "本次以建立信任为目标，提供具体帮助，不主动提产品名。"
    )
    offerings = (campaign.get("profile_snapshot") or {}).get("product_offerings") or []
    if offerings:
        instruction += ("\n筛选输出额外包含 need_quote 和 matched_offering：need_quote 必须是对方原评论的连续原文，"
                        "matched_offering 必须从 product_offerings 的 name 原样选择。不能用共同提到AI来代替需求与能力的具体匹配。"
                        "浏览、收藏、找灵感也可以匹配，不要求人人立即创作；不要假定每条都有公开提示词或能独立发布作品。")
    return ("本条回复的固定任务（只依据这份档案，不混用其他产品）：\n"
            + json.dumps(campaign, ensure_ascii=False, default=str)
            + "\n" + instruction
            + "\n不编造产品功能、效果或可用性。不得放链接、联系方式，或要求私信/关注；发送仍需人工审核。")


def product_source_outdated(item: dict[str, Any]) -> bool:
    profile = get_profile(str(item.get('profile_id') or '')) if item.get('profile_id') else None
    if profile is None:
        return False
    verified_at = getattr(profile, 'product_verified_at', '')
    return bool(verified_at and (item.get('profile_snapshot') or {}).get('product_verified_at') != verified_at)


def ensure_current_product_source(item: dict[str, Any]) -> None:
    if product_source_outdated(item):
        raise ValueError('产品公开能力已更新，这条草稿使用旧依据；请按当前产品重新筛选后审核')
