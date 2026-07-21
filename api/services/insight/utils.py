# -*- coding: utf-8
"""Shared helpers for insight ingestion."""

from __future__ import annotations

import re
from typing import Any


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if text.startswith("http://") or text.startswith("https://"):
        return default
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def extract_video_label(folder: str) -> str:
    """Extract readable video title from folder path segment."""
    leaf = folder.replace("\\", "/").split("/")[-1]
    leaf = re.sub(r"_BV[a-zA-Z0-9]+$", "", leaf)
    leaf = re.sub(r"_av\d+$", "", leaf)
    return leaf.strip() or folder
