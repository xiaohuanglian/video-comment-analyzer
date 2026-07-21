# -*- coding: utf-8 -*-
"""Normalize crawler rows into stable, analysis-ready contracts."""

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from ..schemas.analysis import Comment, Content, Dataset, DatasetStatus


PLATFORMS = {"xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"}


def _first(row: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    text = str(value).strip()
    if not text:
        return 0
    if text.startswith("http://") or text.startswith("https://"):
        return 0
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def _as_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number)
    except (TypeError, ValueError, OSError):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None


def infer_platform(source_path: str, rows: Iterable[Mapping[str, Any]]) -> str:
    path_parts = set(Path(source_path).parts)
    for platform in PLATFORMS:
        if platform in path_parts:
            return platform
    if "BV" in source_path:
        return "bili"
    first_row = next(iter(rows), {})
    if first_row.get("video_id") and first_row.get("comment_id"):
        return "bili"
    candidate = str(_first(first_row, "platform", "source_platform")).lower()
    return candidate if candidate in PLATFORMS else "unknown"


def normalize_rows(
    rows: list[Mapping[str, Any]],
    *,
    source_path: str,
    platform: Optional[str] = None,
    user_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dataset:
    platform = platform or infer_platform(source_path, rows)
    first_row = rows[0] if rows else {}
    content_id = str(
        _first(
            first_row,
            "content_id",
            "video_id",
            "note_id",
            "aweme_id",
            "article_id",
            "question_id",
            default=Path(source_path).stem,
        )
    )
    content = Content(
        content_id=content_id,
        platform=platform,
        url=str(_first(first_row, "content_url", "video_url", "note_url", "url")),
        title=str(_first(first_row, "title", "content_title", "video_title")),
        creator_id=str(_first(first_row, "creator_id", "user_id", "author_id")),
        creator_name=str(_first(first_row, "creator_name", "nickname", "author_name")),
        published_at=_as_datetime(_first(first_row, "content_time", "publish_time", "time")),
        metrics={
            "comments": len(rows),
            "likes": _as_int(_first(first_row, "liked_count", "like_count")),
            "shares": _as_int(_first(first_row, "share_count", "reposts_count")),
            "plays": _as_int(_first(first_row, "play_count", "view_count")),
        },
    )

    comments = []
    for index, row in enumerate(rows, start=1):
        comment_id = str(
            _first(row, "comment_id", "id", "rpid", "cid", default=f"{content_id}:{index}")
        )
        parent_id = _first(row, "parent_comment_id", "parent_id", "root_comment_id")
        comments.append(
            Comment(
                comment_id=comment_id,
                content_id=str(_first(row, "content_id", "video_id", "note_id", default=content_id)),
                platform=platform,
                text=str(_first(row, "content", "comment_text", "text", "desc")),
                parent_comment_id=None if parent_id in (None, "", 0, "0") else str(parent_id),
                author_id=str(_first(row, "user_id", "author_id", "uid")),
                author_name=str(_first(row, "nickname", "author_name", "user_name")),
                published_at=_as_datetime(_first(row, "create_time", "created_at", "time")),
                like_count=_as_int(_first(row, "like_count", "liked_count", "digg_count")),
                metadata={"ip_location": _first(row, "ip_location")},
            )
        )

    return Dataset(
        user_id=user_id,
        workspace_id=workspace_id,
        job_id=job_id,
        status=DatasetStatus.READY if rows else DatasetStatus.PARTIAL,
        content=content,
        comments=comments,
        source_files=[source_path],
    )
