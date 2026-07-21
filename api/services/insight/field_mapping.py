# -*- coding: utf-8 -*-
"""Detect and apply column mappings for comment files."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

from .schemas import FieldMapping

COMMENT_KEYS = (
    "content",
    "comment_text",
    "text",
    "desc",
    "comment",
    "message",
    "评论",
    "评论内容",
    "正文",
)
USERNAME_KEYS = ("nickname", "user_name", "username", "author_name", "用户昵称", "昵称")
USER_ID_KEYS = ("user_id", "author_id", "uid", "用户id")
HOMEPAGE_KEYS = ("user_homepage_url", "homepage", "profile_url", "用户主页")
COMMENT_URL_KEYS = ("comment_url", "comment_link", "评论链接")
VIDEO_TITLE_KEYS = ("video_title", "title", "content_title", "视频标题", "标题")
CREATOR_KEYS = ("creator_name", "up_name", "author_name", "up主", "博主")
PLATFORM_KEYS = ("platform", "source_platform", "平台")

CREATOR_TYPE_FROM_PATH = {
    "健身类": "普通健身类",
    "运康类": "运动康复类",
    "生活方式类": "生活方式类",
}


def _match_column(columns: List[str], candidates: tuple[str, ...]) -> Optional[str]:
    lowered = {col: col.lower().strip() for col in columns}
    for candidate in candidates:
        for col, low in lowered.items():
            if low == candidate.lower():
                return col
    for candidate in candidates:
        for col, low in lowered.items():
            if candidate.lower() in low:
                return col
    return None


def infer_creator_type_from_path(source_path: str) -> str:
    for key, value in CREATOR_TYPE_FROM_PATH.items():
        if key in source_path:
            return value
    return "未知"


def detect_field_mapping(columns: List[str], source_path: str = "") -> FieldMapping:
    comment_col = _match_column(columns, COMMENT_KEYS)
    if not comment_col:
        raise ValueError("无法自动识别评论正文列，请手动选择")
    return FieldMapping(
        comment_text=comment_col,
        username=_match_column(columns, USERNAME_KEYS),
        user_id=_match_column(columns, USER_ID_KEYS),
        user_homepage_url=_match_column(columns, HOMEPAGE_KEYS),
        comment_url=_match_column(columns, COMMENT_URL_KEYS),
        video_title=_match_column(columns, VIDEO_TITLE_KEYS),
        creator_name=_match_column(columns, CREATOR_KEYS),
        creator_type=infer_creator_type_from_path(source_path) if source_path else None,
        platform=None,
    )


def row_value(row: Mapping[str, Any], column: Optional[str]) -> str:
    if not column:
        return ""
    value = row.get(column)
    if value is None:
        return ""
    return str(value).strip()


_BV_PATTERN = re.compile(r"(BV[\w]+)", re.IGNORECASE)


def infer_platform_from_source(source: Mapping[str, Any]) -> str:
    platform = str(source.get("platform") or "").strip().lower()
    if platform in {"xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"}:
        return platform
    source_file = str(source.get("source_file") or "")
    if "bilibili.com" in source_file.lower() or _BV_PATTERN.search(source_file):
        return "bili"
    raw = source.get("raw_data") or {}
    if raw.get("video_id") and raw.get("comment_id"):
        return "bili"
    return platform or "unknown"


def derive_bilibili_links(platform: str, user_id: str, video_id: str, comment_id: str) -> tuple[str, str]:
    homepage = ""
    comment_url = ""
    if platform in {"bili", "unknown"} and (user_id or video_id):
        if user_id:
            homepage = f"https://space.bilibili.com/{user_id}"
        if video_id and comment_id:
            comment_url = f"https://www.bilibili.com/video/{video_id}#reply{comment_id}"
    return homepage, comment_url


def resolve_source_links(source: Mapping[str, Any]) -> tuple[str, str]:
    homepage = str(source.get("user_homepage_url") or "").strip()
    comment_url = str(source.get("comment_url") or "").strip()
    if homepage and comment_url:
        return homepage, comment_url

    platform = infer_platform_from_source(source)
    user_id = str(source.get("user_id") or "").strip()
    raw = source.get("raw_data") or {}
    video_id = str(raw.get("video_id") or raw.get("note_id") or raw.get("aweme_id") or "")
    comment_id = str(raw.get("comment_id") or raw.get("id") or "")
    if not video_id:
        match = _BV_PATTERN.search(str(source.get("source_file") or ""))
        if match:
            video_id = match.group(1)
    derived_homepage, derived_comment = derive_bilibili_links(platform, user_id, video_id, comment_id)
    return homepage or derived_homepage, comment_url or derived_comment
