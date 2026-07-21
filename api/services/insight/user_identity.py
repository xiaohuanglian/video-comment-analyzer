# -*- coding: utf-8 -*-
"""User identity helpers for merge and contactability."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .field_mapping import resolve_source_links

_PLACEHOLDER_USERNAME = re.compile(
    r"^(用户\d*|bilibili用户|哔哩哔哩用户|默认用户|匿名用户|未知用户|网友|游客)$",
    re.IGNORECASE,
)


def is_mergeable_username(username: str) -> bool:
    name = (username or "").strip()
    if not name or len(name) <= 1:
        return False
    if _PLACEHOLDER_USERNAME.match(name):
        return False
    if name.isdigit():
        return False
    return True


def user_key(source: Dict[str, Any]) -> Optional[str]:
    user_id = (source.get("user_id") or "").strip()
    if user_id:
        platform = (source.get("platform") or "unknown").strip()
        return f"id:{platform}:{user_id}"

    homepage, _comment_url = resolve_source_links(source)
    if homepage:
        return f"home:{homepage}"

    username = (source.get("username") or "").strip()
    platform = (source.get("platform") or "unknown").strip()
    if is_mergeable_username(username):
        return f"user:{platform}:{username}"
    return None
