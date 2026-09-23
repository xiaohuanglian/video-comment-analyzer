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
        name="通用（默认）",
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
            "禁止：把玩笑/玩梗当作核心标签；把个别案例夸大为普遍需求；使用未经验证的疗效/收益承诺。"
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
        decision_keywords=["问题", "困难", "需求", "替代", "付费", "为什么不", "怎么办"],
        noise_markers=["哈哈", "支持", "沙发", "第一", "点赞", "路过", "签到"],
        theme_risk_tokens=["风险", "坑", "骗", "退款", "后悔"],
        theme_difficulty_tokens=["不会", "难", "搞不定", "做不到", "麻烦", "卡住"],
        theme_question_tokens=["怎么", "能不能", "可以", "吗", "如何", "为什么"],
        content_persona="专业、真诚、以解决问题为导向的口吻；具体、不夸大、不硬广。",
        content_platforms=["短视频", "图文", "长文", "工具页"],
        opportunity_templates=[],
        is_builtin=True,
    )


def builtin_profiles() -> Dict[str, ProjectProfile]:
    return {
        "default": _builtin_default(),
    }


DEFAULT_PROFILE_ID = "default"
# Legacy ids from earlier versions map onto the neutral default.
_LEGACY_PROFILE_ALIASES = {"kineo": "default", "generic": "default"}


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