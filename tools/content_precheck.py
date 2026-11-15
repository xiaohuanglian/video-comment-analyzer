"""评论请求前的内容闸门。详情由存储入口登记，不额外请求平台。"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
_contents: dict[tuple[str, str], dict[str, Any]] = {}
_decisions: dict[tuple[str, str], bool] = {}


def register_content(platform: str, content_id: str, content: dict[str, Any]) -> None:
    key = (platform, str(content_id))
    _contents[key] = dict(content)
    _decisions.pop(key, None)


async def allow_comments(platform: str, content_id: str) -> bool:
    # 自动化双阶段采集已在父进程完成本轮预审，无需再调模型。
    if os.environ.get("VC_CONTENT_PREFLIGHT", "1") == "0":
        return True
    key = (platform, str(content_id))
    if key in _decisions:
        return _decisions[key]
    content = _contents.get(key)
    if content is None:
        logger.warning("[内容预审] %s/%s 未取得标题详情，暂不采评论", *key)
        return False
    from api.services.outreach.collection_preflight import assess_contents
    from api.services.outreach.reply_automation import _screen_brief

    normalized = dict(content)
    normalized["video_url"] = str(content.get("note_url") or content.get("aweme_url") or content.get("video_url") or "")
    try:
        _, report = await assess_contents({str(content_id): normalized}, _screen_brief(), platform=platform)
        record = report[0]
    except Exception:
        logger.warning("[内容预审] %s/%s 无法判断，请检查账号档案和模型配置，暂不采评论", *key)
        _decisions[key] = False
        return False
    allowed = record["decision"] == "collect"
    _decisions[key] = allowed
    logger.info("[内容预审] %s | %s | %s", record["title"], record["decision"], record["reason"])
    return allowed
