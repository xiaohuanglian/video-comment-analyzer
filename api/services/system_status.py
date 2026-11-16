"""Read local connection/policy state. Never log in, crawl, clear guards or send."""

import os
import time
from datetime import datetime

from api.services.json_store import JsonStoreCorruption, read_json
from api.services.llm_config import masked, resolve_llm_config
from api.services.outreach import automation_rules as rules
from tools import crawl_pacing


def snapshot() -> dict:
    model = masked(resolve_llm_config())
    model["connection"] = "not_checked"
    model["environment_override"] = any(os.getenv(key, "").strip() for key in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"))
    cooldowns = crawl_pacing.cooldown_store().snapshot()
    channels = []
    for platform, label, overrides in (
        ("bili", "B 站", {}), ("xhs", "小红书", rules.XHS_CONFIG_OVERRIDES),
        ("dy", "抖音", rules.DY_CONFIG_OVERRIDES),
    ):
        try:
            raw = read_json(rules.store_path_for(platform), default={}, quarantine_corruption=False)
            if not isinstance(raw, dict):
                raise ValueError("状态格式异常")
            cfg = {**rules.DEFAULT_CONFIG, **overrides, **raw.get("config", {})}
            sender = raw.get("sender", {})
            cooldown = cooldowns.get(platform, {})
            remaining = max(0, int(float(cooldown.get("at", 0)) + float(cooldown.get("retry_after_seconds", 0)) - time.time()))
            manual = bool(cooldown.get("manual"))
            pause_until = str(sender.get("pause_until") or "")
            paused = bool(pause_until and datetime.fromisoformat(pause_until).timestamp() > time.time())
            state = "manual_hold" if manual else "cooling" if remaining else "paused" if paused else "disabled" if not cfg.get("enabled") else "not_checked"
            channels.append({"platform": platform, "label": label, "state": state,
                "login": "not_checked", "enabled": bool(cfg.get("enabled")),
                "cooldown_seconds": remaining, "cooldown_code": cooldown.get("code", ""),
                "pause_until": pause_until, "manual_hold": manual,
                "send_policy": {key: cfg.get(key) for key in ("daily_send_limit", "send_interval_seconds", "send_window_start", "send_window_end")},
                "crawl_interval": crawl_pacing.compute_crawl_interval(platform),
                "search_interval": crawl_pacing.compute_crawl_interval(platform, kind="search"),
                "policy_source": "平台默认策略＋已保存的通道配置" if raw.get("config") else "平台默认策略",
            })
        except (JsonStoreCorruption, ValueError, TypeError):
            channels.append({"platform": platform, "label": label, "state": "error", "login": "not_checked",
                             "message": "本地通道状态无法读取，请检查状态文件；尚未确认可用。"})
    return {"model": model, "channels": channels,
            "note": "仅检查本地配置与已有拦截记录。未进行网络探测或登录验证；无拦截记录不代表账号健康。"}
