# -*- coding: utf-8 -*-
"""清理 data/ 下的临时与可重建产物。

背景（2026-11-11 审计）：
`data/` 是一个**独立本地 git 仓库**（永不 push），但长期积累了大量
可重建/无价值的内容：

- `data/creators/_tmp/raw/_asr/**/*.part`：60MB 的 ASR 中间文件残留
- `data/.insight/`：每次分析都会生成的中间态（散落在各处）
- `data/topics/*.corrupt-*`：JSON 损坏时的留档（由 json_store 生成）
- `__pycache__` / `.DS_Store`：系统垃圾

这些都是「删了不心疼、留着会撑大仓库」的东西。本脚本只删它们，
**绝不动** comments / wechat / youtube_comments 等采集结果。

用法：
    uv run python -m scripts.prune_data --dry-run     # 先看会删什么
    uv run python -m scripts.prune_data               # 真删
    uv run python -m scripts.prune_data --keep-corrupt  # 保留损坏留档
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

#: 只清理这些「可再生成」的目录/文件模式。
#: 采集结果（comments / wechat / youtube_comments / xhs_browse）绝不在此列。
PRUNE_PATTERNS: tuple[str, ...] = (
    "creators/_tmp",       # 风格学习的下载/ASR 中间文件
    "creators/**/_asr",    # ASR 工作目录
    ".insight",            # 分析中间态
    "**/__pycache__",
)

PRUNE_SUFFIXES: tuple[str, ...] = (".part", ".tmp")
PRUNE_NAMES: tuple[str, ...] = (".DS_Store",)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(DATA_DIR))
    except ValueError:
        return str(path)


def _dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"


def collect_targets(*, keep_corrupt: bool) -> list[tuple[Path, int]]:
    """返回 [(待删路径, 字节数)]，已去重（父目录优先）。"""
    if not DATA_DIR.exists():
        return []

    found: list[Path] = []
    for pattern in PRUNE_PATTERNS:
        for path in DATA_DIR.glob(pattern):
            if path.exists():
                found.append(path)

    for path in DATA_DIR.rglob("*"):
        if path.is_file():
            if path.suffix in PRUNE_SUFFIXES or path.name in PRUNE_NAMES:
                found.append(path)
            elif not keep_corrupt and ".corrupt-" in path.name:
                found.append(path)

    # 父目录已包含的，不再单独列出
    found.sort(key=lambda p: len(p.parts))
    kept: list[Path] = []
    for path in found:
        if any(parent == path or parent in path.parents for parent in kept):
            continue
        kept.append(path)
    return [(p, (_dir_size(p) if p.is_dir() else p.stat().st_size)) for p in kept]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清理 data/ 下的可重建产物")
    parser.add_argument("--dry-run", action="store_true", help="只列出，不删除")
    parser.add_argument("--keep-corrupt", action="store_true", help="保留 *.corrupt-* 损坏留档")
    args = parser.parse_args(argv)

    targets = collect_targets(keep_corrupt=args.keep_corrupt)
    if not targets:
        print("没有需要清理的产物。")
        return 0

    total = sum(size for _, size in targets)
    print(f"待清理 {len(targets)} 项，共 {_human(total)}：")
    for path, size in targets:
        print(f"  {_human(size):>9}  {_rel(path)}")

    if args.dry_run:
        print("\n（dry-run，未删除任何文件）")
        return 0

    removed = 0
    for path, _ in targets:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed += 1
        except OSError as exc:
            print(f"  跳过 {_rel(path)}：{exc}", file=sys.stderr)
    print(f"\n已删除 {removed}/{len(targets)} 项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
