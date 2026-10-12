# -*- coding: utf-8 -*-
"""小红书浏览式采集 CLI。

用法：
  uv run python scripts/xhs_browse_collect.py --keyword 导出笔记 --keyword 收藏备份
  uv run python scripts/xhs_browse_collect.py --note-url "https://www.xiaohongshu.com/explore/xxx?xsec_token=yyy"

前提：带调试端口（默认 9222）的浏览器已启动且已登录小红书。
输出：data/xhs_browse/<时间戳>/comments.csv，可直接在 Web UI 建任务导入。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.xhs_browse_collector import run_browse_collection


def main() -> None:
    parser = argparse.ArgumentParser(description="小红书浏览式采集（浏览器 DOM 提取，无 API 请求）")
    parser.add_argument("--keyword", action="append", default=[], help="搜索关键词（可多次）")
    parser.add_argument("--note-url", action="append", default=[], help="指定笔记链接（可多次，需含 xsec_token）")
    parser.add_argument("--max-notes", type=int, default=5, help="每个关键词最多浏览的笔记数（默认 5）")
    parser.add_argument(
        "--min-pause",
        type=float,
        default=12.0,
        help="两篇笔记之间最小停留秒数（默认 12，建议不要太小）",
    )
    parser.add_argument(
        "--max-pause",
        type=float,
        default=35.0,
        help="两篇笔记之间最大停留秒数（默认 35）",
    )
    parser.add_argument("--out", type=str, default="", help="输出目录（默认 data/xhs_browse/<时间戳>）")
    args = parser.parse_args()

    if not args.keyword and not args.note_url:
        parser.error("至少提供 --keyword 或 --note-url 之一")

    out_dir = Path(args.out) if args.out else None
    csv_path, results = asyncio.run(
        run_browse_collection(
            keywords=args.keyword,
            note_urls=args.note_url,
            max_notes_per_keyword=args.max_notes,
            note_pause_seconds=(args.min_pause, args.max_pause),
            out_dir=out_dir,
        )
    )
    total = sum(len(n.comments) for n in results)
    print(f"\n完成：{len(results)} 篇笔记，{total} 条评论")
    print(f"CSV：{csv_path}")
    print("下一步：Web UI 建任务时选择该 CSV（平台 xhs），列名会自动识别")


if __name__ == "__main__":
    main()
