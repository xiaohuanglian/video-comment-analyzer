#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flatten nested bili/csv folders into per-video root folders."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

NESTED_MARKERS = (
    Path("bili/csv"),
    Path("bili"),
)


def flatten_video_folder(video_dir: Path, dry_run: bool = False) -> list[str]:
    actions: list[str] = []
    nested_csv = video_dir / "bili" / "csv"
    if not nested_csv.is_dir():
        return actions

    for src in nested_csv.glob("*"):
        if not src.is_file():
            continue
        dest_name = src.name.replace("detail_", "", 1) if src.name.startswith("detail_") else src.name
        dest = video_dir / dest_name
        actions.append(f"{src} -> {dest}")
        if not dry_run:
            if dest.exists():
                dest.unlink()
            shutil.move(str(src), str(dest))

    if not dry_run:
        shutil.rmtree(video_dir / "bili", ignore_errors=True)
    return actions


def flatten_all(base_dir: Path, dry_run: bool = False) -> None:
    if not base_dir.is_dir():
        print("目录不存在:", base_dir)
        return

    total = 0
    for child in sorted(base_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        actions = flatten_video_folder(child, dry_run=dry_run)
        if actions:
            print(f"\n[{child.name}]")
            for action in actions:
                print(" ", action)
            total += len(actions)

    legacy_bili = base_dir / "bili"
    if legacy_bili.is_dir() and not dry_run:
        shutil.rmtree(legacy_bili, ignore_errors=True)
        print("\n已删除旧版扁平目录:", legacy_bili)

    legacy_flat = base_dir / "_legacy_flat"
    if legacy_flat.is_dir() and not dry_run:
        shutil.rmtree(legacy_flat, ignore_errors=True)
        print("已删除备份目录:", legacy_flat)

    if total == 0:
        print("没有需要扁平化的嵌套目录。")
    elif dry_run:
        print(f"\n(dry-run，共 {total} 个文件待移动)")
    else:
        print(f"\n完成，共处理 {total} 个文件。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Flatten per-video nested bili/csv folders.")
    parser.add_argument("--base", default="./data/comments")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    flatten_all(Path(args.base).resolve(), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
