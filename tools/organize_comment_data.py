#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Organize legacy flat comment CSV files into per-video subfolders.

Before:
  data/comments/bili/csv/detail_comments_2026-07-17.csv
  data/comments/bili/csv/detail_videos_2026-07-17.csv
  ...

After:
  data/comments/{title_slug}_{video_key}/bili/csv/detail_comments_2026-07-17.csv
  ...
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.save_path_utils import build_video_folder_slug, join_video_save_path

LEGACY_RELATIVE = Path("bili/csv")
DETAIL_PREFIX = "detail_"


def extract_video_key(video_row: dict) -> str:
    video_url = (video_row.get("video_url") or "").strip()
    bv_match = re.search(r"/video/(BV[a-zA-Z0-9]+)", video_url, re.I)
    if bv_match:
        return bv_match.group(1)
    bvid = (video_row.get("bvid") or video_row.get("BV") or "").strip()
    if bvid:
        return bvid if bvid.upper().startswith("BV") else f"BV{bvid}"
    video_id = (video_row.get("video_id") or "").strip()
    if video_id:
        return f"av{video_id}"
    return "unknown"


def read_csv_rows(path: Path) -> tuple[list[str], list[dict]]:
    if not path.is_file():
        return [], []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        return fieldnames, list(reader)


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def discover_legacy_dates(base_dir: Path) -> list[str]:
    legacy_dir = base_dir / LEGACY_RELATIVE
    if not legacy_dir.is_dir():
        return []
    dates = set()
    for path in legacy_dir.glob(f"{DETAIL_PREFIX}*_*.csv"):
        match = re.match(rf"{DETAIL_PREFIX}(\w+)_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$", path.name)
        if match:
            dates.add(match.group(2))
    return sorted(dates)


def organize_legacy_data(base_dir: Path, dry_run: bool = False) -> list[dict]:
    legacy_dir = base_dir / LEGACY_RELATIVE
    if not legacy_dir.is_dir():
        return []

    results: list[dict] = []
    for date_str in discover_legacy_dates(base_dir):
        videos_path = legacy_dir / f"{DETAIL_PREFIX}videos_{date_str}.csv"
        comments_path = legacy_dir / f"{DETAIL_PREFIX}comments_{date_str}.csv"
        creators_path = legacy_dir / f"{DETAIL_PREFIX}creators_{date_str}.csv"

        video_fields, video_rows = read_csv_rows(videos_path)
        comment_fields, comment_rows = read_csv_rows(comments_path)
        creator_fields, creator_rows = read_csv_rows(creators_path)

        if not video_rows and not comment_rows:
            continue

        comments_by_video: dict[str, list[dict]] = defaultdict(list)
        for row in comment_rows:
            comments_by_video[(row.get("video_id") or "").strip()].append(row)

        creators_by_user = {(row.get("user_id") or "").strip(): row for row in creator_rows}

        if not video_rows and comments_by_video:
            for video_id in comments_by_video:
                video_rows.append(
                    {
                        "video_id": video_id,
                        "title": f"video_{video_id}",
                        "video_url": "",
                        "user_id": "",
                    }
                )

        for video_row in video_rows:
            video_id = (video_row.get("video_id") or "").strip()
            title = (video_row.get("title") or f"video_{video_id}").strip()
            video_key = extract_video_key(video_row)
            folder_slug = build_video_folder_slug(title, video_key)
            target_root = Path(join_video_save_path(str(base_dir), folder_slug))

            video_comments = comments_by_video.get(video_id, [])
            creator_id = (video_row.get("user_id") or "").strip()
            video_creators = [creators_by_user[creator_id]] if creator_id in creators_by_user else []

            result = {
                "date": date_str,
                "folder": folder_slug,
                "video_key": video_key,
                "title": title,
                "comments": len(video_comments),
                "videos": 1 if video_row else 0,
                "creators": len(video_creators),
                "target": str(target_root),
            }
            results.append(result)

            if dry_run:
                continue

            if video_fields and video_row:
                write_csv_rows(
                    target_root / f"videos_{date_str}.csv",
                    video_fields,
                    [video_row],
                )
            if comment_fields and video_comments:
                write_csv_rows(
                    target_root / f"comments_{date_str}.csv",
                    comment_fields,
                    video_comments,
                )
            if creator_fields and video_creators:
                write_csv_rows(
                    target_root / f"creators_{date_str}.csv",
                    creator_fields,
                    video_creators,
                )

    if not dry_run and results and legacy_dir.is_dir():
        backup_root = base_dir / "_legacy_flat" / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_dir.parent), str(backup_root / "bili"))
        legacy_parent = base_dir / "bili"
        if legacy_parent.exists() and not any(legacy_parent.rglob("*")):
            legacy_parent.rmdir()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Organize legacy flat B站 comment CSV files by video.")
    parser.add_argument(
        "--base",
        default="./data/comments",
        help="Comment data root directory (default: ./data/comments)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files")
    args = parser.parse_args()

    base_dir = Path(args.base).resolve()
    results = organize_legacy_data(base_dir, dry_run=args.dry_run)

    if not results:
        print("未发现需要整理的旧版扁平数据。")
        return

    print("整理结果：")
    for item in results:
        print(
            f"- [{item['date']}] {item['folder']}\n"
            f"  标题: {item['title'][:40]}{'…' if len(item['title']) > 40 else ''}\n"
            f"  评论 {item['comments']} 条 · 视频 {item['videos']} 条 · UP主 {item['creators']} 条\n"
            f"  目标: {item['target']}"
        )

    if args.dry_run:
        print("\n(dry-run 模式，未写入文件)")
    else:
        print(f"\n旧文件已备份到 {base_dir / '_legacy_flat'} 下。")


if __name__ == "__main__":
    main()
