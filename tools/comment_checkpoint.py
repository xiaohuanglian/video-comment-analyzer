# -*- coding: utf-8 -*-
"""Checkpoint helpers for resuming Bilibili comment crawls."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from tools.save_path_utils import comment_file_globs


def _checkpoint_file(save_dir: Path) -> Path:
    return save_dir / ".comment_crawl_checkpoint.json"


def load_existing_comment_ids(save_dir: Path, video_id: str) -> set[str]:
    """Load comment IDs already saved for a video in the target folder."""
    ids: set[str] = set()
    if not save_dir.is_dir():
        return ids

    for pattern in comment_file_globs("*", "csv"):
        for csv_path in save_dir.glob(pattern):
            if csv_path.name.startswith("creators_") or csv_path.name.startswith("videos_"):
                continue
            try:
                with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        row_video_id = str(row.get("video_id", "")).strip()
                        if row_video_id and row_video_id != str(video_id):
                            continue
                        comment_id = str(row.get("comment_id", "")).strip()
                        if comment_id:
                            ids.add(comment_id)
            except Exception:
                continue
    return ids


def load_checkpoint(save_dir: Path, video_id: str) -> Optional[dict]:
    path = _checkpoint_file(save_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    entry = data.get(str(video_id))
    return entry if isinstance(entry, dict) else None


def save_checkpoint(
    save_dir: Path,
    video_id: str,
    *,
    next_page: int,
    total_saved: int,
    order_mode: int,
    stopped_reason: str,
) -> None:
    save_dir.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_file(save_dir)
    payload: dict = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    payload[str(video_id)] = {
        "next_page": next_page,
        "total_saved": total_saved,
        "order_mode": order_mode,
        "stopped_reason": stopped_reason,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_video_crawl_data(save_dir: Path) -> list[str]:
    """Remove comment/video/creator CSV files and checkpoint for a fresh crawl."""
    removed: list[str] = []
    if not save_dir.is_dir():
        return removed

    patterns = (
        "comments_*.csv",
        "videos_*.csv",
        "creators_*.csv",
        "comments_*.jsonl",
        "comments_*.json",
        "comments_*.xlsx",
    )
    for pattern in patterns:
        for path in save_dir.glob(pattern):
            try:
                path.unlink()
                removed.append(path.name)
            except Exception:
                continue

    checkpoint = _checkpoint_file(save_dir)
    if checkpoint.is_file():
        try:
            checkpoint.unlink()
            removed.append(checkpoint.name)
        except Exception:
            pass

    return removed


def count_existing_comments(save_dir: Path, video_id: str) -> int:
    """Return unique comment count already saved for a video."""
    return len(load_existing_comment_ids(save_dir, video_id))


def should_restart_crawl(
    save_dir: Path,
    video_id: str,
    expected_reply: int,
    max_count: int,
    *,
    force: bool = False,
    completion_ratio: float = 0.95,
) -> tuple[bool, str]:
    """
    Decide whether to discard existing output and restart from page 0.

    Returns (should_restart, reason).
    """
    if not save_dir.is_dir():
        return False, ""

    existing_count = count_existing_comments(save_dir, video_id)
    has_checkpoint = load_checkpoint(save_dir, video_id) is not None

    if force:
        if existing_count > 0 or has_checkpoint:
            return True, "manual fresh crawl requested"
        return False, ""

    if existing_count == 0:
        if has_checkpoint:
            return True, "stale checkpoint from an incomplete run"
        return False, ""

    if expected_reply > 0:
        target = min(expected_reply, max_count) if max_count > 0 else expected_reply
    else:
        target = max_count

    if target <= 0:
        return False, ""

    if existing_count < int(target * completion_ratio):
        return True, f"partial crawl detected ({existing_count}/{target} comments)"

    if has_checkpoint:
        return True, f"partial crawl detected ({existing_count}/{target} comments, checkpoint present)"

    return False, ""


def clear_checkpoint(save_dir: Path, video_id: str) -> None:
    path = _checkpoint_file(save_dir)
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    payload.pop(str(video_id), None)
    if payload:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
