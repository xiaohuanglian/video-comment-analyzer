# -*- coding: utf-8 -*-
"""Configurable project profiles (场景/产品档案).

A profile captures everything that used to be hard-coded for the fitness
scenario: research context, hypotheses, prompt rules, report noise/filter
tokens and content-generation persona. Users can ship their own profile per
product so the same pipeline works for any domain.

Built-in profiles are defined in code; user profiles live in
``data/project_profiles.json`` and are merged over the built-ins by id.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .paths import DATA_DIR

PROFILES_FILE_NAME = "project_profiles.json"

_write_lock = threading.Lock()


class ProjectProfile(BaseModel):
    profile_id: str
    name: str
    domain: str = ""
    research_goal: str = ""
    target_audience: str = ""
    forbidden_claims: str = ""
    context_compact: str = ""  # short context injected into extraction prompt
    context_full: str = ""  # richer context for the research agent
    hypotheses: Dict[str, str] = Field(default_factory=dict)  # H1..H3 full text
    hypothesis_short: Dict[str, str] = Field(default_factory=dict)
    hypothesis_rules: str = ""  # extra rule lines for the research system prompt
    decision_keywords: List[str] = Field(default_factory=list)
    noise_markers: List[str] = Field(default_factory=list)
    theme_risk_tokens: List[str] = Field(default_factory=list)
    theme_difficulty_tokens: List[str] = Field(default_factory=list)
    theme_question_tokens: List[str] = Field(default_factory=list)
    content_persona: str = ""  # tone/voice for generated content
    content_platforms: List[str] = Field(default_factory=list)
    opportunity_templates: List[Dict[str, Any]] = Field(default_factory=list)
    is_builtin: bool = False


# --- built-in profiles -------------------------------------------------------

_KINEO_COMPACT = (
    "研究目标：健身内容评论中的训练障碍、行动差距与产品机会。"
    "目标用户：跟练/自重训练新手到进阶。"
    "禁止：把玩梗当核心标签；把难度直接当成需要系统代规划的证明；医疗确诊措辞。"
)

_KINEO_RULES = (
    "- H1：只有部分已行动样本且缺未行动对照时，结论必须 mixed 或 insufficient。\n"
    "- H2：方向判断/动作标准问题最多构成中等支持，不等于必须实时视觉识别。\n"
    "- H3：记不住动作/不知道下一步/需要降阶只能构成弱支持或证据不足。"
)


def _builtin_kineo() -> ProjectProfile:
    return ProjectProfile(
        profile_id="kineo",
        name="健身内容（默认）",
        domain="健身",
        research_goal="从健身内容评论中发现训练障碍、行动差距与产品机会。",
        target_audience="跟练/自重训练新手到进阶用户。",
        forbidden_claims="把玩梗当核心标签；把难度直接当成需要系统代规划的证明；医疗确诊措辞。",
        context_compact=_KINEO_COMPACT,
        context_full=_KINEO_COMPACT,
        hypotheses={
            "H1": (
                "用户本身已经具有一定训练动力，不需要产品解决「是否开始训练」，"
                "而是需要解决训练过程和训练质量问题。"
            ),
            "H2": (
                "部分用户仅靠单向视频无法解决问题，需要动作质量即时反馈、"
                "个性化判断或交互式指导。"
            ),
            "H3": (
                "部分用户不希望自己反复判断训练安排和调整方式，"
                "希望把规划、进阶、降阶和调整交给 Agent。"
            ),
        },
        hypothesis_short={
            "H1": "已有动力，需过程/质量支持",
            "H2": "单向视频不够，需即时反馈/个性化",
            "H3": "希望 Agent 规划/进阶/调整",
        },
        hypothesis_rules=_KINEO_RULES,
        decision_keywords=["方向", "判断", "动作", "困难", "问题", "障碍", "疼痛", "规划", "积液", "甩泥"],
        noise_markers=["打卡", "day", "第九天", "第四天", "d5", "d6", "bgm", "收藏", "点赞", "真的有用"],
        theme_risk_tokens=["疼", "痛", "不适", "关节"],
        theme_difficulty_tokens=["做不了", "不行", "困难", "好难", "累", "不到位"],
        theme_question_tokens=["可以", "能不能", "吗", "要做几次", "每天"],
        content_persona="专业、克制、以解决问题为导向的健身教练口吻；不夸大效果，不做医疗建议。",
        content_platforms=["短视频", "图文", "长文", "工具页"],
        opportunity_templates=[
            {
                "match": ["方向", "判断"],
                "name": "训练前方向判断辅助",
                "problem": "用户不知道该练哪一侧，或担心方向判断错误。",
                "experiment": "让用户上传一段标准姿态视频，只返回方向提示并明确非医疗诊断；验证其是否比自行判断更可靠。",
            },
            {
                "match": ["动作", "质控", "发力", "反馈"],
                "name": "单动作执行反馈",
                "problem": "用户找不到发力感，或无法判断一个具体动作是否做对。",
                "experiment": "只选择一个动作，对比普通视频组与反馈组的完成率、主观确定感和纠错次数。",
            },
            {
                "match": ["安排", "规划", "下一步", "降阶"],
                "name": "单次训练下一步建议",
                "problem": "用户不知道当前动作之后该练什么，或是否需要降阶。",
                "experiment": "只提供一次训练的下一步建议，验证用户是否采纳及是否减少反复搜索。",
            },
        ],
        is_builtin=True,
    )


def _builtin_generic() -> ProjectProfile:
    return ProjectProfile(
        profile_id="generic",
        name="通用（自定义产品）",
        domain="",
        research_goal="从目标人群的真实评论中发现需求、痛点与产品机会。",
        target_audience="待填写：你的产品或内容所服务的人群。",
        forbidden_claims="不得声称已验证需求、市场规模、付费意愿或疗效，除非代码统计直接支持。",
        context_compact=(
            "研究目标：从评论中发现目标人群的真实需求、痛点与机会。"
            "禁止：把玩笑/玩梗当作核心标签；把个别案例夸大为普遍需求。"
        ),
        context_full=(
            "研究目标：从评论中发现目标人群的真实需求、痛点与机会，并评估产品假设。"
            "禁止：把玩笑/玩梗当作核心标签；把个别案例夸大为普遍需求；使用未经验证的医疗/效果承诺。"
        ),
        hypotheses={
            "H1": "用户存在明确、反复出现的未满足需求（而非一次性好奇）。",
            "H2": "现有替代方案（竞品/自建方案/人工服务）无法很好地满足该需求。",
            "H3": "部分用户愿意为更好的解决方案付出成本（时间、学习或金钱）。",
        },
        hypothesis_short={
            "H1": "存在反复出现的未满足需求",
            "H2": "现有替代方案不够好",
            "H3": "存在付费/投入意愿",
        },
        hypothesis_rules=(
            "- 只有单一或少样本时，结论必须为 mixed 或 insufficient。\n"
            "- 弱上下文（weak_context）不得支撑结论。\n"
            "- 区分「表达偏好」与「实际行为/付费」。"
        ),
        decision_keywords=["问题", "困难", "需求", "替代", "付费", "为什么不"],
        noise_markers=["打卡", "沙发", "第一", "哈哈", "支持", "点赞", "沙发"],
        theme_risk_tokens=["风险", "坑", "骗", "退款"],
        theme_difficulty_tokens=["不会", "难", "搞不定", "做不到", "麻烦"],
        theme_question_tokens=["怎么", "能不能", "可以", "吗", "如何"],
        content_persona="专业、真诚、以解决问题为导向的口吻；具体、不夸大、不硬广。",
        content_platforms=["短视频", "图文", "长文", "工具页"],
        opportunity_templates=[],
        is_builtin=True,
    )


def builtin_profiles() -> Dict[str, ProjectProfile]:
    return {
        "kineo": _builtin_kineo(),
        "generic": _builtin_generic(),
    }


DEFAULT_PROFILE_ID = "kineo"


# --- storage -----------------------------------------------------------------

def _profiles_path() -> Path:
    from . import paths

    return paths.DATA_DIR / PROFILES_FILE_NAME


def _read_profiles_file() -> List[ProjectProfile]:
    path = _profiles_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    entries = raw.get("profiles") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []
    out: List[ProjectProfile] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        try:
            out.append(ProjectProfile.model_validate(item))
        except Exception:
            continue
    return out


def _write_profiles_file(profiles: List[ProjectProfile]) -> None:
    path = _profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "profiles": [p.model_dump() for p in profiles],
    }
    with _write_lock:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


def _custom_profiles() -> Dict[str, ProjectProfile]:
    return {p.profile_id: p for p in _read_profiles_file() if p.profile_id}


def list_profiles() -> List[ProjectProfile]:
    merged = builtin_profiles()
    for pid, profile in _custom_profiles().items():
        merged[pid] = profile
    return sorted(merged.values(), key=lambda p: (not p.is_builtin, p.profile_id))


def get_profile(profile_id: str) -> Optional[ProjectProfile]:
    pid = (profile_id or "").strip()
    if not pid:
        return None
    custom = _custom_profiles().get(pid)
    if custom is not None:
        return custom
    return builtin_profiles().get(pid)


def upsert_profile(profile: ProjectProfile) -> ProjectProfile:
    """Create or update a user profile (stored in the data dir)."""
    if not profile.profile_id.strip():
        raise ValueError("profile_id 不能为空")
    stored = profile.model_copy(update={"is_builtin": False})
    custom = _custom_profiles()
    custom[stored.profile_id] = stored
    _write_profiles_file(list(custom.values()))
    return stored


def delete_profile(profile_id: str) -> bool:
    pid = (profile_id or "").strip()
    custom = _custom_profiles()
    if pid not in custom:
        return False
    custom.pop(pid)
    _write_profiles_file(list(custom.values()))
    return True


def resolve_profile(config: Any) -> ProjectProfile:
    """Resolve the effective profile for a run, applying per-run overrides."""
    pid = (getattr(config, "project_id", "") or "").strip() if config is not None else ""
    profile = get_profile(pid) if pid else None
    if profile is None:
        profile = builtin_profiles()[DEFAULT_PROFILE_ID]
    if config is None:
        return profile
    compact = (getattr(config, "project_context_compact", "") or "").strip()
    full = (getattr(config, "project_context", "") or "").strip()
    if compact or full:
        profile = profile.model_copy(
            update={
                "context_compact": compact or profile.context_compact,
                "context_full": full or profile.context_full,
            }
        )
    return profile