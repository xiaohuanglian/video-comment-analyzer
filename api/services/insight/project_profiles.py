# -*- coding: utf-8 -*-
"""Configurable project profiles (场景/产品档案).

A profile captures everything that used to be hard-coded for one vertical:
research context, hypotheses, prompt rules, report noise/filter tokens and
content-generation persona. Users ship their own profile per product so the
same pipeline works for any domain.

A single domain-neutral default is defined in code; user profiles live in
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
# A single domain-neutral default. Projects customize it by creating their own
# profile (see upsert_profile) instead of this tool shipping any vertical-specific
# defaults.


def _builtin_default() -> ProjectProfile:
    return ProjectProfile(
        profile_id="default",
        name="AI 教学与分享（默认）",
        domain="AI 教学与知识分享",
        research_goal="从 AI 学习者与从业者的真实评论中，发现他们在学习/使用 AI 时的需求、卡点与内容机会。",
        target_audience="想学会用 AI 提升效率的职场人、内容创作者与学生，以及对 AI 好奇的入门者。",
        forbidden_claims="不得声称已验证需求、市场规模、付费意愿或某项 AI 的确定效果，除非代码统计直接支持。",
        context_compact=(
            "研究目标：发现 AI 学习/使用中的需求、卡点与内容选题机会。"
            "禁止：把玩笑/玩梗当作核心标签；把个别案例夸大为普遍需求。"
        ),
        context_full=(
            "研究目标：发现 AI 学习/使用中的需求、卡点与内容机会，并评估产品/内容假设。"
            "禁止：把玩笑/玩梗当作核心标签；把个别案例夸大为普遍需求；把 AI 能力夸大为一定能达成的结果。"
        ),
        hypotheses={
            "H1": "用户在学习或使用 AI 时存在明确、反复出现的卡点（不知道从哪学、工具太多、不知道怎么落地）。",
            "H2": "现有教程/课程/工具无法很好满足：太理论、太零散、跟不上更新或缺少场景示范。",
            "H3": "部分用户愿意为更系统的学习或更好的工具付出时间、注意力或金钱。",
        },
        hypothesis_short={
            "H1": "存在反复出现的 AI 学习/使用卡点",
            "H2": "现有教程/工具不够好",
            "H3": "存在投入/付费意愿",
        },
        hypothesis_rules=(
            "- 只有单一或少样本时，结论必须为 mixed 或 insufficient。\n"
            "- 弱上下文（weak_context）不得支撑结论。\n"
            "- 区分「表达偏好」与「实际行为/付费」。"
        ),
        decision_keywords=["怎么学", "不会用", "教程", "提示词", "工具", "效果", "踩坑", "替代", "付费", "为什么不"],
        noise_markers=["哈哈", "支持", "沙发", "第一", "点赞", "路过", "签到"],
        theme_risk_tokens=["风险", "坑", "骗", "割韭菜", "后悔"],
        theme_difficulty_tokens=["不会", "难", "搞不定", "学不会", "麻烦", "卡住"],
        theme_question_tokens=["怎么", "能不能", "可以", "吗", "如何", "为什么"],
        content_persona="既懂 AI 又能把复杂概念讲明白的老师型创作者口吻；具体、有示范、不夸大、不制造焦虑、不硬推广。",
        content_platforms=["短视频", "图文", "长文", "课程/直播"],
        opportunity_templates=[],
        is_builtin=True,
    )


def builtin_profiles() -> Dict[str, ProjectProfile]:
    return {
        "default": _builtin_default(),
    }


DEFAULT_PROFILE_ID = "default"
# "generic" was an early neutral synonym for the built-in default; keep it as a
# convenience alias. Any other historical id is NOT special-cased — unknown ids
# simply fall back to `default` in resolve_profile(), so old configs still load.
_LEGACY_PROFILE_ALIASES = {"generic": "default"}


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
    pid = _LEGACY_PROFILE_ALIASES.get(pid, pid)
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