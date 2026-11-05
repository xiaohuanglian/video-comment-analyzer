# -*- coding: utf-8 -*-
"""YouTube 评论采集（yt-dlp，零 API key）。

为什么用 yt-dlp 而不是 Data API：
- 本机已装 yt-dlp，不需要申请 key / 配配额；
- 一次能拿到主评论 + 回复 + 点赞数 + 作者 id + 时间戳；
- 代价是走网页接口，页大小小、大评论区慢，所以一律设上限并按视频断点落盘。

输出列与 B 站采集器保持一致（comment_id / parent_comment_id / create_time / video_id /
content / user_id / nickname / sub_comment_count / like_count），后端字段映射可直接复用；
额外追加 video_title / video_url / channel / platform / is_uploader / author_url。

注意：`extractor_args` 的值必须是**列表**，传字符串会被 yt-dlp 静默忽略（实测 0 条）。
"""

from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
OUT_DIR = DATA_DIR / "youtube_comments"
BENCH_DIR = DATA_DIR / "bench" / "youtube"
CREATORS_DIR = DATA_DIR / "creators"

PLATFORM = "youtube"

# 与 B 站采集器同名列在前，便于复用字段映射
COLUMNS = [
    "comment_id",
    "parent_comment_id",
    "create_time",
    "video_id",
    "content",
    "user_id",
    "nickname",
    "sub_comment_count",
    "like_count",
    "video_title",
    "video_url",
    "channel",
    "is_uploader",
    "author_url",
    "platform",
]

DEFAULT_MAX_COMMENTS = 200
DEFAULT_MAX_PARENTS = 60
DEFAULT_MAX_REPLIES = 10


# ---------------------------------------------------------------------------
# 目标发现：对标频道 + 本地已有视频清单
# ---------------------------------------------------------------------------

@dataclass
class Channel:
    name: str
    source: str  # bench / creators
    videos: List[Dict[str, Any]] = field(default_factory=list)


def _video_from_bench(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    vid = item.get("id") or item.get("video_id")
    if not vid:
        return None
    return {
        "id": vid,
        "title": item.get("title") or "",
        "views": int(item.get("views") or 0),
        "url": f"https://www.youtube.com/watch?v={vid}",
    }


def _video_from_raw(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    vid = item.get("video_id")
    if not vid:
        return None
    return {
        "id": vid,
        "title": item.get("title") or "",
        "views": int(item.get("views") or 0),
        "url": f"https://www.youtube.com/watch?v={vid}",
    }


def _dedupe(videos: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for video in videos:
        if not video:
            continue
        seen.setdefault(video["id"], video)
    return list(seen.values())


def list_channels() -> List[Channel]:
    """对标频道 = data/bench/youtube/*.json + data/creators/<slug>/raw/*.json。"""
    channels: List[Channel] = []

    if BENCH_DIR.is_dir():
        for path in sorted(BENCH_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            videos = _dedupe(_video_from_bench(v) for v in data.get("videos") or [])
            if videos:
                channels.append(Channel(name=path.stem, source="bench", videos=videos))

    if CREATORS_DIR.is_dir():
        for raw_dir in sorted(CREATORS_DIR.glob("*/raw")):
            slug = raw_dir.parent.name
            if slug.startswith("_"):
                continue
            videos: List[Dict[str, Any]] = []
            for path in sorted(raw_dir.glob("*.json")):
                if path.name.startswith("_"):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                videos.append(_video_from_raw(data))
            videos = _dedupe(videos)
            if videos:
                channels.append(Channel(name=slug, source="creators", videos=videos))

    # 同名频道（bench 与 creators 都有的）合并，bench 优先保留播放数据
    merged: Dict[str, Channel] = {}
    for channel in channels:
        key = channel.name.lower().replace("-", "").replace("_", "")
        if key in merged:
            existing = merged[key]
            existing.videos = _dedupe(existing.videos + channel.videos)
        else:
            merged[key] = channel
    return list(merged.values())


def select_videos(channel: Channel, limit: int = 3, order: str = "views") -> List[Dict[str, Any]]:
    videos = list(channel.videos)
    if order == "views":
        videos.sort(key=lambda v: -int(v.get("views") or 0))
    return videos[: max(1, limit)]


def list_targets(limit: int = 3) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for channel in list_channels():
        picked = select_videos(channel, limit)
        out.append(
            {
                "channel": channel.name,
                "source": channel.source,
                "video_count": len(channel.videos),
                "selected": picked,
            }
        )
    return out


# ---------------------------------------------------------------------------
# 采集
# ---------------------------------------------------------------------------

def _extract(info_url: str, *, max_comments: int, max_parents: int, max_replies: int, sort: str) -> Dict[str, Any]:
    import yt_dlp  # 延迟导入：只有真采时才需要

    options = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "getcomments": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                # 必须是「每个字段一个元素」的列表：总条数 / 主评论数 / 每条回复数。
                # 传成 ["300,80,10"] 会被 int_or_none 判成 None，等于不限额（实测拉了 1573 条）。
                "max_comments": [str(max_comments), str(max_parents), str(max_replies)],
                "comment_sort": [sort],
            }
        },
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(info_url, download=False) or {}


def _comment_row(
    comment: Dict[str, Any],
    *,
    video: Dict[str, Any],
    channel: str,
) -> Dict[str, Any]:
    parent = comment.get("parent") or "root"
    timestamp = comment.get("timestamp")
    return {
        "comment_id": str(comment.get("id") or ""),
        "parent_comment_id": "" if parent == "root" else str(parent),
        "create_time": int(timestamp * 1000) if timestamp else "",
        "video_id": video.get("id") or "",
        # 评论里的换行会让 CSV 的「记录数」被按物理行算错，统一压成空格
        "content": re.sub(r"\s*\n+\s*", " ", (comment.get("text") or "")).strip(),
        "user_id": comment.get("author_id") or "",
        "nickname": comment.get("author") or "",
        "sub_comment_count": int(comment.get("reply_count") or 0),
        "like_count": int(comment.get("like_count") or 0),
        "video_title": video.get("title") or "",
        "video_url": video.get("url") or "",
        "channel": channel,
        "is_uploader": bool(comment.get("author_is_uploader")),
        "author_url": comment.get("author_url") or "",
        "platform": PLATFORM,
    }


def fetch_video_comments(
    video: Dict[str, Any],
    *,
    channel: str = "",
    max_comments: int = DEFAULT_MAX_COMMENTS,
    max_parents: int = DEFAULT_MAX_PARENTS,
    max_replies: int = DEFAULT_MAX_REPLIES,
    sort: str = "top",
    extract_fn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """采一条视频。返回 {video, rows, error}，失败不抛（批量采不该被一条拖垮）。"""
    extract = extract_fn or _extract
    try:
        info = extract(
            video["url"],
            max_comments=max_comments,
            max_parents=max_parents,
            max_replies=max_replies,
            sort=sort,
        )
    except Exception as exc:  # noqa: BLE001
        return {"video": video, "rows": [], "error": f"{type(exc).__name__}: {exc}"}

    title = info.get("title") or video.get("title") or ""
    enriched = {
        "id": video.get("id") or info.get("id") or "",
        "title": title,
        "views": int(info.get("view_count") or video.get("views") or 0),
        "url": info.get("webpage_url") or video.get("url") or "",
    }
    comments = info.get("comments") or []
    rows = [_comment_row(c, video=enriched, channel=channel) for c in comments]
    return {"video": enriched, "rows": rows, "error": ""}


# ---------------------------------------------------------------------------
# 落盘与合并
# ---------------------------------------------------------------------------

def channel_csv_path(channel: str) -> Path:
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in channel) or "unknown"
    return OUT_DIR / safe / "all.csv"


def read_csv(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.is_file():
        return {}
    rows: Dict[str, Dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = row.get("comment_id") or ""
            if key:
                rows[key] = row
    return rows


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in COLUMNS})
    return path


def merge_into(path: Path, new_rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """按 comment_id 合并，支持断点续采（重复跑不会翻倍）。"""
    existing = read_csv(path)
    before = len(existing)
    for row in new_rows:
        key = row.get("comment_id")
        if key:
            existing[key] = row
    write_csv(path, list(existing.values()))
    return {"before": before, "after": len(existing), "added": len(existing) - before}


def collect_channel(
    channel: Channel,
    *,
    limit: int = 3,
    order: str = "views",
    max_comments: int = DEFAULT_MAX_COMMENTS,
    max_parents: int = DEFAULT_MAX_PARENTS,
    max_replies: int = DEFAULT_MAX_REPLIES,
    sort: str = "top",
    sleep_seconds: float = 1.5,
    extract_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    videos = select_videos(channel, limit=limit, order=order)
    collected: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for index, video in enumerate(videos, start=1):
        result = fetch_video_comments(
            video,
            channel=channel.name,
            max_comments=max_comments,
            max_parents=max_parents,
            max_replies=max_replies,
            sort=sort,
            extract_fn=extract_fn,
        )
        collected.extend(result["rows"])
        if result["error"]:
            errors.append({"video_id": video.get("id", ""), "error": result["error"]})
        if progress:
            progress(
                {
                    "channel": channel.name,
                    "video_index": index,
                    "video_total": len(videos),
                    "video_id": video.get("id", ""),
                    "rows": len(result["rows"]),
                    "error": result["error"],
                }
            )
        if sleep_seconds and index < len(videos):
            time.sleep(sleep_seconds)

    path = channel_csv_path(channel.name)
    merge = merge_into(path, collected)
    return {
        "channel": channel.name,
        "csv": str(path),
        "videos": len(videos),
        "fetched": len(collected),
        "added": merge["added"],
        "total_in_csv": merge["after"],
        "errors": errors,
    }


def collect_all(
    *,
    limit: int = 3,
    order: str = "views",
    max_comments: int = DEFAULT_MAX_COMMENTS,
    max_parents: int = DEFAULT_MAX_PARENTS,
    max_replies: int = DEFAULT_MAX_REPLIES,
    sort: str = "top",
    sleep_seconds: float = 1.5,
    channels: Optional[Sequence[str]] = None,
    extract_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    wanted = {c.strip().lower() for c in (channels or []) if c.strip()}
    targets = [c for c in list_channels() if not wanted or c.name.lower() in wanted]
    summaries = []
    for channel in targets:
        summaries.append(
            collect_channel(
                channel,
                limit=limit,
                order=order,
                max_comments=max_comments,
                max_parents=max_parents,
                max_replies=max_replies,
                sort=sort,
                sleep_seconds=sleep_seconds,
                extract_fn=extract_fn,
                progress=progress,
            )
        )

    # 汇总一份全局 CSV，方便一次拖进洞察
    merged: Dict[str, Dict[str, Any]] = {}
    for channel in targets:
        merged.update(read_csv(channel_csv_path(channel.name)))
    global_path = write_csv(OUT_DIR / "all_channels.csv", list(merged.values()))
    return {
        "channels": summaries,
        "total": len(merged),
        "global_csv": str(global_path),
        "out_dir": str(OUT_DIR),
    }


def channel_summary(channel: str) -> Dict[str, Any]:
    """本地已有数据的快速统计（不联网）。"""
    rows = list(read_csv(channel_csv_path(channel)).values())
    videos = {r.get("video_id") for r in rows if r.get("video_id")}
    top = sorted(rows, key=lambda r: -int(r.get("like_count") or 0))[:5]
    return {
        "channel": channel,
        "comments": len(rows),
        "videos": len(videos),
        "csv": str(channel_csv_path(channel)),
        "top_liked": [
            {"content": (r.get("content") or "")[:80], "like_count": int(r.get("like_count") or 0)}
            for r in top
        ],
    }
