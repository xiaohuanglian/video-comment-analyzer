# -*- coding: utf-8 -*-
"""「最强视频」素材采集:自有 B 站数据 + 外部链接(YouTube 字幕/简介)。

设计依据(2026-10-21 用户定调):国外内容普遍比国内先进一档,
「最强视频」要把国外的好观点/好技术带回国内,而非跟国内内卷。
YouTube 走 yt-dlp(本机猫猫云 TUN 可直连),只取元数据+字幕,不下载视频。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any


def _is_youtube(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


def _is_bilibili(url: str) -> bool:
    return bool(re.search(r"(bilibili\.com|b23\.tv)", url))


def _bvid_from(url: str) -> str:
    m = re.search(r"(BV[\w]+)", url)
    return m.group(1) if m else ""


async def fetch_link_material(url: str, timeout: float = 90) -> dict[str, Any]:
    """取一个外部链接的可用素材。永不抛异常,失败返回 error 字段。"""
    if _is_youtube(url):
        return await _fetch_youtube(url, timeout)
    if _is_bilibili(url):
        return {"url": url, "platform": "bili", "bvid": _bvid_from(url), "note": "B站链接:若在已采集库中会自动匹配评论"}
    return {"url": url, "platform": "unknown", "error": "不支持的链接(目前支持 YouTube / B 站)"}


def _yt_extract(url: str) -> dict[str, Any]:
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "zh-Hans", "zh-Hant", "zh"],
        "extractor_args": {"youtube": {"max_comments": ["30"]}},
        "getcomments": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _pick_subtitle_text(info: dict[str, Any], max_chars: int = 6000) -> str:
    """从 subtitles/automatic_captions 里拿纯文本(vtt/json3),截断。"""
    for source in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        for lang in ("zh-Hans", "zh-Hant", "zh", "en"):
            for fmt in source.get(lang) or []:
                if fmt.get("data"):
                    return _strip_sub(fmt["data"])[:max_chars]
    return ""


def _strip_sub(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    text = re.sub(r"(?m)^\d+$", "", text)
    text = re.sub(r"(?m)^[\d:.,\s-]+-->,*$", "", text)
    text = re.sub(r"(?m)^WEBVTT.*$", "", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # vtt 常见连续重复行,去相邻重复
    out: list[str] = []
    for ln in lines:
        if not out or out[-1] != ln:
            out.append(ln)
    return "\n".join(out)


def _yt_search(query: str, n: int) -> list[dict[str, Any]]:
    """YouTube 搜索,返回按播放量排序的候选(只有元数据)。"""
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    entries = [
        {
            "url": f"https://www.youtube.com/watch?v={e.get('id')}",
            "title": e.get("title") or "",
            "channel": e.get("uploader") or e.get("channel") or "",
            "view_count": e.get("view_count") or 0,
            "duration": e.get("duration") or 0,
        }
        for e in (info.get("entries") or [])
        if e.get("id")
    ]
    entries.sort(key=lambda e: -e["view_count"])
    return entries


async def search_youtube(query: str, n: int = 5, timeout: float = 60) -> list[dict[str, Any]]:
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, _yt_search, query, n), timeout)
    except Exception:
        return []


async def _fetch_youtube(url: str, timeout: float) -> dict[str, Any]:
    try:
        loop = asyncio.get_running_loop()
        info = await asyncio.wait_for(loop.run_in_executor(None, _yt_extract, url), timeout)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "platform": "youtube", "error": f"抓取失败:{str(e)[:200]}"}
    comments = [
        {"text": str(c.get("text") or "")[:200], "likes": c.get("like_count") or 0}
        for c in (info.get("comments") or [])[:30]
        if c.get("text")
    ]
    comments.sort(key=lambda c: -c["likes"])
    return {
        "url": url,
        "platform": "youtube",
        "title": info.get("title") or "",
        "channel": info.get("uploader") or "",
        "description": (info.get("description") or "")[:800],
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "subtitle": _pick_subtitle_text(info),
        "comments": comments[:15],
    }


def match_collected_videos(
    topic_title: str,
    video_map: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    max_videos: int = 4,
    exclude_video_id: str = "",
) -> list[dict[str, Any]]:
    """在自有采集数据里找同方向 B 站视频,返回 视频信息+高赞评论。"""
    # 中文分词不靠谱,用二元组(bigram)重叠度 + ASCII 词匹配
    def bigrams(s: str) -> set[str]:
        s = re.sub(r"[^\w\u4e00-\u9fff]", "", s)
        return {s[i : i + 2] for i in range(len(s) - 1)}

    topic_bg = bigrams(topic_title)
    ascii_terms = [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9]+", topic_title)]
    scored: list[tuple[int, str]] = []
    for vid, v in video_map.items():
        if exclude_video_id and vid == exclude_video_id:
            continue
        title = str(v.get("title") or "")
        title_bg = bigrams(title)
        hits = len(topic_bg & title_bg) + 3 * sum(1 for t in ascii_terms if t in title.lower())
        if hits >= 2:
            scored.append((hits, vid))
    scored.sort(reverse=True)
    out: list[dict[str, Any]] = []
    for _, vid in scored[:max_videos]:
        v = video_map.get(vid, {})
        comments = [r for r in rows if str(r.get("video_id") or "") == vid]
        comments.sort(key=lambda r: int(str(r.get("like_count") or 0) or 0), reverse=True)
        out.append(
            {
                "platform": "bili",
                "title": str(v.get("title") or vid),
                "desc": str(v.get("desc") or "")[:300],
                "top_comments": [
                    {"text": str(c.get("content") or "")[:150], "likes": int(str(c.get("like_count") or 0) or 0)}
                    for c in comments[:15]
                ],
            }
        )
    return out
