#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YouTube 评论采集 CLI（yt-dlp，零 API key）。

例：
  # 看有哪些对标频道、会采哪几条视频
  uv run python tools/youtube_comments.py --targets

  # 每个对标频道采播放量 Top 3 视频，各 200 条评论
  uv run python tools/youtube_comments.py --all --limit 3 --max-comments 200

  # 只采指定频道
  uv run python tools/youtube_comments.py --channels LiamOttley,marc-lou --limit 2

  # 采指定视频
  uv run python tools/youtube_comments.py --video https://youtu.be/xxxx

输出：data/youtube_comments/<channel>/all.csv + 汇总 data/youtube_comments/all_channels.csv
重复跑自动按 comment_id 合并，不会翻倍。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.youtube import comments  # noqa: E402


def _print(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="采集 YouTube 评论（yt-dlp）")
    parser.add_argument("--targets", action="store_true", help="只列出对标频道与候选视频，不采集")
    parser.add_argument("--all", action="store_true", help="采集全部对标频道")
    parser.add_argument("--channels", default="", help="指定频道，逗号分隔（如 LiamOttley,marc-lou）")
    parser.add_argument("--video", action="append", default=[], help="指定视频 URL 或 ID，可多次")
    parser.add_argument("--limit", type=int, default=3, help="每个频道取播放量前 N 条视频（默认 3）")
    parser.add_argument("--order", choices=["views", "recent"], default="views")
    parser.add_argument("--max-comments", type=int, default=comments.DEFAULT_MAX_COMMENTS,
                        help="每条视频最多采多少条（主评论上限自动跟随）")
    parser.add_argument("--max-parents", type=int, default=None, help="主评论上限，默认等于 --max-comments")
    parser.add_argument("--max-replies", type=int, default=None, help="回复上限，默认总条数的 1/10")
    parser.add_argument("--sort", choices=["top", "newest"], default="top")
    parser.add_argument("--sleep", type=float, default=1.5, help="视频之间休眠秒数，防风控")
    args = parser.parse_args()

    if args.targets:
        _print({"targets": comments.list_targets(limit=args.limit)})
        return 0

    if args.video:
        videos = []
        for raw in args.video:
            vid = raw.rstrip("/").split("/")[-1].split("v=")[-1]
            videos.append(
                {
                    "id": vid,
                    "title": "",
                    "views": 0,
                    "url": raw if raw.startswith("http") else f"https://www.youtube.com/watch?v={vid}",
                }
            )
        channel = comments.Channel(name="manual", source="manual", videos=videos)
        summary = comments.collect_channel(
            channel,
            limit=len(videos),
            max_comments=args.max_comments,
            max_parents=args.max_parents,
            max_replies=args.max_replies,
            sort=args.sort,
            sleep_seconds=args.sleep,
            progress=_print,
        )
        _print({"summary": summary})
        return 0

    if not args.all and not args.channels.strip():
        parser.error("请用 --all / --channels / --video / --targets 之一")

    channels = [c for c in args.channels.split(",") if c.strip()] or None
    result = comments.collect_all(
        limit=args.limit,
        order=args.order,
        max_comments=args.max_comments,
        max_parents=args.max_parents,
        max_replies=args.max_replies,
        sort=args.sort,
        sleep_seconds=args.sleep,
        channels=channels,
        progress=_print,
    )
    _print({"result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
