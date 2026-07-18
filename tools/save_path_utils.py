# -*- coding: utf-8 -*-
"""Helpers for per-video save folder naming."""

import re
from pathlib import Path
from typing import Optional


_INVALID_PATH_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_MULTI_UNDERSCORE = re.compile(r"_+")


def shorten_video_title(title: str, max_len: int = 20) -> str:
    """Return a filesystem-safe abbreviated title."""
    text = (title or "").strip()
    text = _INVALID_PATH_CHARS.sub("", text)
    text = re.sub(r"\s+", "_", text)
    text = _MULTI_UNDERSCORE.sub("_", text).strip("._ ")
    if len(text) > max_len:
        text = text[:max_len].rstrip("._ ")
    return text or "video"


def build_video_folder_slug(title: str, video_id: str, max_title_len: int = 20) -> str:
    """Build folder name like `标题简写_BV1xxxx`."""
    slug = shorten_video_title(title, max_title_len)
    video_key = (video_id or "unknown").strip()
    video_key = _INVALID_PATH_CHARS.sub("", video_key)
    return f"{slug}_{video_key}"


def join_video_save_path(base_path: str, folder_slug: str) -> str:
    """Join base save path with per-video folder slug."""
    base = (base_path or "./data/comments").strip().rstrip("/")
    slug = (folder_slug or "video").strip().strip("/")
    return f"{base}/{slug}"


def build_comment_filename(item_type: str, date_str: str, file_ext: str, flat: bool = True) -> str:
    """Build output filename for comment crawler exports."""
    if flat:
        return f"{item_type}_{date_str}.{file_ext}"
    return f"detail_{item_type}_{date_str}.{file_ext}"


def comment_file_globs(date_str: str, file_ext: str) -> list[str]:
    """Glob patterns that match comment export files (flat + legacy layouts)."""
    return [
        f"**/comments_{date_str}.{file_ext}",
        f"**/detail_comments_{date_str}.{file_ext}",
        f"**/*/csv/detail_comments_{date_str}.{file_ext}",
    ]


def count_csv_rows(path: Path, *, quick: bool = False) -> Optional[int]:
    """Count CSV data rows. When quick=True, skip full scan for large files."""
    try:
        size = path.stat().st_size
        if quick and size > 512 * 1024:
            return None
        with open(path, "r", encoding="utf-8-sig") as handle:
            line_count = sum(1 for _ in handle)
        return max(0, line_count - 1)
    except OSError:
        return None
