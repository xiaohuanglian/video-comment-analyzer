# -*- coding: utf-8 -*-
"""本地已采数据盘点:按目录/日期/平台统计采回了多少笔记与评论。

采集页用一个「本地已采数据」概览回答"我到底采回了什么":
- 手动批量 data/comments(平台混合,按行形状识别 xhs/bili)
- 自动化通道 data/automation/comments(B 站)/ comments_xhs(小红书)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

# (目录, 来源标签) — 手动批量目录里 bili/xhs 按日期混住,靠行内容区分平台;
# 两个自动化目录(bili / xhs)平台固定,但同样走行检测保持一条代码路径
SOURCES: list[tuple[Path, str]] = [
    (DATA_DIR / "comments", "manual"),
    (DATA_DIR / "automation" / "comments", "automation"),
    (DATA_DIR / "automation" / "comments_xhs", "automation"),
]

_DATE_RE = re.compile(r"^(contents|comments)_(\d{4}-\d{2}-\d{2})\.jsonl$")

# 概览里最多展示的笔记/视频标题数(标题可能很长,只取前 24 字)
MAX_SAMPLE_TITLES = 6


def _iter_rows(path: Path):
    """逐行读 jsonl。用 split("\\n") 而非 splitlines():正文里的 U+2028 会被
    splitlines 切开,把完整 JSON 行撕成两半导致行数虚增(read_collected 踩过
    同一个坑)。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _detect_platform(row: dict[str, Any]) -> str:
    """按行形状识别平台:xhs 行带 note_id,bili 行带 video_id。"""
    if row.get("note_id"):
        return "xhs"
    if row.get("aweme_id"):
        return "dy"
    if row.get("video_id") or row.get("bvid"):
        return "bili"
    return "unknown"


def _scan_file(path: Path) -> tuple[dict[str, int], dict[str, list[str]]]:
    """数每个平台的行数;contents 文件顺带收集各平台的样例标题。"""
    counts: dict[str, int] = {}
    titles: dict[str, list[str]] = {}
    for row in _iter_rows(path):
        if not isinstance(row, dict):
            continue
        platform = _detect_platform(row)
        counts[platform] = counts.get(platform, 0) + 1
        bucket = titles.setdefault(platform, [])
        if len(bucket) < MAX_SAMPLE_TITLES:
            title = str(row.get("title") or "").strip()
            if title:
                bucket.append(title[:24])
    return counts, titles


def local_data_inventory() -> dict[str, Any]:
    """汇总三个采集目录,返回按平台聚合 + 按批次明细的库存。

    批次粒度是 (日期, 来源, 平台):手动目录同一天混采两个平台时会拆成
    两个批次,谁的数据算谁的,不互相吞。
    """
    # (date, source, platform) -> 批次;contents 与 comments 两个文件合并
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}

    for base, source in SOURCES:
        if not base.exists():
            continue
        for path in sorted(base.glob("*.jsonl")):
            m = _DATE_RE.match(path.name)
            if not m:
                continue
            kind, date = m.group(1), m.group(2)
            counts, titles = _scan_file(path)
            for platform, n in counts.items():
                batch = merged.setdefault(
                    (date, source, platform),
                    {
                        "date": date,
                        "source": source,
                        "platform": platform,
                        "contents": 0,
                        "comments": 0,
                        "titles": [],
                    },
                )
                if kind == "contents":
                    batch["contents"] += n
                    batch["titles"].extend(titles.get(platform, []))
                else:
                    batch["comments"] += n

    batches = sorted(
        merged.values(), key=lambda b: (b["date"], b["source"]), reverse=True
    )

    platforms: dict[str, dict[str, int]] = {}
    for b in batches:
        agg = platforms.setdefault(
            b["platform"], {"comments": 0, "contents": 0, "batches": 0}
        )
        agg["comments"] += b["comments"]
        agg["contents"] += b["contents"]
        agg["batches"] += 1

    return {"platforms": platforms, "batches": batches}
