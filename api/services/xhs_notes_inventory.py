# -*- coding: utf-8 -*-
"""小红书关键词笔记清单：把 `data/xhs_search/<批次>/notes.csv` 读成采集页能展示的列表。

## 为什么需要这个服务

`scripts/xhs_keyword_notes.py` 采回来的是「只有笔记、没有评论」的搜索结果
（标题 / 作者 / 点赞收藏评论数 / 原帖链接）。它落在两个既有入口都不管的中间地带：

- 不是评论文件：洞察页的来源是 `data/**/comments_*.csv`，笔记进去就是噪音；
- 不在 `/api/data` 的下载白名单里：那个接口是给"拿文件"用的，不是给"看内容"用的。

而采集页真正要回答的问题是「我刚采回来的是些什么帖子」，所以要的是一份
**只读、能点开原帖**的清单，不是文件下载。

## 读盘口径

- 批次 = `data/xhs_search/` 下的子目录，认有 `notes.csv` 的；
- 批次时间优先取 `manifest.json` 的 `created_at`，没有就退回文件 mtime；
- 默认只给最新一批：用户关心的是刚跑的那次，历史批次按需 `batch=` 指定。
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
NOTES_ROOT = DATA_DIR / "xhs_search"

#: 单次最多返回多少条（100 条的批次一次给全；上限防止误传大目录把响应撑爆）
MAX_LIMIT = 500


def _to_int(value: Any) -> int:
    """互动数统一成 int；"1.2万" 这类展示型文案退化为 0，不猜。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _batch_created_at(batch_dir: Path, notes_csv: Path) -> str:
    """批次时间：先看 manifest.created_at，没有就用文件 mtime 格式化。"""
    try:
        data = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
        created = str(data.get("created_at") or "").strip()
        if created:
            return created
    except (OSError, ValueError):
        pass
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(notes_csv.stat().st_mtime))
    except OSError:
        return ""


def list_batches() -> List[Dict[str, Any]]:
    """列出所有可展示的批次，新的在前。"""
    if not NOTES_ROOT.exists():
        return []
    batches: List[Dict[str, Any]] = []
    for path in NOTES_ROOT.iterdir():
        notes_csv = path / "notes.csv"
        if not path.is_dir() or not notes_csv.exists():
            continue
        try:
            total = max(0, len(notes_csv.read_text(encoding="utf-8-sig").splitlines()) - 1)
            mtime = notes_csv.stat().st_mtime
        except OSError:
            continue
        batches.append(
            {
                "batch": path.name,
                "created_at": _batch_created_at(path, notes_csv),
                "total": total,
                "mtime": mtime,
            }
        )
    batches.sort(key=lambda b: b["mtime"], reverse=True)
    return batches


def _read_rows(batch_dir: Path) -> List[Dict[str, Any]]:
    path = batch_dir / "notes.csv"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    items: List[Dict[str, Any]] = []
    for row in csv.DictReader(text.splitlines()):
        if not isinstance(row, dict):
            continue
        note_id = str(row.get("note_id") or "").strip()
        if not note_id:
            continue
        items.append(
            {
                "note_id": note_id,
                "keyword": str(row.get("keyword") or ""),
                "title": str(row.get("title") or "").strip(),
                "author": str(row.get("author") or "").strip(),
                "note_type": str(row.get("note_type") or ""),
                "liked": _to_int(row.get("liked_count")),
                "collected": _to_int(row.get("collected_count")),
                "comments": _to_int(row.get("comment_count")),
                "url": str(row.get("url") or ""),
            }
        )
    return items


def _keyword_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """当前结果集里各关键词的条数，前端用来做筛选提示。"""
    counts: Dict[str, int] = {}
    for row in rows:
        key = row.get("keyword") or "未标注"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def get_notes(
    batch: str = "",
    q: str = "",
    sort: str = "liked",
    limit: int = MAX_LIMIT,
    offset: int = 0,
) -> Dict[str, Any]:
    """返回一批笔记清单（可按标题/作者/关键词过滤，默认按点赞倒序）。"""
    batches = list_batches()
    available = {b["batch"] for b in batches}
    chosen = (batch or "").strip()
    if chosen and chosen not in available:
        raise KeyError(f"批次不存在：{chosen}")
    if not chosen:
        chosen = batches[0]["batch"] if batches else ""

    rows: List[Dict[str, Any]] = _read_rows(NOTES_ROOT / chosen) if chosen else []

    needle = (q or "").strip().lower()
    if needle:
        rows = [
            r
            for r in rows
            if needle in r["title"].lower() or needle in r["author"].lower() or needle in r["keyword"].lower()
        ]

    if sort == "liked":
        rows.sort(key=lambda r: r["liked"], reverse=True)

    total = len(rows)
    # 0 / 负数一律钳到 1：调用方传 0 的本意是"少一点"，不是"要全部"
    limit = max(1, min(int(limit or 1), MAX_LIMIT))
    offset = max(0, int(offset or 0))
    return {
        "batch": chosen,
        "batches": [
            {"batch": b["batch"], "created_at": b["created_at"], "total": b["total"]} for b in batches
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": rows[offset : offset + limit],
        "keyword_counts": _keyword_counts(rows),
    }
