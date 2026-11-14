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
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..growth.operating_models import GrowthContext
from ..json_store import lock_for, read_json, write_json
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

    model_config = ConfigDict(extra="allow")


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

    # --- 账号定位（原 api/services/strategy.py 的字段，2026-11-11 合并进来）---
    #
    # 为什么合并：原先「账号定位」和「项目档案」是两套并行存储、两套 ID，
    # 同一件事（我是谁、面向谁）要填两遍，而且两个地方不一致时没人知道该信谁。
    # 一个产品 = 一个档案，定位与分析口径是同一个档案的两面。
    niche: str = ""
    monetization: str = ""
    tone_rules: List[str] = Field(default_factory=list)
    forbidden: List[str] = Field(default_factory=list)
    reference_styles: List[str] = Field(default_factory=list)
    goal: str = ""
    evidence: str = ""
    target_scenarios: List[Dict[str, Any]] = Field(default_factory=list)
    growth_context: GrowthContext = Field(default_factory=GrowthContext)
    updated_at: str = ""

    # 2026-11-11：允许未知字段**原样保留**。
    # 教训：这里原先没有 extra，而 strategy.save() 又只保留白名单里的 8 个键，
    # 结果「采纳场景」写入的 target_scenarios 在保存时被静默丢弃，接口却返回
    # {"ok": true}——界面显示已采纳，磁盘上什么都没有，是假成功。
    # 任何新增字段（插件、实验开关）都不该因为没加进模型就消失。
    model_config = ConfigDict(extra="allow")


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

#: 用户可能只填了「账号定位」那一组（niche/goal），也可能只填了分析口径那一组
#: （domain/research_goal）。两组都算「配置过」，缺一组时用另一组补齐判定。
_ALTERNATE_FIELDS = {
    "domain": ("niche", "name"),
    "research_goal": ("goal",),
}


def is_configured(profile: Optional[ProjectProfile]) -> bool:
    """档案是否包含真实定位（而非内置占位）。"""
    if profile is None or getattr(profile, "is_builtin", False):
        return False
    for field in _REQUIRED_PROFILE_FIELDS:
        values = (field,) + _ALTERNATE_FIELDS.get(field, ())
        if not any(str(getattr(profile, f, "") or "").strip() for f in values):
            return False
    return True


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
#: 「我自己的自媒体账号」这份档案的 id。
#:
#: 2026-11-14 纠正：这份档案是在「单档案时代」从 data/strategy/youvibe_account.json
#: 迁过来的，迁移代码把文件名当成了 id，于是你自媒体的账号档案被叫成 youvibe——
#: 而 youvibe 是造浪 YouVibe 这个产品（BP 里的产品），两件事被同一个名字拴在一起，
#: 档案下拉里才会显示成「AI 创业者（自媒体账号） · youvibe」。
#: 现在：产品归「造浪」档案，账号归这份「我的」（name 仍是「AI 创业者（自媒体账号）」）。
MY_ACCOUNT_PROFILE_ID = "我的"

# "generic" was an early neutral synonym for the built-in default; keep it as a
# convenience alias. Unknown ids are NOT special-cased — they simply fall back to
# `default` in resolve_profile(), so old configs still load.
# "youvibe" 是上面那份账号档案的历史 id（迁移遗留），重命名后继续可解析，
# 老的 run/文案配置不会因为改名而丢档案。
_LEGACY_PROFILE_ALIASES = {"generic": "default", "youvibe": MY_ACCOUNT_PROFILE_ID}


# --- storage -----------------------------------------------------------------
#
# 一个产品 = 一个档案。所有档案同住 `data/project_profiles.json`，结构：
#   {"version": 2, "active_profile_id": "youvibe", "profiles": [...]}
#
# `active_profile_id` 是**可切换的当前档案**——不同产品的定位、受众、口吻
# 绝不能混用，所以「当前用哪个」必须是显式状态，而不是某个全局默认值。
#
# 2026-11-11 之前这里是无锁的 `write_text`，且策略档案另存于
# `data/strategy/youvibe_account.json`（单文件、单档案、save 只保留白名单字段，
# 导致采纳的场景被静默丢弃）。现在统一走 json_store：加锁读改写 + 原子写 +
# 损坏不静默。

PROFILES_FILE_VERSION = 2
#: 旧版策略档案位置（单档案时代）。首次读取时自动迁移为多档案中的一个。
LEGACY_STRATEGY_FILE = "strategy/youvibe_account.json"


class ActiveProfileMissing(RuntimeError):
    """有档案但没有指定当前档案，且无法唯一推断。"""


def _profiles_path() -> Path:
    from . import paths

    return paths.DATA_DIR / PROFILES_FILE_NAME


def _legacy_strategy_path() -> Path:
    from . import paths

    return paths.DATA_DIR / LEGACY_STRATEGY_FILE


def _read_raw() -> Dict[str, Any]:
    """读整个文件（含 active_profile_id），顺手做一次旧数据迁移。"""
    path = _profiles_path()
    with lock_for(path):
        data = read_json(path, default={}, expect=dict)
        if not data:
            data = _migrate_legacy_strategy() or {}
        if "profiles" not in data and isinstance(data, list):
            data = {"version": PROFILES_FILE_VERSION, "profiles": data}
    return data


def _write_raw(data: Dict[str, Any]) -> None:
    path = _profiles_path()
    with lock_for(path):
        payload = dict(data)
        payload["version"] = PROFILES_FILE_VERSION
        payload.setdefault("profiles", [])
        write_json(path, payload)


def _short_name(text: str, limit: int = 24) -> str:
    """从定位里取一个能当档案名的短句（按标点切，不硬截断）。"""
    cleaned = (text or "").strip()
    for sep in ("，", ",", "：", ":", "。", "；", ";", "\n"):
        if sep in cleaned:
            head = cleaned.split(sep)[0].strip()
            if head:
                cleaned = head
                break
    return cleaned[:limit] or "未命名档案"


def _migrate_legacy_strategy() -> Optional[Dict[str, Any]]:
    """把单档案时代的 `strategy/youvibe_account.json` 迁成第一个项目档案。

    只在还没有 project_profiles.json 时执行；旧文件保留不动（可回溯），
    但不再被读取。返回迁移后的完整文件内容。
    """
    legacy = _legacy_strategy_path()
    if not legacy.exists():
        return None
    try:
        raw = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or not raw.get("niche"):
        return None

    niche = str(raw.get("niche") or "")
    profile = {
        "profile_id": MY_ACCOUNT_PROFILE_ID,
        # 名字只取定位的第一个短句：整段定位有 60+ 字，直接截断会断在半句上，
        # 在档案列表里看起来像是数据坏了。
        "name": _short_name(niche),
        "niche": str(raw.get("niche") or ""),
        "target_audience": str(raw.get("target_audience") or ""),
        "monetization": str(raw.get("monetization") or ""),
        "tone_rules": [str(x) for x in (raw.get("tone_rules") or [])],
        "forbidden": [str(x) for x in (raw.get("forbidden") or [])],
        "reference_styles": [str(x) for x in (raw.get("reference_styles") or [])],
        "goal": str(raw.get("goal") or ""),
        "evidence": str(raw.get("evidence") or ""),
        "target_scenarios": raw.get("target_scenarios") or [],
        "domain": str(raw.get("niche") or ""),
        "research_goal": str(raw.get("goal") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
    }
    data = {
        "version": PROFILES_FILE_VERSION,
        "active_profile_id": MY_ACCOUNT_PROFILE_ID,
        "profiles": [profile],
        "migrated_from": str(legacy.name),
    }
    _write_raw(data)
    return data


def _parse_profile(item: Any) -> Optional[ProjectProfile]:
    if not isinstance(item, dict):
        return None
    try:
        return ProjectProfile.model_validate(item)
    except Exception:  # noqa: BLE001 — 单条坏档案不该让整个列表不可用
        return None


def _custom_profiles() -> Dict[str, ProjectProfile]:
    out: Dict[str, ProjectProfile] = {}
    for item in _read_raw().get("profiles") or []:
        profile = _parse_profile(item)
        if profile is not None and profile.profile_id:
            out[profile.profile_id] = profile
    return out


def list_profiles() -> List[ProjectProfile]:
    merged = builtin_profiles()
    for pid, profile in _custom_profiles().items():
        merged[pid] = profile
    return sorted(merged.values(), key=lambda p: (p.is_builtin, p.profile_id))


def get_profile(profile_id: str) -> Optional[ProjectProfile]:
    pid = (profile_id or "").strip()
    if not pid:
        return None
    pid = _LEGACY_PROFILE_ALIASES.get(pid, pid)
    custom = _custom_profiles().get(pid)
    if custom is not None:
        return custom
    return builtin_profiles().get(pid)


def get_active_profile_id() -> str:
    """当前档案 id；没有则返回空串（不猜）。"""
    data = _read_raw()
    pid = str(data.get("active_profile_id") or "").strip()
    if pid:
        return pid
    configured = [p.profile_id for p in _custom_profiles().values() if is_configured(p)]
    return configured[0] if len(configured) == 1 else ""


def set_active_profile(profile_id: str) -> str:
    """切换当前档案。不同产品不能混用，所以这个动作必须显式发生。"""
    pid = (profile_id or "").strip()
    if not pid:
        raise ValueError("profile_id 不能为空")
    pid = _LEGACY_PROFILE_ALIASES.get(pid, pid)
    if pid not in _custom_profiles():
        raise KeyError(f"档案不存在：{pid}")
    with lock_for(_profiles_path()):
        data = _read_raw()
        data["active_profile_id"] = pid
        _write_raw(data)
    return pid


def get_active_profile() -> Optional[ProjectProfile]:
    """取当前档案；未显式指定且无法唯一推断时返回 None（调用方决定报错还是降级）。"""
    pid = get_active_profile_id()
    return get_profile(pid) if pid else None


def upsert_profile(profile: ProjectProfile) -> ProjectProfile:
    """Create or update a user profile (stored in the data dir).

    未指定 `updated_at` 时自动打时间戳；保存时**保留未知字段**（见
    ProjectProfile.model_config 的说明）。
    """
    if not profile.profile_id.strip():
        raise ValueError("profile_id 不能为空")
    stored = profile.model_copy(
        update={
            "is_builtin": False,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    with lock_for(_profiles_path()):
        data = _read_raw()
        rows = [item for item in (data.get("profiles") or []) if isinstance(item, dict)]
        rows = [item for item in rows if str(item.get("profile_id") or "") != stored.profile_id]
        rows.append(stored.model_dump())
        data["profiles"] = rows
        # 第一个被创建的档案自动成为当前档案，避免「建好了却没在用」。
        if not str(data.get("active_profile_id") or "").strip():
            data["active_profile_id"] = stored.profile_id
        _write_raw(data)
    return stored


def delete_profile(profile_id: str) -> bool:
    pid = (profile_id or "").strip()
    with lock_for(_profiles_path()):
        data = _read_raw()
        rows = [item for item in (data.get("profiles") or []) if isinstance(item, dict)]
        kept = [item for item in rows if str(item.get("profile_id") or "") != pid]
        if len(kept) == len(rows):
            return False
        data["profiles"] = kept
        if str(data.get("active_profile_id") or "") == pid:
            remaining = [str(item.get("profile_id") or "") for item in kept if item.get("profile_id")]
            data["active_profile_id"] = remaining[0] if remaining else ""
        _write_raw(data)
    return True


def resolve_profile(config: Any) -> ProjectProfile:
    """Resolve the effective profile for a run, applying per-run overrides."""
    pid = (getattr(config, "project_id", "") or "").strip() if config is not None else ""
    profile = get_profile(pid) if pid else None
    if profile is None:
        profile = get_active_profile() or builtin_profiles()[DEFAULT_PROFILE_ID]
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
