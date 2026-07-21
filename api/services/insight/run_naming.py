# -*- coding: utf-8 -*-
"""Human-readable run folder names."""

from __future__ import annotations

import re
from typing import Callable, Optional


def slugify_run_name(name: str) -> str:
    base = (name or "评论洞察任务").strip()
    slug = re.sub(r"\s+", "_", base)
    slug = re.sub(r"[^\w\u4e00-\u9fff\-_]", "", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")[:48]
    return slug or "任务"


def build_run_id(name: str, *, exists: Optional[Callable[[str], bool]] = None) -> str:
    """Build folder name from task name only (no date suffix)."""
    slug = slugify_run_name(name)
    if exists is None or not exists(slug):
        return slug
    for index in range(2, 100):
        alt = f"{slug}_{index}"
        if not exists(alt):
            return alt
    return f"{slug}_99"
