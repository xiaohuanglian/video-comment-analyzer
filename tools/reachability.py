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




# ---------------------------------------------------------------------------
# 路由 → UI 可达性
#
# 起因（2026-11-11 审计）：上面的 dangling() 只看 Python import，抓不到
# 「后端有 47 条路由、前端一行都没调用」这种情况。/api/analysis/* 与
# /api/growth/*（共 93 条）在移除旧前端后一直没有 React 入口，而
# PROJECT_STATE 与 README 仍把它们写成已交付功能。
# ---------------------------------------------------------------------------

#: 明确声明「只给 CLI / 外部脚本用、不需要 Web UI」的前缀。
#: 新增条目必须写清楚为什么，否则测试会把它当成缺口。
UI_EXEMPT_PREFIXES = {
    "growth": "增长引擎是独立子系统（产品/实验/机会），当前按 CLI+API 方式使用",
    "data": "文件浏览接口服务于下载链接，页面内以 href 直接引用",
    "bilibili": "B 站直连调试接口，由 CLI 使用",
    "youvibe": "内部数据分析查询，随 skill 离线使用",
    "creator": "创作者排行由采集页间接调用，主页暂无独立入口",
    "hot-radar": "热点雷达尚未接前端",
}


def backend_prefixes(root: Path = ROOT) -> Dict[str, int]:
    """从 APIRouter(prefix=...) 提取前缀与该前缀下的路由数。"""
    import re

    counts: Dict[str, int] = {}
    routers = root / "api" / "routers"
    if not routers.is_dir():
        return counts
    for path in sorted(routers.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        match = re.search(r'APIRouter\(prefix="/([^"]+)"', text)
        if not match:
            continue
        prefix = match.group(1).split("/")[0]
        counts[prefix] = len(re.findall(r"@router\.(?:get|post|patch|put|delete)", text))
    return counts


#: 判定「这个前缀算不算接进 UI」的门槛：至少 3 条**核心**路由被调用。
#:
#: 不用「覆盖率比例」做门槛——真实页面只调用少数几条主干路由
#: （洞察 47 条里 InsightPage 只用 6 条，这就是正常的）。
#: 3 条的门槛足够挡掉「只调一条设置接口就宣称接入」的假阳性。
UI_COVERAGE_MIN_ROUTES = 3


def frontend_called_paths(root: Path = ROOT) -> Set[str]:
    """前端 API 客户端里请求过的 `路径` 与 `方法 路径`（去掉 query）。

    同时返回 `方法 路径` 形式，是因为同一路径可能对应多条路由
    （如 `/strategy` 的 GET 与 PUT），只看路径会漏计。

    实现上按 `req<...>('路径'` 逐处切分，并从该处往后到下一个 `req(`
    之间找 method——不能跨语句贪婪匹配，否则会把下一条调用的
    method 张冠李戴（这曾让 chat 被误判成没接入）。
    """
    import re

    client = root / "web_react" / "src" / "lib" / "api.ts"
    if not client.exists():
        return set()
    text = client.read_text(encoding="utf-8")

    starts = [m.start() for m in re.finditer(r"req(?:<[^>]*>)?\(\s*[`'\"]", text)]
    starts.append(len(text))
    found: Set[str] = set()
    for begin, nxt in zip(starts, starts[1:]):
        chunk = text[begin:nxt]
        path_match = re.search(r"req(?:<[^>]*>)?\(\s*[`'\"]([^`'\"]+)[`'\"]", chunk)
        if not path_match:
            continue
        path = path_match.group(1).split("?")[0].strip("/")
        if not path:
            continue
        found.add(path)
        method_match = re.search(r"method:\s*[`'\"]([A-Za-z]+)[`'\"]", chunk)
        method = (method_match.group(1) if method_match else "GET").upper()
        found.add(f"{method} {path}")
    return found


def routes_without_ui(root: Path = ROOT) -> Dict[str, int]:
    """后端有路由、前端基本没用的前缀（已排除 UI_EXEMPT_PREFIXES）。

    判定「基本没用」：该前缀下被前端调用到的路由条数少于 UI_COVERAGE_MIN_ROUTES。
    """
    called_paths = frontend_called_paths(root)
    missing: Dict[str, int] = {}
    for prefix, count in backend_prefixes(root).items():
        if prefix in UI_EXEMPT_PREFIXES:
            continue
        # 按「方法 + 路径」计数：`/strategy` 的 GET/PUT 是两条路由。
        # 也兼容「前缀即全部路径」的写法（不能要求一定有两段）。
        covered = sum(
            1
            for entry in called_paths
            if entry.split("/")[0] == prefix
            or (len(entry.split(" ")) == 2 and entry.split(" ", 1)[1].split("/")[0] == prefix)
        )
        # 小前缀（≤3 条路由）只要全部被调用就算接入了；
        # 大前缀至少要接上 UI_COVERAGE_MIN_ROUTES 条主干路由。
        needed = min(UI_COVERAGE_MIN_ROUTES, count)
        if covered >= needed:
            continue
        missing[prefix] = count
    return missing



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

    missing_ui = routes_without_ui()
    if missing_ui:
        print(f"\n后端有路由但没有前端调用的前缀 {len(missing_ui)} 个：")
        for prefix, count in sorted(missing_ui.items()):
            print(f"  /api/{prefix}  ({count} 条路由)")
    else:
        print("\n所有后端路由前缀都有前端调用方（或已在 UI_EXEMPT_PREFIXES 声明豁免）。")


if __name__ == "__main__":
    main()
