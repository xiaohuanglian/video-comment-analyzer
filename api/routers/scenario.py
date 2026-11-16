"""产品触达场景：生成关键词、验证评论、人工采纳。"""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/strategy", tags=["strategy"])

class ScenarioRequest(BaseModel):
    """切场景：从产品定位推导可切入的具体场景。

    定位与受众留空时回落到当前账号定位/项目档案——不回落任何内置行业。
    """

    positioning: str = ""
    audience: str = ""
    value: str = ""
    existing_hint: str = ""  # 用户已想到的场景（用来让模型避开雷同）
    verify: bool = True      # 是否用现有语料验证"真有人这么问吗"
    source: str = "bili"
    limit: int = 5


def _scenario_positioning(body: "ScenarioRequest") -> tuple[str, str, str]:
    """解析定位/受众/价值，优先级：请求 > 账号定位 > 项目档案。"""
    from api.services.insight.project_profiles import get_profile, is_configured
    from api.services.strategy import load as load_strategy

    positioning = (body.positioning or "").strip()
    audience = (body.audience or "").strip()
    value = (body.value or "").strip()

    if positioning and audience:
        return positioning, audience, value

    # 定位与分析口径现在同属一份档案，直接按当前档案取，不再两处回落。
    s = load_strategy() or {}
    positioning = positioning or str(s.get("niche") or s.get("domain") or "").strip()
    audience = audience or str(s.get("target_audience") or "").strip()
    value = value or str(s.get("goal") or s.get("research_goal") or "").strip()

    if not (positioning and audience):
        pid = str(s.get("profile_id") or "").strip()
        try:
            profile = get_profile(pid) if pid else None
        except Exception:  # noqa: BLE001
            profile = None
        if profile is not None and is_configured(profile):
            positioning = positioning or str(profile.domain or profile.niche or "").strip()
            audience = audience or str(profile.target_audience or "").strip()
            value = value or str(profile.research_goal or profile.goal or "").strip()

    return positioning, audience, value


@router.post("/scenario/plan")
async def scenario_plan(body: ScenarioRequest) -> dict[str, Any]:
    """从产品定位推导 5 个可切入场景（六轴：身份/困境/替代/触发/否认/邻近）。

    回答的是「除了我想到的那几个，还有哪些地方能打」——
    不是从产品功能反推，而是从用户的生活情境出发。
    """
    from api.services.outreach import scenario as scenario_svc

    positioning, audience, value = _scenario_positioning(body)
    if not positioning:
        raise HTTPException(
            status_code=400,
            detail="需要先填写产品/内容定位（或到「设置 → 账号定位」填 niche）",
        )
    if not audience:
        raise HTTPException(
            status_code=400,
            detail="还需要目标人群——只有定位没有受众，切出来的场景会太泛",
        )

    try:
        scenarios, warnings = await scenario_svc.generate_scenarios(
            positioning=positioning,
            audience=audience,
            value=value,
            existing_hint=body.existing_hint,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"场景生成失败：{exc}") from exc

    scenarios = scenarios[: max(1, min(body.limit, 8))]
    return {
        "positioning": positioning,
        "audience": audience,
        "axes": [{"key": k, "label": label, "description": desc} for k, label, desc in scenario_svc.AXES],
        "scenarios": [s.to_dict() for s in scenarios],
        "warnings": warnings,
        "verified": False,
        "message": "已生成场景。下一步用「验证」跑一次真实语料，确认这些场景真的有人这么问。",
    }


@router.post("/scenario/verify")
async def scenario_verify(body: dict[str, Any]) -> dict[str, Any]:
    """用已采集的评论验证场景：命中多少条、多少独立用户、涉及多少视频。

    数字全部由代码回算（模型只提场景与关键词，不许报数字）。
    没有语料时如实返回「无信号」而不是假装验证过。
    """
    from api.services.outreach import scenario as scenario_svc
    from api.services.outreach.reply_automation import BULK_COMMENT_DIR, read_collected

    items = body.get("scenarios")
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="没有可验证的场景")

    scenarios = scenario_svc.parse_scenarios({"scenarios": items})
    if not scenarios:
        raise HTTPException(status_code=400, detail="场景缺少名称或关键词，无法验证")

    rows, _video_map = read_collected(BULK_COMMENT_DIR)
    if not rows:
        return {
            "scenarios": [s.to_dict() for s in scenarios],
            "stats": {
                "total": len(scenarios),
                "verified": 0,
                "warnings": ["data/comments 下没有已采集评论，先去「采集」页爬一批再验证"],
            },
            "corpus_size": 0,
        }

    verified = scenario_svc.verify_scenarios(scenarios, rows)
    ranked = scenario_svc.rank_scenarios(verified)
    return {
        "scenarios": [s.to_dict() for s in ranked],
        "stats": scenario_svc.summary_stats(ranked),
        "corpus_size": len(rows),
    }


@router.post("/scenario/adopt")
async def scenario_adopt(body: dict[str, Any]) -> dict[str, Any]:
    """把选中的场景记进账号定位，后续评论筛选会围绕它们判断。"""
    from api.services import strategy as strategy_mod

    items = body.get("scenarios")
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="scenarios 必须是数组")

    chosen = []
    for item in items[:5]:
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            chosen.append(
                {
                    "name": str(item.get("name"))[:60],
                    "axis": str(item.get("axis") or ""),
                    "trigger": str(item.get("trigger") or "")[:120],
                    "keywords": [str(k)[:40] for k in (item.get("keywords") or [])][:6],
                }
            )
    if not chosen:
        raise HTTPException(status_code=400, detail="没有有效的场景可采纳")

    profile_id = str(body.get("profile_id") or "").strip() or None
    current = strategy_mod.load(profile_id) or {}
    updated = {**current, "target_scenarios": chosen}
    saved = strategy_mod.save(updated, profile_id)
    # 回读确认真的落盘了——此前接口返回 ok 但字段被白名单丢弃，是假成功。
    persisted = strategy_mod.load(str(saved.get("profile_id") or profile_id)).get("target_scenarios") or []
    return {
        "ok": len(persisted) == len(chosen),
        "profile_id": saved.get("profile_id"),
        "target_scenarios": persisted,
    }
