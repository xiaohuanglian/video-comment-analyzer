# -*- coding: utf-8 -*-
"""模块可达性分析：找出「有测试、没用户」的悬空模块。

起因（2026-11-06）：`api/services/style/` 4006 行、13 个模块，测试全绿、
台账记「已落地」，但没有 router、没有页面、没有 CLI —— 生产引用数为 0。
测试绿只证明函数对，不证明有人调用。这个脚本把「有没有人调用」变成可断言的事实。

用法：
    uv run python -m tools.reachability            # 打印悬空模块
    uv run python -m tools.reachability --write    # 把当前状态写成基线

判定口径：
    入口 = api/main.py + main.py + api/routers/* + tools/*.py + scripts/* + cmd_arg/*
    悬空 = 从入口出发、沿静态 import 边不可达的模块
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Dict, Iterable, List, Set

ROOT = Path(__file__).resolve().parent.parent

# 不参与分析的目录（数据/前端/虚拟环境/测试自身）
SKIP_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "web_react",
    "tests",
    "data",
    "docs",
    "cache",
    "browser_data",
    ".git",
    ".pytest_cache",
}

# 只关心这些包：它们是「本项目的服务层」，需要有人调用
SERVICE_PREFIXES = ("api.services", "api.schemas")


def module_name(path: Path, root: Path = ROOT) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_package_file(path: Path) -> bool:
    return path.name == "__init__.py"


def build_index(root: Path = ROOT) -> Dict[str, Path]:
    """模块名 -> 文件路径，覆盖项目所有源码。"""
    index: Dict[str, Path] = {}
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.parts and rel.parts[0].startswith("."):
            continue
        index[module_name(path, root)] = path
    return index


def _package_of(path: Path, root: Path = ROOT) -> str:
    """文件所属包；不在包内（无 __init__.py）时返回空串。"""
    name = module_name(path, root)
    if _is_package_file(path):
        return name
    parent = path.parent
    if not (parent / "__init__.py").exists():
        return ""
    return name.rsplit(".", 1)[0] if "." in name else ""


def _resolve_relative(module: str | None, level: int, path: Path, root: Path) -> str | None:
    package = _package_of(path, root)
    if not package:
        return None
    parts = package.split(".")
    drop = level - 1
    if drop > 0:
        if drop >= len(parts):
            parts = []
        else:
            parts = parts[: len(parts) - drop]
    base = ".".join(parts)
    if module:
        return f"{base}.{module}" if base else module
    return base or None


def imports_of(path: Path, root: Path = ROOT) -> Set[str]:
    """文件静态 import 到的模块名（含 `from pkg import name` 展开的 name）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                target = _resolve_relative(node.module, node.level, path, root)
            else:
                target = node.module
            if not target:
                continue
            found.add(target)
            # 导入 a.b.c 会连带导入包 a、a.b，否则包 __init__ 会被误判成悬空
            parts = target.split(".")
            for i in range(1, len(parts)):
                found.add(".".join(parts[:i]))
            for alias in node.names:
                if alias.name != "*":
                    found.add(f"{target}.{alias.name}")
    return found


def entry_modules(root: Path = ROOT) -> List[str]:
    """真实入口：Web 服务、CLI 主程序、路由、工具脚本、命令行参数层。"""
    roots: List[str] = []
    for rel in ("api/main.py", "main.py"):
        if (root / rel).exists():
            roots.append(module_name(root / rel, root))
    for sub in ("api/routers", "tools", "scripts", "cmd_arg"):
        directory = root / sub
        if directory.is_dir():
            roots.extend(module_name(p, root) for p in sorted(directory.rglob("*.py")))
    return roots


def reachable(root: Path = ROOT) -> Set[str]:
    index = build_index(root)
    seen: Set[str] = set()
    stack = [m for m in entry_modules(root) if m in index]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for dep in imports_of(index[current], root):
            if dep in index and dep not in seen:
                stack.append(dep)
    return seen

def dangling(root: Path = ROOT) -> List[str]:
    """服务层里从入口不可达的模块，按名字排序。"""
    seen = reachable(root)
    index = build_index(root)
    return sorted(m for m in index if m.startswith(SERVICE_PREFIXES) and m not in seen)

def line_count(module: str, root: Path = ROOT) -> int:
    path = build_index(root).get(module)
    if not path:
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def read_baseline(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    entries = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return entries


def write_baseline(path: Path, modules: Iterable[str]) -> None:
    lines = [
        "# 已知悬空模块基线（2026-11-06）",
        "# 一行一个模块。新增模块不许再进这里，要么接线、要么显式写理由。",
        "# 已接线的模块必须从本文件删除（测试会检查）。",
        "",
    ]
    for module in sorted(modules):
        lines.append(module)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="悬空模块可达性分析")
    parser.add_argument("--write", action="store_true", help="把当前悬空模块写成基线")
    parser.add_argument(
        "--baseline",
        default="tests/service_reachability_baseline.txt",
        help="基线文件路径（相对仓库根目录）",
    )
    args = parser.parse_args()

    modules = dangling()
    if args.write:
        target = ROOT / args.baseline
        target.parent.mkdir(parents=True, exist_ok=True)
        write_baseline(target, modules)
        print(f"已写入 {target.relative_to(ROOT)}（{len(modules)} 个模块）")
        return

    total = sum(line_count(m) for m in modules)
    print(f"悬空模块 {len(modules)} 个，共 {total} 行：")
    for module in modules:
        print(f"  {module}  ({line_count(module)} 行)")


if __name__ == "__main__":
    main()
