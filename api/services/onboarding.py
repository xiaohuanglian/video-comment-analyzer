# -*- coding: utf-8 -*-
"""引导式建档：3 个问题 → 一份可用档案 → 顺带跑一次切场景。

## 为什么需要它

2026-11-11 把内置档案中立化之后（不再预设任何行业），新用户第一次打开
系统时，所有需要「我是谁、面向谁」的功能都会明确报 `ProfileNotConfigured`。
这是对的——不能替用户假设行业——但体验上等于"必须先手填一整页表单才能用"。

所以这里提供一条最短路径：问 3 个问题，填出档案的**必填三件套**
（domain / target_audience / research_goal），立刻可以跑分析、筛选和选题。

## 为什么是 3 个而不是 8 个

档案一共十来个字段，但只有三个是"没有就跑不动"的：

1. 你做什么（domain）——决定分类口径与选题方向
2. 面向谁（target_audience）——决定评论是不是"你的"评论
3. 想搞清楚什么（research_goal）——决定报告回答什么问题

其余字段（口吻、禁区、参考风格、变现场景…）都可以后面慢慢补，
填了更好，不填不阻塞。**一次问完八项，用户会直接关掉页面。**
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .insight import project_profiles as pp

QUESTIONS: List[Dict[str, str]] = [
    {
        "key": "domain",
        "question": "你在做什么产品 / 账号？",
        "hint": "一句话说清业务，不用写公司名。例：同城鲜花配送 / 给新手的 AI 视频教程",
        "placeholder": "如：同城鲜花配送，主打当天送达",
    },
    {
        "key": "target_audience",
        "question": "你最想服务谁？",
        "hint": "具体到人群和处境，越具体筛得越准。例：想送花但不懂花、怕买错的男性",
        "placeholder": "如：想送花但不懂花的男性，怕买错被嫌弃",
    },
    {
        "key": "research_goal",
        "question": "想从评论里搞清楚什么？",
        "hint": "一句话说清你这次的疑问。例：他们选花时卡在哪一步",
        "placeholder": "如：他们选花时最纠结什么，为什么最后没下单",
    },
]

_REQUIRED = ("domain", "target_audience", "research_goal")


class OnboardingIncomplete(ValueError):
    """三个必答问题没答全。"""


def questions() -> List[Dict[str, str]]:
    return [dict(q) for q in QUESTIONS]


def build_profile(
    *,
    domain: str,
    target_audience: str,
    research_goal: str,
    name: str = "",
    profile_id: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> pp.ProjectProfile:
    """把 3 个答案组装成一份档案（不做任何行业假设，全部来自用户原话）。"""
    values = {
        "domain": (domain or "").strip(),
        "target_audience": (target_audience or "").strip(),
        "research_goal": (research_goal or "").strip(),
    }
    missing = [q["question"] for q in QUESTIONS if not values[q["key"]]]
    if missing:
        raise OnboardingIncomplete("还需要回答：" + "、".join(missing))

    pid = (profile_id or "").strip() or _slug(values["domain"])
    profile = pp.ProjectProfile(
        profile_id=pid,
        name=(name or values["domain"]).strip()[:40],
        domain=values["domain"],
        # 账号定位与分析口径同源：三问答完就能用，不要求用户再填一遍。
        niche=values["domain"],
        target_audience=values["target_audience"],
        research_goal=values["research_goal"],
        goal=values["research_goal"],
        context_compact=f"业务：{values['domain']}；目标人群：{values['target_audience']}",
        context_full=(
            f"业务：{values['domain']}\n"
            f"目标人群：{values['target_audience']}\n"
            f"本次研究目标：{values['research_goal']}"
        ),
    )
    if extra:
        merged = {**profile.model_dump(), **extra}
        profile = pp.ProjectProfile.model_validate(merged)
    return profile


def _slug(text: str) -> str:
    """把业务名转成档案 id。

    **必须保留中文**：业务名几乎都是中文，只留 ascii 会让每个中文产品都
    变成同一个 `"profile"`，第二个产品直接覆盖第一个（正是多档案要防的事）。
    """
    out = []
    for ch in (text or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out).strip("-")[:40]
    return slug or "profile"


async def onboard(
    *,
    domain: str,
    target_audience: str,
    research_goal: str,
    name: str = "",
    profile_id: str = "",
    extra: Optional[Dict[str, Any]] = None,
    activate: bool = True,
    run_scenario: bool = False,
    scenario_limit: int = 5,
    complete_fn: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """建档 → （可选）切场景。返回结构化结果，任何一步失败都不静默。

    切场景依赖模型网关；网关不可用时**建档照常成功**，只把失败如实回报，
    不能让"顺手试一下"把主流程也拖挂。
    """
    profile = build_profile(
        domain=domain,
        target_audience=target_audience,
        research_goal=research_goal,
        name=name,
        profile_id=profile_id,
        extra=extra,
    )
    if not profile.profile_id or profile.profile_id in {p.profile_id for p in pp.list_profiles() if p.is_builtin}:
        profile = pp.ProjectProfile.model_validate({**profile.model_dump(), "profile_id": _slug(profile.domain)})

    stored = pp.upsert_profile(profile)
    if activate:
        pp.set_active_profile(stored.profile_id)

    result: Dict[str, Any] = {
        "profile": stored.model_dump(),
        "active_profile_id": pp.get_active_profile_id(),
        "scenarios": None,
        "scenario_error": "",
        "next_steps": [],
    }

    if run_scenario:
        try:
            from .topics import scenario as scenario_svc

            scenarios, warnings = await scenario_svc.generate_scenarios(
                positioning=stored.niche or stored.domain,
                audience=stored.target_audience,
                value=stored.research_goal,
                complete_fn=complete_fn,
            )
            scenarios = scenarios[: max(1, min(scenario_limit, 8))]
            result["scenarios"] = {
                "items": [s.to_dict() for s in scenarios],
                "warnings": warnings,
                "verified": False,
            }
        except Exception as exc:  # noqa: BLE001 — 建档已完成，切场景失败不该回滚
            result["scenario_error"] = f"场景生成失败（不影响建档）：{exc}"

    result["next_steps"] = [
        "去「采集」页爬一批评论（或用已有的）",
        "去「评论洞察」跑一次分析，档案口径会自动生效",
        "用「切场景」验证哪些切入角度真的有人这么问",
    ]
    return result
