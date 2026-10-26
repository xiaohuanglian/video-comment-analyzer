# -*- coding: utf-8 -*-
"""账号策略档案:定位/受众/变现/口吻/禁区/参考账号。

来自 RedBeacon locate skill 方法论(五件事对话摸清),是所有内容生成的策略基座。
档案文件:data/strategy/youvibe_account.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRATEGY_DIR = PROJECT_ROOT / "data" / "strategy"
STRATEGY_FILE = STRATEGY_DIR / "youvibe_account.json"

FIELDS = ("niche", "target_audience", "monetization", "tone_rules", "forbidden", "reference_styles", "goal", "evidence")


def load() -> dict[str, Any]:
    if not STRATEGY_FILE.exists():
        return {}
    try:
        return json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(data: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for k in FIELDS:
        v = data.get(k)
        if isinstance(v, list):
            cleaned[k] = [str(x).strip() for x in v if str(x).strip()]
        elif v is not None:
            cleaned[k] = str(v).strip()
    cleaned["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    STRATEGY_FILE.write_text(json.dumps(cleaned, ensure_ascii=False, indent=1), encoding="utf-8")
    return cleaned


def exists() -> bool:
    return bool(load().get("niche"))


def tone_summary() -> Optional[str]:
    """给各生成入口的口吻摘要;无档案返回 None。"""
    s = load()
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
