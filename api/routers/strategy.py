# -*- coding: utf-8 -*-
"""账号策略 / 项目档案 API。

一个产品 = 一个档案。这里提供：
- `/api/strategy`        当前档案的账号定位（读写）
- `/api/strategy/profiles` 档案列表 / 新建 / 删除
- `/api/strategy/active`   切换当前档案

为什么「当前档案」要显式切换：不同产品的定位、受众、口吻不能混用，
所以不能让「最近编辑的那个」隐式生效——那会让 A 产品的回复按 B 产品的
口径筛选，而且用户看不出来。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services import onboarding, strategy
from api.services.insight import project_profiles as pp

router = APIRouter(prefix="/strategy", tags=["strategy"])


class StrategyBody(BaseModel):
    profile_id: Optional[str] = None
    niche: str = ""
    target_audience: str = ""
    monetization: str = ""
    tone_rules: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    reference_styles: list[str] = Field(default_factory=list)
    goal: str = ""
    evidence: str = ""
    domain: Optional[str] = None
    research_goal: Optional[str] = None


#: 设置页只需要账号定位这一组；档案里还有整份分类词表、语料上下文，
#: 全量吐给前端既慢又没必要。
_LOCATION_KEYS = (
    "profile_id",
    "name",
    "domain",
    "research_goal",
    "niche",
    "target_audience",
    "monetization",
    "tone_rules",
    "forbidden",
    "reference_styles",
    "goal",
    "evidence",
    "target_scenarios",
    "updated_at",
)


def _location_view(data: dict[str, Any]) -> dict[str, Any]:
    return {k: data.get(k) for k in _LOCATION_KEYS if k in data}


@router.get("")
async def get_strategy(profile_id: Optional[str] = None) -> dict[str, Any]:
    data = _location_view(strategy.load(profile_id))
    if not data:
        return {"exists": False, "active_profile_id": pp.get_active_profile_id(), "profiles": _profile_briefs()}
    data["exists"] = True
    data["active_profile_id"] = pp.get_active_profile_id()
    data["is_active"] = data.get("profile_id") == pp.get_active_profile_id()
    data["profiles"] = _profile_briefs()
    return data


@router.put("")
async def put_strategy(body: StrategyBody) -> dict[str, Any]:
    payload = body.model_dump(exclude={"profile_id"})
    saved = strategy.save(payload, body.profile_id)
    saved["exists"] = True
    saved["active_profile_id"] = pp.get_active_profile_id()
    saved["profiles"] = _profile_briefs()
    return saved


def _profile_briefs() -> list[dict[str, Any]]:
    """列表只给切换 UI 需要的字段，不把整份档案（含大段语料引用）塞进列表。"""
    active = pp.get_active_profile_id()
    out = []
    for profile in pp.list_profiles():
        if profile.is_builtin:
            continue
        out.append(
            {
                "profile_id": profile.profile_id,
                "name": profile.name or profile.profile_id,
                "niche": profile.niche,
                "target_audience": profile.target_audience,
                "is_active": profile.profile_id == active,
                "is_configured": pp.is_configured(profile),
                "updated_at": profile.updated_at,
            }
        )
    return out


class CreateProfileBody(BaseModel):
    name: str = ""
    profile_id: str = ""
    niche: str = ""
    target_audience: str = ""
    domain: str = ""
    research_goal: str = ""


@router.get("/profiles")
async def list_profiles() -> dict[str, Any]:
    return {"active_profile_id": pp.get_active_profile_id(), "profiles": _profile_briefs()}


@router.post("/profiles")
async def create_profile(body: CreateProfileBody) -> dict[str, Any]:
    """新建一个产品档案。新建后**不会**自动切换当前档案，由用户显式确认。"""
    pid = (body.profile_id or "").strip() or strategy._slugify(body.name or body.niche or "")
    if not pid:
        raise HTTPException(status_code=400, detail="请填写产品/账号名称")
    if pp.get_profile(pid) is not None and not pp.get_profile(pid).is_builtin:
        raise HTTPException(status_code=409, detail=f"档案 {pid} 已存在")
    profile = pp.ProjectProfile(
        profile_id=pid,
        name=(body.name or body.niche or pid).strip()[:40],
        niche=body.niche.strip(),
        target_audience=body.target_audience.strip(),
        domain=(body.domain or body.niche).strip(),
        research_goal=(body.research_goal or "").strip(),
    )
    stored = pp.upsert_profile(profile, activate_if_empty=False)
    return {"profile": stored.model_dump(), "active_profile_id": pp.get_active_profile_id()}


class ActiveProfileBody(BaseModel):
    profile_id: str


@router.put("/active")
async def set_active_profile(body: ActiveProfileBody) -> dict[str, Any]:
    try:
        pid = pp.set_active_profile(body.profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"active_profile_id": pid, "profiles": _profile_briefs()}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str) -> dict[str, Any]:
    if not pp.delete_profile(profile_id):
        raise HTTPException(status_code=404, detail="档案不存在（内置档案不可删除）")
    return {"deleted": profile_id, "active_profile_id": pp.get_active_profile_id()}


# --- 引导式建档 ---------------------------------------------------------------
#
# 默认档案中立化之后，新用户第一次用会被「必须先有档案」挡住。这条路把建档
# 压到 3 个问题，并可顺手跑一次切场景，让新用户 2 分钟就能出第一批结果。


class OnboardBody(BaseModel):
    domain: str = ""
    target_audience: str = ""
    research_goal: str = ""
    name: str = ""
    profile_id: str = ""
    activate: bool = True
    run_scenario: bool = False
    scenario_limit: int = 5


@router.get("/onboarding/questions")
async def onboarding_questions() -> dict[str, Any]:
    """建档问卷。只有 3 个必答题——一次问八项会把人劝退。"""
    return {
        "questions": onboarding.questions(),
        "required_count": 3,
        "already_configured": any(pp.is_configured(p) for p in pp.list_profiles()),
        "active_profile_id": pp.get_active_profile_id(),
    }


@router.post("/onboarding")
async def onboard(body: OnboardBody) -> dict[str, Any]:
    try:
        return await onboarding.onboard(
            domain=body.domain,
            target_audience=body.target_audience,
            research_goal=body.research_goal,
            name=body.name,
            profile_id=body.profile_id,
            activate=body.activate,
            run_scenario=body.run_scenario,
            scenario_limit=body.scenario_limit,
        )
    except onboarding.OnboardingIncomplete as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
