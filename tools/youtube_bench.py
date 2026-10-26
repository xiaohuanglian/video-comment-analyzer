#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""YouTube 对标频道采集器(只读,拆解用,不涉及任何发送)。

用途:拉对标频道视频列表(标题/播放/时长/日期)+ 头部视频的字幕与简介,
落盘 data/bench/youtube/<handle>.json,供《对标拆解报告》使用。

依赖:yt-dlp(公有领域)、youtube-transcript-api(MIT)。

用法:
  .venv/bin/python tools/youtube_bench.py --channels @LiamOttley @marc-lou --limit 60 --detail 8 --subs 3
  --limit  取最近 N 条视频元数据(默认 60)
  --detail 对播放量前 N + 最早 N 条做全量抽取(简介/精确日期,默认 8)
  --subs   对播放量前 N 条抓英文字幕(自动生成字幕也算,默认 3)
  --refresh 已有缓存也强制重拉
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yt_dlp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "data" / "bench" / "youtube"


def _ydl(opts: dict) -> yt_dlp.YoutubeDL:
    base = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # 单视频抽取换 ios 客户端,绕开网页端的 bot 校验
        "extractor_args": {"youtube": {"player_client": ["ios"]}},
        # 直连可达;若环境变化需代理,加 "proxy": "http://..."
    }
    base.update(opts)
    return yt_dlp.YoutubeDL(base)


def _rss_dates(channel_id: str) -> dict[str, str]:
    """频道 RSS(最新15条)拿发布日期,免登录免 bot 校验。"""
    import re as _re
    import urllib.request
    if not channel_id:
        return {}
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
            headers={"User-Agent": "Mozilla/5.0"})
        xml = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
        pairs = _re.findall(r"<yt:videoId>([^<]+)</yt:videoId>.*?<published>(\d{4}-\d{2}-\d{2})", xml, _re.S)
        return {vid: pub.replace("-", "") for vid, pub in pairs}
    except Exception:  # noqa: BLE001
        return {}


def fetch_channel(handle: str, limit: int, detail: int, subs: int, refresh: bool = False) -> dict:
    out_file = OUT_DIR / f"{handle.lstrip('@')}.json"
    old: dict = {}
    if out_file.exists():
        if not refresh:
            print(f"[{handle}] 已有缓存 {out_file.name}(--refresh 重拉)")
            return json.loads(out_file.read_text(encoding="utf-8"))
        try:  # refresh 时仍保留旧数据做合并,避免本次未抓的字段被清空
            old = json.loads(out_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            old = {}

    print(f"[{handle}] 拉取视频列表(最近 {limit} 条)…")
    with _ydl({"extract_flat": True, "playlistend": limit}) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/{handle}/videos", download=False)
    entries = [e for e in (info.get("entries") or []) if e]
    channel = {
        "handle": handle,
        "name": info.get("channel") or "",
        "followers": info.get("channel_follower_count"),
        "channel_id": info.get("channel_id") or "",
        "url": f"https://www.youtube.com/{handle}",
    }
    print(f"[{handle}] {channel['name']} | 订阅 {channel['followers']} | 页内视频 {len(entries)}")

    videos = [
        {
            "id": e.get("id") or "",
            "title": e.get("title") or "",
            "views": e.get("view_count"),
            "duration_s": e.get("duration"),
            "url": e.get("url") or (f"https://youtu.be/{e.get('id')}" if e.get("id") else ""),
        }
        for e in entries
    ]
    videos = [v for v in videos if v["id"]]

    # RSS 回填最新一批的发布日期(免 bot 校验)
    rss = _rss_dates(channel.get("channel_id") or "")
    for v in videos:
        if rss.get(v["id"]):
            v["upload_date"] = rss[v["id"]]

    # ---- 全量抽取:播放量前 detail 条 + 补足最早若干条(拿简介+精确日期) ----
    by_views = sorted([v for v in videos if v.get("views")], key=lambda x: -x["views"])[:detail]
    detail_ids = {v["id"] for v in by_views}
    with _ydl({}) as ydl:
        for v in videos:
            if v["id"] in detail_ids and not v.get("upload_date"):
                try:
                    full = ydl.extract_info(v["url"], download=False)
                    v["upload_date"] = full.get("upload_date") or ""
                    v["description"] = (full.get("description") or "")[:1500]
                    v["views"] = full.get("view_count") or v.get("views")
                    v["likes"] = full.get("like_count")
                    time.sleep(0.4)
                except Exception as ex:  # noqa: BLE001
                    v["_detail_error"] = str(ex)[:80]
    # 其余条目日期缺失时按列表顺序近似(YouTube /videos 默认最新在前)
    for i, v in enumerate(videos):
        v.setdefault("upload_date", "")
        v["rank_newest"] = i

    # 有日期的按时间排序,标出「起号期」前 20
    dated = [v for v in videos if v.get("upload_date")]
    dated.sort(key=lambda x: x["upload_date"])
    for i, v in enumerate(dated):
        v["rank_early"] = i  # 0 = 频道最早
        v["is_early20"] = i < 20

    # 合并旧数据:本次没抓到的字段(日期/简介/字幕)从上次结果回填
    old_by_id = {v.get("id"): v for v in (old.get("videos") or [])}
    for v in videos:
        prev = old_by_id.get(v["id"])
        if prev:
            for k in ("upload_date", "description", "likes"):
                if not v.get(k) and prev.get(k):
                    v[k] = prev[k]

    # ---- 字幕:播放量前 subs 条 ----
    transcripts: dict[str, str] = {}
    top_ids = [v["id"] for v in by_views[:subs]]
    old_transcripts = old.get("transcripts") or {}
    if subs > 0:
        print(f"[{handle}] 抓字幕 {len(top_ids)} 条(播放量头部)…")
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            api = YouTubeTranscriptApi()
            for vid in top_ids:
                try:
                    fetched = api.fetch(vid, languages=["en"])
                    text = " ".join(s.text for s in fetched).strip()
                    transcripts[vid] = text[:6000]
                    time.sleep(0.4)
                except Exception as ex:  # noqa: BLE001
                    transcripts[vid] = old_transcripts.get(vid) or f"[字幕获取失败: {str(ex)[:60]}]"
        except ImportError:
            print("[warn] youtube-transcript-api 未安装,跳过字幕")
    # 旧字幕里不在本次名单的也保留(可能上次拓过更多)
    for k, v in old_transcripts.items():
        transcripts.setdefault(k, v)

    data = {
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "channel": channel,
        "videos": videos,
        "transcripts": transcripts,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{handle}] ✓ 落盘 {out_file}({len(videos)} 条视频,{len(transcripts)} 份字幕)")
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channels", nargs="+", required=True, help="频道手柄,如 @LiamOttley")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--detail", type=int, default=8)
    ap.add_argument("--subs", type=int, default=3)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    for h in args.channels:
        try:
            fetch_channel(h, args.limit, args.detail, args.subs, args.refresh)
        except Exception as ex:  # noqa: BLE001
            print(f"[{h}] ✗ 失败: {str(ex)[:120]}(继续下一个)")


if __name__ == "__main__":
    main()
