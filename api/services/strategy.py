# -*- coding: utf-8 -*-
"""账号策略档案：定位 / 受众 / 变现 / 口吻 / 禁区 / 参考账号。

来自 RedBeacon locate skill 方法论（五件事对话摸清），是所有内容生成的策略基座。

**2026-11-11 起这是 `insight.project_profiles` 的兼容门面。**
原先这里自己管一个写死的单文件 `data/strategy/youvibe_account.json`，而分析侧
另有一套 `data/project_profiles.json`：同一个「我是谁、面向谁」要填两遍，两边
不一致时没人知道该信谁。现在一个产品 = 一个档案，账号定位只是档案的一个面，
所有读写都落到同一个存储、同一个 profile_id 上。

保留本模块是因为调用点很多（topics / writer / creator.pipeline /
reply_automation 等），逐个改签名风险大；门面让它们继续工作，同时共享同一份数据。

**教训（别再犯）**：旧 `save()` 只保留 `FIELDS` 白名单里的键，于是「采纳场景」
写进去的 `target_scenarios` 被静默丢弃，接口却返回 `{"ok": true}`——界面显示
已采纳，磁盘上什么都没有。现在保存保留未知字段。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .insight import project_profiles as pp

#: 账号定位相关的字段。保留这个常量是为了兼容（有测试/脚本引用它）。
FIELDS = (
    "niche",
    "target_audience",
    "monetization",
    "tone_rules",
    "forbidden",
    "reference_styles",
    "goal",
    "evidence",
)

_LIST_FIELDS = ("tone_rules", "forbidden", "reference_styles")


def _target(profile_id: Optional[str] = None) -> Optional[pp.ProjectProfile]:
    """定位要读写的档案：显式 id → 当前档案。"""
    pid = (profile_id or "").strip()
    if pid:
        return pp.get_profile(pid)
    return pp.get_active_profile()


def _as_dict(profile: Optional[pp.ProjectProfile]) -> dict[str, Any]:
    if profile is None:
        return {}
    data = profile.model_dump()
    # 内置占位档案不算「已配置」，对外表现为空——否则调用方会拿默认文案当用户定位。
    if profile.is_builtin:
        return {}
    return data


def load(profile_id: Optional[str] = None) -> dict[str, Any]:
    """读当前档案的账号定位（无档案返回空 dict）。"""
    return _as_dict(_target(profile_id))


def save(data: dict[str, Any], profile_id: Optional[str] = None) -> dict[str, Any]:
    """写账号定位。

    - 保留 `data` 里的**未知字段**（如 `target_scenarios`），不再白名单过滤
    - 未指定 `profile_id` 时写到**当前档案**；当前档案不存在则新建一个
    """
    current = _target(profile_id)
    pid = (profile_id or "").strip() or (current.profile_id if current else "")

    merged: dict[str, Any] = dict(current.model_dump()) if current is not None else {}
    for key, value in data.items():
        if value is None:
            continue
        if key in _LIST_FIELDS and isinstance(value, list):
            merged[key] = [str(x).strip() for x in value if str(x).strip()]
        elif isinstance(value, list):
            merged[key] = value
        else:
            merged[key] = value if not isinstance(value, str) else value.strip()
    merged["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if not pid:
        # 一个档案都没有：用定位内容当第一个产品档案。
        pid = _slugify(str(merged.get("niche") or "")) or "profile"
    merged["profile_id"] = pid
    merged.setdefault("name", str(merged.get("niche") or pid)[:40])
    # 账号定位与分析口径同源：没单独填 domain/research_goal 时用定位补上。
    if not str(merged.get("domain") or "").strip():
        merged["domain"] = str(merged.get("niche") or "")
    if not str(merged.get("research_goal") or "").strip():
        merged["research_goal"] = str(merged.get("goal") or "")
    merged["is_builtin"] = False

    stored = pp.upsert_profile(pp.ProjectProfile.model_validate(merged))
    return _as_dict(stored)


def _slugify(text: str) -> str:
    """业务名 → 档案 id。**保留中文**，否则中文业务名全塌成同一个 id 互相覆盖。"""
    out = []
    for ch in (text or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:40]


def exists() -> bool:
    profile = _target()
    return bool(profile is not None and not profile.is_builtin and profile.niche)


def tone_summary(profile_id: Optional[str] = None) -> Optional[str]:
    """给各生成入口的口吻摘要；无档案返回 None。"""
    s = load(profile_id)
    if not s.get("niche"):
        return None
    parts = [f"账号定位:{s['niche']}"]
    if s.get("target_audience"):
        parts.append(f"目标受众:{s['target_audience']}")
    if s.get("tone_rules"):
        parts.append(f"口吻:{';'.join(s['tone_rules'])}")
    if s.get("forbidden"):
        parts.append(f"禁区:{';'.join(s['forbidden'])}")
    if s.get("reference_styles"):
        refs = ";".join(
            r if isinstance(r, str) else f"{r.get('name', '')}({r.get('what', '')})"
            for r in s["reference_styles"]
        )
        parts.append(f"文风参考(只学表达,不搬内容):{refs}")
    return "\n".join(parts)
