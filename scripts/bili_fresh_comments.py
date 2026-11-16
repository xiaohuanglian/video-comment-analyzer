"""Collect recent Bilibili root comments for the existing reply-screening pipeline.

The search, fingerprint, persistence and pacing are reused from the crawler.
This driver adds a recent-comment cutoff and an atomic resumable manifest.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("CDP_CONNECT_EXISTING", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

config.PLATFORM = "bili"
config.CDP_CONNECT_EXISTING = False
config.CDP_HEADLESS = True

from playwright.async_api import async_playwright  # noqa: E402

from api.services.json_store import lock_for, read_json, write_json  # noqa: E402
from media_platform.bilibili.client import BilibiliClient  # noqa: E402
from media_platform.bilibili.exception import DataFetchError  # noqa: E402
from media_platform.bilibili.field import CommentOrderType, SearchOrderType  # noqa: E402
from tools import utils  # noqa: E402
from tools.browser_fingerprint import read_browser_fingerprint  # noqa: E402
from tools.cdp_browser import CDPBrowserManager  # noqa: E402
from tools.crawl_pacing import (  # noqa: E402
    classify_failure,
    ensure_platform_available,
)

DEFAULT_KEYWORDS = [
    "AI生图 提示词",
    "AI绘画 提示词",
    "提示词 教程",
    "AI视频 提示词",
    "AI海报 教程",
    "AI作品 复刻",
    "AI生图 教程",
    "AI绘画 教程",
]
def _clean_title(value: Any) -> str:
    return str(value or "").replace('<em class="keyword">', "").replace("</em>", "").strip()


def _comment_row(video_id: str, item: dict[str, Any]) -> dict[str, Any]:
    content = item.get("content") or {}
    member = item.get("member") or {}
    return {
        "comment_id": str(item.get("rpid") or ""),
        "parent_comment_id": str(item.get("parent") or "0"),
        "create_time": int(item.get("ctime") or 0),
        "video_id": str(video_id),
        "content": str(content.get("message") or ""),
        "user_id": str(member.get("mid") or ""),
        "nickname": str(member.get("uname") or ""),
        "sex": str(member.get("sex") or ""),
        "sign": str(member.get("sign") or ""),
        "avatar": str(member.get("avatar") or ""),
        "sub_comment_count": str(item.get("rcount") or 0),
        "like_count": int(item.get("like") or 0),
        "last_modify_ts": utils.get_current_timestamp(),
    }


def _content_row(video: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_id": str(video["aid"]),
        "bvid": str(video["bvid"]),
        "video_type": "video",
        "title": str(video["title"]),
        "desc": str(video.get("description") or ""),
        "create_time": int(video.get("pubdate") or 0),
        "user_id": str(video.get("mid") or ""),
        "nickname": str(video.get("author") or ""),
        "avatar": "",
        "liked_count": str(video.get("like") or 0),
        "video_play_count": str(video.get("play") or 0),
        "video_comment": str(video.get("review") or 0),
        "video_url": f"https://www.bilibili.com/video/{video['bvid']}",
        "source_keyword": str(video.get("keyword") or ""),
        "last_modify_ts": utils.get_current_timestamp(),
    }


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with lock_for(path), path.open("a", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    with lock_for(path):
        write_json(path, manifest)


def _video_order_key(video: dict[str, Any]) -> tuple[int, int]:
    return (int(video.get("review") or 0), int(video.get("pubdate") or 0))


async def _client(page: Any) -> BilibiliClient:
    cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
        page.context, urls=["https://www.bilibili.com"]
    )
    fingerprint = await read_browser_fingerprint(page, label="B站万条补采")
    return BilibiliClient(
        headers={
            **fingerprint.headers(),
            "Cookie": cookie_str,
            "Origin": "https://www.bilibili.com",
            "Referer": "https://www.bilibili.com",
            "Content-Type": "application/json;charset=UTF-8",
        },
        playwright_page=page,
        cookie_dict=cookie_dict,
    )


async def _search(
    client: BilibiliClient, keywords: list[str], pages: int, cutoff: int
) -> list[dict[str, Any]]:
    videos: dict[str, dict[str, Any]] = {}
    for keyword in keywords:
        for page_no in range(1, pages + 1):
            result = await client.search_video_by_keyword(
                keyword=keyword,
                page=page_no,
                page_size=20,
                order=SearchOrderType.LAST_PUBLISH,
                pubtime_begin_s=cutoff,
            )
            for item in result.get("result") or []:
                bvid = str(item.get("bvid") or "")
                if not bvid or not item.get("aid"):
                    continue
                videos.setdefault(
                    bvid,
                    {
                        "aid": int(item["aid"]),
                        "bvid": bvid,
                        "title": _clean_title(item.get("title")),
                        "description": str(item.get("description") or ""),
                        "author": str(item.get("author") or ""),
                        "mid": str(item.get("mid") or ""),
                        "play": int(item.get("play") or 0),
                        "like": int(item.get("like") or 0),
                        "review": int(item.get("review") or 0),
                        "pubdate": int(item.get("pubdate") or 0),
                        "keyword": keyword,
                    },
                )
            print(f"SEARCH {keyword} p{page_no}: {len(videos)} videos", flush=True)
            await client._pacer.sleep("after recent-video search")
    return sorted(videos.values(), key=_video_order_key, reverse=True)


async def _collect_video(
    client: BilibiliClient,
    video: dict[str, Any],
    out_dir: Path,
    manifest: dict[str, Any],
    args: argparse.Namespace,
) -> int:
    saved = 0
    state = manifest.setdefault("video_states", {}).setdefault(
        video["bvid"], {"next_cursor": 0, "status": "running"}
    )
    cursor = int(state.get("next_cursor") or 0)
    empty_pages = 0
    while saved < args.per_video:
        result = await client.get_video_comments(video["aid"], CommentOrderType.TIME, cursor)
        replies = result.get("replies") or []
        cursor_info = result.get("cursor") or {}
        state["next_cursor"] = cursor_info.get("next") or cursor
        rows = [_comment_row(str(video["aid"]), item) for item in replies]
        rows = [row for row in rows if row["comment_id"] and row["create_time"] >= args.cutoff_ts]
        rows = [row for row in rows if row["comment_id"] not in args.seen_ids]
        reached_stale = any(int(item.get("ctime") or 0) < args.cutoff_ts for item in replies)
        _append_jsonl(out_dir / f"comments_{args.date}.jsonl", rows)
        args.seen_ids.update(row["comment_id"] for row in rows)
        saved += len(rows)
        manifest["root_comments"] += len(rows)
        manifest["pages"] += 1
        print(
            f"COMMENTS {video['bvid']} cursor={cursor}: +{len(rows)} / video={saved} "
            f"batch={manifest['root_comments']}",
            flush=True,
        )
        _save_manifest(out_dir / "manifest.json", manifest)
        if manifest["root_comments"] >= args.target:
            state["status"] = "running"
            break
        if reached_stale:
            state["status"] = "freshness_cutoff"
            print(f"FRESHNESS_CUTOFF {video['bvid']}", flush=True)
            break
        empty_pages = empty_pages + 1 if not replies else 0
        if empty_pages >= 3 or cursor_info.get("is_end", True):
            state["status"] = "completed"
            break
        next_cursor = cursor_info.get("next")
        if not isinstance(next_cursor, int) or next_cursor == cursor:
            state["status"] = "completed"
            break
        cursor = next_cursor
        await client._pacer.sleep("after recent-comment page")
    _save_manifest(out_dir / "manifest.json", manifest)
    return saved


async def run(args: argparse.Namespace) -> dict[str, Any]:
    ensure_platform_available("bili")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out_dir / "manifest.json"
    manifest = read_json(manifest_path, default={}, expect=dict)
    manifest.update(
        status="running",
        started_at=manifest.get("started_at") or datetime.now().isoformat(timespec="seconds"),
        updated_at=datetime.now().isoformat(timespec="seconds"),
        target=args.target,
        freshness_hours=args.freshness_hours,
        cutoff_ts=args.cutoff_ts,
        keywords=args.keywords,
        root_comments=int(manifest.get("root_comments") or 0),
        pages=int(manifest.get("pages") or 0),
        errors=[],
    )
    _save_manifest(manifest_path, manifest)
    manager = CDPBrowserManager()
    try:
        async with async_playwright() as playwright:
            context = await manager.launch_and_connect(
                playwright, None, None, headless=not args.headful
            )
            page = await context.new_page()
            await page.goto("https://www.bilibili.com", wait_until="commit", timeout=90000)
            await page.wait_for_function(
                "() => document.readyState !== 'loading'", timeout=90000
            )
            client = await _client(page)
            account = await client.get("/x/web-interface/nav")
            if not account.get("isLogin"):
                raise DataFetchError("B站登录态失效", code=-101)
            print(f"LOGIN_OK level={(account.get('level_info') or {}).get('current_level')}", flush=True)
            videos = await _search(client, args.keywords, args.search_pages, args.video_cutoff_ts)
            _save_manifest(manifest_path, {**manifest, "videos": videos, "status": "collecting"})
            for video in videos:
                if manifest["root_comments"] >= args.target:
                    break
                if (manifest.get("video_states", {}).get(video["bvid"], {}).get("status")) in (
                    "completed",
                    "freshness_cutoff",
                ):
                    continue
                ensure_platform_available("bili")
                print(f"VIDEO {video['bvid']} comments~{video['review']} {video['title']}", flush=True)
                if str(video["aid"]) not in args.seen_videos:
                    content_path = args.out_dir / f"contents_{args.date}.jsonl"
                    _append_jsonl(content_path, [_content_row(video)])
                    args.seen_videos.add(str(video["aid"]))
                try:
                    await _collect_video(client, video, args.out_dir, manifest, args)
                except DataFetchError as exc:
                    failure = client._pacer.on_failure(exc)
                    manifest["errors"].append({"video": video["bvid"], **failure.to_dict()})
                    _save_manifest(manifest_path, manifest)
                    raise RuntimeError(failure.to_text()) from exc
                await client._pacer.sleep("between recent-comment videos")
        manifest["status"] = "completed" if manifest["root_comments"] >= args.target else "partial"
        return manifest
    except Exception as exc:
        failure = classify_failure(exc, platform="bili")
        manifest.update(status="stopped", stop_reason=failure.to_text())
        raise
    finally:
        manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _save_manifest(manifest_path, manifest)
        await manager.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--target", type=int, default=10000)
    parser.add_argument("--freshness-hours", type=int, default=168)
    parser.add_argument("--video-days", type=int, default=30)
    parser.add_argument("--search-pages", type=int, default=3)
    parser.add_argument("--per-video", type=int, default=1000)
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS))
    args = parser.parse_args()
    args.keywords = [word.strip() for word in args.keywords.split(",") if word.strip()]
    args.date = time.strftime("%Y-%m-%d")
    args.cutoff_ts = int(time.time()) - args.freshness_hours * 3600
    args.video_cutoff_ts = int(time.time()) - args.video_days * 86400
    config.CDP_HEADLESS = not args.headful
    args.seen_ids = set()
    args.seen_videos = set()
    comments_path = args.out_dir / f"comments_{args.date}.jsonl"
    if comments_path.exists():
        for line in comments_path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                row = json.loads(line)
                if row.get("comment_id"):
                    args.seen_ids.add(str(row["comment_id"]))
    contents_path = args.out_dir / f"contents_{args.date}.jsonl"
    if contents_path.exists():
        for line in contents_path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                row = json.loads(line)
                if row.get("video_id"):
                    args.seen_videos.add(str(row["video_id"]))
    result = asyncio.run(run(args))
    print(json.dumps({"status": result["status"], "root_comments": result["root_comments"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
