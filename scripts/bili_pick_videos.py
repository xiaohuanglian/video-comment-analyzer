# -*- coding: utf-8 -*-
"""B 站「高赞一半 + 最近一半」选片：只挑视频，不抓评论。

为什么单独写：
1. B 站搜索**没有「按点赞」排序**（只有 综合/最多播放/最新发布/最多弹幕/最多收藏），
   所以「高赞」只能先用「最多播放」把候选捞回来，再按搜索返回里的真实 `like` 排序；
2. 搜到的每条结果里已经带了 `play / like / review(评论数) / favorites / pubdate`，
   不必对每条都再打一次详情接口——选片阶段每词每页 1 次请求就够。

输出：`data/bili_pick/<时间戳>/`
- `candidates.csv`：全部候选（两个排序档合并，按 like 倒序）
- `selection.json`：最终选中的 N 个视频 + 分组标签，供评论采集直接消费

用法：
  uv run python scripts/bili_pick_videos.py \
      --keyword 新闻速览 --keyword AI资讯 --per-group 10 --recent-days 30 --pages 2
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

os.environ.setdefault("CDP_CONNECT_EXISTING", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

# CDPBrowserManager 用 config.PLATFORM 挑 profile（browser_data/cdp_<p>_user_data_dir）
config.PLATFORM = "bili"
config.CRAWLER_TYPE = "search"

from tenacity import RetryError  # noqa: E402

from media_platform.bilibili.client import BilibiliClient  # noqa: E402
from media_platform.bilibili.field import SearchOrderType  # noqa: E402
from tools import utils  # noqa: E402
from tools.cdp_browser import CDPBrowserManager  # noqa: E402
from tools.crawl_pacing import (  # noqa: E402
    classify_failure,
    compute_crawl_interval,
    ensure_platform_available,
)

_INDEX_URL = "https://www.bilibili.com"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
#: 高赞/最近两组都要过的「标题相关性」闸门。
#: 为什么必须有：B 站「最多播放」会把全网爆款捞进来——Minecraft 每日新闻、
#: 19 秒背景音乐、模仿新闻播报、英语精听搬运，这些和「1 分钟资讯音频」无关，
#: 评论区聊的也不是目标用户。宁可少，不要跑题。
_RELEVANT_PATTERNS = ("新闻", "资讯", "播报", "速览", "日报", "早间", "晨报", "晚报", "热点", "盘点", "AI", "人工智能")
_EXCLUDE_PATTERNS = (
    "minecraft", "我的世界", "音乐", "歌单", "bgm", "英语", "日语", "精听", "听力",
    "模仿", "有声书", "小说", "相声", "鬼畜", "混响", "恶搞", "游戏", "直播回放",
    # 2026-11-12 实测漏网的：播音练声、美剧剧情分析，标题沾词但内容不是资讯
    "跟读", "播音腔", "职场剧", "美剧", "电视剧", "穿搭",
)

_COLUMNS = [
    "group",
    "keyword",
    "bvid",
    "aid",
    "title",
    "author",
    "play",
    "like",
    "favorites",
    "comments",
    "pubdate",
    "pubdate_str",
    "duration",
    "url",
]


def _clean_title(raw: Any) -> str:
    """搜索结果的标题带高亮标签，去掉再存。"""
    text = str(raw or "")
    return text.replace('<em class="keyword">', "").replace("</em>", "").strip()


def _row(keyword: str, item: Dict[str, Any], group: str) -> Dict[str, Any] | None:
    bvid = str(item.get("bvid") or "").strip()
    if not bvid:
        return None
    pubdate = int(item.get("pubdate") or 0)
    return {
        "group": group,
        "keyword": keyword,
        "bvid": bvid,
        "aid": item.get("aid") or 0,
        "title": _clean_title(item.get("title")),
        "author": str(item.get("author") or "").strip(),
        "play": int(item.get("play") or 0),
        "like": int(item.get("like") or 0),
        "favorites": int(item.get("favorites") or 0),
        "comments": int(item.get("review") or 0),
        "pubdate": pubdate,
        "pubdate_str": time.strftime("%Y-%m-%d", time.localtime(pubdate)) if pubdate else "",
        "duration": str(item.get("duration") or ""),
        "url": f"{_INDEX_URL}/video/{bvid}",
    }


def is_relevant(title: str) -> bool:
    """标题命中资讯类词、且不命中排除词。"""
    text = (title or "").lower()
    if not any(p.lower() in text for p in _RELEVANT_PATTERNS):
        return False
    return not any(p.lower() in text for p in _EXCLUDE_PATTERNS)


def _root_error(exc: BaseException) -> BaseException:
    cur: BaseException = exc
    seen: set[int] = set()
    while True:
        nxt = cur.__cause__ or cur.__context__
        if isinstance(cur, RetryError):
            try:
                nxt = cur.last_attempt.exception() or nxt
            except Exception:  # noqa: BLE001
                pass
        if nxt is None or nxt is cur or id(nxt) in seen:
            return cur
        seen.add(id(cur))
        cur = nxt


async def _build_client(page: Any) -> BilibiliClient:
    cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
        page.context, urls=[_INDEX_URL]
    )
    return BilibiliClient(
        headers={
            "User-Agent": _USER_AGENT,
            "Cookie": cookie_str,
            "Origin": _INDEX_URL,
            "Referer": _INDEX_URL,
            "Content-Type": "application/json;charset=UTF-8",
        },
        playwright_page=page,
        cookie_dict=cookie_dict,
    )


async def collect(
    keywords: List[str],
    *,
    per_group: int,
    recent_days: int,
    pages: int,
    out_dir: Path,
    recent_min_play: int = 3000,
    recent_min_comments: int = 20,
) -> Dict[str, Any]:
    ensure_platform_available("bili")

    from playwright.async_api import async_playwright

    manager = CDPBrowserManager()
    failures: List[Dict[str, Any]] = []
    candidates: Dict[str, Dict[str, Any]] = {}

    async with async_playwright() as playwright:
        context = await manager.launch_and_connect(playwright, None, None, headless=config.CDP_HEADLESS)
        page = await context.new_page()
        try:
            await page.goto(_INDEX_URL, wait_until="domcontentloaded", timeout=30000)
            client = await _build_client(page)
            first = True
            for order, group in ((SearchOrderType.DEFAULT, "hot"), (SearchOrderType.LAST_PUBLISH, "recent")):
                for keyword in keywords:
                    for page_no in range(1, max(1, pages) + 1):
                        if not first:
                            base, jitter = compute_crawl_interval("bili")
                            await asyncio.sleep(base + jitter)
                        first = False
                        try:
                            res = await client.search_video_by_keyword(
                                keyword=keyword, page=page_no, page_size=20, order=order
                            )
                            items = res.get("result") or []
                            added = 0
                            for item in items:
                                row = _row(keyword, item, group)
                                if row and row["bvid"] not in candidates:
                                    candidates[row["bvid"]] = row
                                    added += 1
                            utils.logger.info(
                                f"[bili_pick] {group}/{keyword} p{page_no}: {len(items)} 条，新增 {added}"
                            )
                            if not items:
                                break
                        except Exception as exc:  # noqa: BLE001 — 单个请求失败不中断整批
                            root = _root_error(exc)
                            failure = classify_failure(root, platform="bili")
                            failures.append(
                                {
                                    "stage": "search",
                                    "group": group,
                                    "keyword": keyword,
                                    "page": page_no,
                                    **failure.to_dict(),
                                }
                            )
                            utils.logger.warning(
                                f"[bili_pick] {group}/{keyword} p{page_no} 失败：{failure.message or root}"
                            )
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
            await manager.cleanup()

    rows = list(candidates.values())
    cutoff = int(time.time()) - recent_days * 86400

    relevant = [r for r in rows if is_relevant(r["title"])]

    # 高赞组：综合排序的候选里按真实点赞倒序
    hot = sorted([r for r in relevant if r["like"] > 0], key=lambda r: r["like"], reverse=True)
    selected_hot = hot[:per_group]
    taken = {r["bvid"] for r in selected_hot}

    # 最近组：30 天内 + 有互动（否则全是 0 赞 0 评的日更搬运号，评论区没内容可分析）
    recent_pool = [
        r
        for r in relevant
        if r["pubdate"] >= cutoff
        and r["bvid"] not in taken
        and (r["play"] >= recent_min_play or r["comments"] >= recent_min_comments)
    ]
    recent_pool.sort(key=lambda r: r["pubdate"], reverse=True)
    selected_recent = recent_pool[:per_group]

    selected = selected_hot + selected_recent
    for row in selected:
        row["group"] = "hot" if row["bvid"] in {x["bvid"] for x in selected_hot} else "recent"

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "candidates.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r["like"], reverse=True))

    selection = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "keywords": keywords,
        "per_group": per_group,
        "recent_days": recent_days,
        "recent_min_play": recent_min_play,
        "recent_min_comments": recent_min_comments,
        "pages_per_keyword": pages,
        "candidate_total": len(rows),
        "selected_total": len(selected),
        "selected_comments_sum": sum(r["comments"] for r in selected),
        "hot": selected_hot,
        "recent": selected_recent,
        "failures": failures,
    }
    (out_dir / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return selection


def reselect(
    candidates_csv: Path,
    *,
    per_group: int,
    recent_days: int,
    out_dir: Path,
    recent_min_play: int = 3000,
    recent_min_comments: int = 20,
) -> Dict[str, Any]:
    """只重算选片，不联网：复用上一次抓下来的 candidates.csv。"""
    text = candidates_csv.read_text(encoding="utf-8-sig")
    rows: List[Dict[str, Any]] = []
    for raw in csv.DictReader(text.splitlines()):
        rows.append(
            {
                "group": raw.get("group", ""),
                "keyword": raw.get("keyword", ""),
                "bvid": raw.get("bvid", ""),
                "aid": int(raw.get("aid") or 0),
                "title": raw.get("title", ""),
                "author": raw.get("author", ""),
                "play": int(raw.get("play") or 0),
                "like": int(raw.get("like") or 0),
                "favorites": int(raw.get("favorites") or 0),
                "comments": int(raw.get("comments") or 0),
                "pubdate": int(raw.get("pubdate") or 0),
                "pubdate_str": raw.get("pubdate_str", ""),
                "duration": raw.get("duration", ""),
                "url": raw.get("url", ""),
            }
        )
    cutoff = int(time.time()) - recent_days * 86400
    relevant = [r for r in rows if is_relevant(r["title"])]
    hot = sorted([r for r in relevant if r["like"] > 0], key=lambda r: r["like"], reverse=True)
    selected_hot = hot[:per_group]
    taken = {r["bvid"] for r in selected_hot}
    recent_pool = [
        r
        for r in relevant
        if r["pubdate"] >= cutoff
        and r["bvid"] not in taken
        and (r["play"] >= recent_min_play or r["comments"] >= recent_min_comments)
    ]
    recent_pool.sort(key=lambda r: r["pubdate"], reverse=True)
    selected_recent = recent_pool[:per_group]

    out_dir.mkdir(parents=True, exist_ok=True)
    selection = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reused_from": str(candidates_csv),
        "per_group": per_group,
        "recent_days": recent_days,
        "recent_min_play": recent_min_play,
        "recent_min_comments": recent_min_comments,
        "candidate_total": len(rows),
        "selected_total": len(selected_hot) + len(selected_recent),
        "selected_comments_sum": sum(r["comments"] for r in selected_hot + selected_recent),
        "hot": selected_hot,
        "recent": selected_recent,
        "failures": [],
    }
    (out_dir / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return selection


def main() -> None:
    parser = argparse.ArgumentParser(description="B 站选片：一半高赞、一半最近（只选片，不抓评论）")
    parser.add_argument("--keyword", action="append", default=[], help="搜索关键词（可多次）")
    parser.add_argument("--per-group", type=int, default=10, help="每组取几个视频（默认 10）")
    parser.add_argument("--recent-days", type=int, default=30, help="「最近」的天数窗口（默认 30）")
    parser.add_argument("--pages", type=int, default=2, help="每个关键词每个排序取几页（默认 2，每页 20）")
    parser.add_argument("--recent-min-play", type=int, default=3000, help="最近组播放门槛（默认 3000）")
    parser.add_argument("--recent-min-comments", type=int, default=20, help="最近组评论门槛（默认 20）")
    parser.add_argument("--out", type=str, default="", help="输出目录（默认 data/bili_pick/<时间戳>）")
    parser.add_argument(
        "--reuse-candidates",
        type=str,
        default="",
        help="复用已有 candidates.csv 只重算选片（不打任何搜索请求）",
    )
    args = parser.parse_args()
    if not args.keyword and not args.reuse_candidates:
        parser.error("至少提供一个 --keyword（或用 --reuse-candidates 离线重算）")

    out_dir = Path(args.out) if args.out else Path("data") / "bili_pick" / time.strftime("%Y%m%d_%H%M%S")
    if args.reuse_candidates:
        sel = reselect(
            Path(args.reuse_candidates),
            per_group=max(1, args.per_group),
            recent_days=max(1, args.recent_days),
            out_dir=out_dir,
            recent_min_play=max(0, args.recent_min_play),
            recent_min_comments=max(0, args.recent_min_comments),
        )
    else:
        sel = asyncio.run(
            collect(
            args.keyword,
            per_group=max(1, args.per_group),
            recent_days=max(1, args.recent_days),
            pages=max(1, args.pages),
                out_dir=out_dir,
                recent_min_play=max(0, args.recent_min_play),
                recent_min_comments=max(0, args.recent_min_comments),
            )
        )

    def show(title: str, rows: List[Dict[str, Any]]) -> None:
        print(f"\n== {title}（{len(rows)} 个）")
        for r in rows:
            print(
                f"  {r['like']:>7} 赞 / {r['play']:>8} 播 / {r['comments']:>5} 评 | "
                f"{r['pubdate_str']} | {r['author'][:10]:<10} | {r['title'][:38]} | {r['bvid']}"
            )

    show("高赞组（按真实点赞）", sel["hot"])
    show(f"最近组（近 {sel['recent_days']} 天）", sel["recent"])
    print(
        f"\n候选 {sel['candidate_total']} 个 → 选中 {sel['selected_total']} 个；"
        f"这些视频当前评论区合计约 {sel['selected_comments_sum']} 条（评论数含子评论前的大盘值）"
    )
    print(f"清单：{out_dir / 'selection.json'}")
    if sel["failures"]:
        print("\n失败请求：")
        for f in sel["failures"]:
            print(f"  [{f['error']['code']}] {f['group']}/{f['keyword']} p{f['page']}: {f['error']['message']}")
        sys.exit(3)


if __name__ == "__main__":
    main()
