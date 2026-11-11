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

from .prompts import (
    PERSONALIZED_VIDEO_KEYWORDS,
    POSITIVE_RESULT_KEYWORDS,
    REALTIME_VIDEO_KEYWORDS,
)

PROFILES_FILE_NAME = "project_profiles.json"

_write_lock = threading.Lock()


class TaxonomyItem(BaseModel):
    """One business-facing category (intent or signal).

    ``key`` is the stable machine value stored in analysis rows; ``label`` is
    what users see. Profiles may rename, reorder or subset the built-in
    vocabulary so the same pipeline reads naturally for any business.
    """

    key: str
    label: str
    description: str = ""


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
    intents: List[TaxonomyItem] = Field(default_factory=list)  # 意图维度（空=内置）
    signals: List[TaxonomyItem] = Field(default_factory=list)  # 信号维度（空=内置）
    decision_keywords: List[str] = Field(default_factory=list)
    noise_markers: List[str] = Field(default_factory=list)
    theme_risk_tokens: List[str] = Field(default_factory=list)
    theme_difficulty_tokens: List[str] = Field(default_factory=list)
    theme_question_tokens: List[str] = Field(default_factory=list)
    realtime_tokens: List[str] = Field(default_factory=list)  # “需实时观察”判定词（空=内置）
    personalized_tokens: List[str] = Field(default_factory=list)  # “需结合个人情况”判定词
    positive_result_tokens: List[str] = Field(default_factory=list)  # “正向结果”判定词
    content_persona: str = ""  # tone/voice for generated content
    content_platforms: List[str] = Field(default_factory=list)
    opportunity_templates: List[Dict[str, Any]] = Field(default_factory=list)
    is_builtin: bool = False


# --- built-in profiles -------------------------------------------------------
# A single domain-neutral default. Projects customize it by creating their own
# profile (see upsert_profile) instead of this tool shipping any vertical-specific
# defaults.


def _builtin_default() -> ProjectProfile:
    """领域中立的占位档案。

    2026-11-11 纠正：这里原先是「AI 教学与分享（默认）」——领域、受众、假设、
    词表全是 AI 内容创作者口径。后果是：一个做母婴/健身/本地服务的用户，
    即使一个字都没填，采集、洞察、选题也按 AI 内容口径跑，结果全是噪音。

    现在这个档案**只提供结构，不预设任何行业**：domain/target_audience 留空，
    `is_configured()` 返回 False，需要用户（或 AI 生成档案）填入真实定位后
    才会被当作有效档案使用。

    为什么仍保留它而不是直接报错：架构里 `resolve_profile()` 需要一个兜底对象，
    且「只看评论结构、不判行业」的纯统计功能（词频、时间分布）不需要档案。
    需要行业口径的功能必须显式调 `require_profile()`。
    """
    return ProjectProfile(
        profile_id="default",
        name="未配置（请先填写你的产品/领域）",
        domain="",
        research_goal="",
        target_audience="",
        forbidden_claims=(
            "不得声称已验证需求、市场规模、付费意愿，除非代码统计直接支持；"
            "不得把玩笑/玩梗当作核心标签；不得把个别案例夸大为普遍需求。"
        ),
        context_compact="（尚未配置项目档案：请先填写你的产品、目标人群与研究目标。）",
        context_full=(
            "（尚未配置项目档案。本档案不含任何行业预设，"
            "因此不应据此推断用户所属领域、需求或利益点。）"
        ),
        # 行业相关的假设一律留空——由用户或 AI 生成档案填入。
        hypotheses={},
        hypothesis_short={},
        hypothesis_rules=(
            "- 只有单一或少样本时，结论必须为 mixed 或 insufficient。\n"
            "- 弱上下文（weak_context）不得支撑结论。\n"
            "- 区分「表达偏好」与「实际行为/付费」。"
        ),
        # 这些是跨行业通用的检索/噪音/疑问信号，与具体卖什么无关，可保留。
        decision_keywords=["怎么", "不会", "教程", "推荐", "效果", "踩坑", "替代", "付费", "为什么不", "值不值"],
        noise_markers=["哈哈", "支持", "沙发", "第一", "点赞", "路过", "签到"],
        theme_risk_tokens=["风险", "坑", "骗", "割韭菜", "后悔"],
        theme_difficulty_tokens=["不会", "难", "搞不定", "学不会", "麻烦", "卡住"],
        theme_question_tokens=["怎么", "能不能", "可以", "吗", "如何", "为什么"],
        realtime_tokens=list(REALTIME_VIDEO_KEYWORDS),
        personalized_tokens=list(PERSONALIZED_VIDEO_KEYWORDS),
        positive_result_tokens=list(POSITIVE_RESULT_KEYWORDS),
        content_persona="",
        content_platforms=[],
        intents=default_intents(),
        signals=default_signals(),
        opportunity_templates=[],
        is_builtin=True,
    )


#: 判断一个档案是否「真的被配置过」。只看用户必须自己填的那几项，
#: 不看词表/模板（那些有通用默认值，填不填都能跑）。
_REQUIRED_PROFILE_FIELDS = ("domain", "target_audience", "research_goal")


def is_configured(profile: Optional[ProjectProfile]) -> bool:
    """档案是否包含真实定位（而非内置占位）。"""
    if profile is None:
        return False
    return all(str(getattr(profile, field, "") or "").strip() for field in _REQUIRED_PROFILE_FIELDS)


class ProfileNotConfigured(RuntimeError):
    """需要行业口径，但当前档案是未配置的占位档案。"""

    def __init__(self, message: str = "") -> None:
        super().__init__(
            message
            or "还没有配置项目档案。请先在「设置 → 项目档案」填写你的产品、目标人群与研究目标"
            "（或用「AI 根据评论生成档案」生成一份），否则采集口径、筛选标准与选题都会失准。"
        )


def require_profile(profile_id: str = "") -> ProjectProfile:
    """取一个**已配置**的档案；未配置则抛 ProfileNotConfigured。

    凡是要按行业判断的功能（评论筛选、洞察、选题、切场景）都应走这里，
    而不是 `get_profile()` —— 后者会静默回落到占位档案，产生看起来正常
    但完全跑偏的结果。
    """
    profile = get_profile(profile_id) if profile_id else None
    if profile is None:
        candidates = [p for p in list_profiles() if is_configured(p)]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise ProfileNotConfigured()
        raise ProfileNotConfigured(
            "有多个已配置的档案，请明确指定要用哪一个：" + "、".join(p.profile_id for p in candidates)
        )
    if not is_configured(profile):
        raise ProfileNotConfigured(
            f"档案「{profile.name}」还缺少 domain / target_audience / research_goal，"
            "填完才能用于按行业口径的分析与筛选。"
        )
    return profile


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


# --- taxonomy (business-facing intents & signals) ----------------------------

def default_intents() -> List[TaxonomyItem]:
    from .labels import INTENT_LABELS

    return [TaxonomyItem(key=k, label=v) for k, v in INTENT_LABELS.items()]


def default_signals() -> List[TaxonomyItem]:
    from .labels import SIGNAL_LABELS
    from .prompts import SIGNAL_ENUM

    return [TaxonomyItem(key=k, label=SIGNAL_LABELS.get(k, k)) for k in SIGNAL_ENUM]


def resolve_intents(profile: Any) -> List[TaxonomyItem]:
    items = list(getattr(profile, "intents", None) or []) if profile is not None else []
    return items or default_intents()


def resolve_signals(profile: Any) -> List[TaxonomyItem]:
    items = list(getattr(profile, "signals", None) or []) if profile is not None else []
    return items or default_signals()


def intent_label_map(profile: Any) -> Dict[str, str]:
    return {item.key: item.label for item in resolve_intents(profile) if item.key}


def signal_label_map(profile: Any) -> Dict[str, str]:
    return {item.key: item.label for item in resolve_signals(profile) if item.key}


def _resolve_tokens(profile: Any, field: str, defaults) -> List[str]:
    items = list(getattr(profile, field, None) or []) if profile is not None else []
    return items if items else list(defaults)


def resolve_realtime_tokens(profile: Any) -> List[str]:
    return _resolve_tokens(profile, "realtime_tokens", REALTIME_VIDEO_KEYWORDS)


def resolve_personalized_tokens(profile: Any) -> List[str]:
    return _resolve_tokens(profile, "personalized_tokens", PERSONALIZED_VIDEO_KEYWORDS)


def resolve_positive_result_tokens(profile: Any) -> List[str]:
    return _resolve_tokens(profile, "positive_result_tokens", POSITIVE_RESULT_KEYWORDS)