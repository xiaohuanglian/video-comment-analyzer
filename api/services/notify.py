# -*- coding: utf-8 -*-
"""关键事件推送(飞书自定义机器人)。

定位(P0-3):发送失败/风控预警/登录失效/配额用尽/队列清空——这些事件
此前全部静默,只有打开工作台才能看到。参照 Artalk notify_pusher 的多渠道思路,
先接飞书(webhook 在 .env 配 FEISHU_WEBHOOK_URL);未配置时静默 no-op,
失败绝不影响主流程(与 costs.record 同哲学)。
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

FEISHU_WEBHOOK_URL = (os.environ.get("FEISHU_WEBHOOK_URL") or "").strip()

# 同一 key+同一消息的重复通知冷却(秒);消息变化立即再发
NOTIFY_DEDUPE_SECONDS = 6 * 3600


def configured() -> bool:
    return bool(FEISHU_WEBHOOK_URL)


async def _send_text(text: str) -> bool:
    if not FEISHU_WEBHOOK_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.post(
                FEISHU_WEBHOOK_URL,
                json={"msg_type": "text", "content": {"text": text}},
            )
            return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


async def notify(title: str, lines: list[str]) -> bool:
    """发一条通知。返回是否成功送达(webhook 未配置视为未送达但不报错)。"""
    text = f"【评论工作台·{title}】\n" + "\n".join(str(x) for x in lines if str(x).strip())
    return await _send_text(text)


def should_notify(state: dict[str, Any], key: str, message: str) -> bool:
    """节流判定:同 key+同消息冷却期内只发一次;消息变化立即放行。就地更新 state。

    state 建议 store._state["sender"]["notified"],随 store 持久化。
    """
    now = time.time()
    noted = state.get(key)
    # noted: {"ts": float, "msg": str}
    if isinstance(noted, dict):
        if noted.get("msg") == message and now - float(noted.get("ts") or 0) < NOTIFY_DEDUPE_SECONDS:
            return False
    state[key] = {"ts": now, "msg": message}
    return True
