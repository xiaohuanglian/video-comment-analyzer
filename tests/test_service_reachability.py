# -*- coding: utf-8 -*-
"""门禁：不许再产出「测试绿、但没人调用」的服务模块。

判据只有一条：服务模块必须真的被 router、页面或 CLI 调用，光有测试不算落地。

本测试把「被调用」变成可断言的事实：
  1. 新出现的悬空模块 -> 失败（要么接线，要么别写）
  2. 基线里已经接线的条目 -> 失败（保持基线诚实，防止被当成永久白名单）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import reachability

BASELINE = Path(__file__).with_name("service_reachability_baseline.txt")


def test_no_new_dangling_service_modules():
    """不许新增悬空模块。"""
    baseline = reachability.read_baseline(BASELINE)
    actual = set(reachability.dangling())
    new = sorted(actual - baseline)

    if new:
        detail = "\n".join(
            f"  - {module}（{reachability.line_count(module)} 行）" for module in new
        )
        pytest.fail(
            "以下模块没有任何生产调用方（router / 页面 / CLI 都碰不到），"
            "只有测试在用：\n"
            f"{detail}\n\n"
            "处理方式二选一：\n"
            "  1. 接线：让 api/routers 或 tools/scripts 真正调用它；\n"
            "  2. 不接线：删掉，或确认要留后在 "
            f"{BASELINE.name} 里登记并写清理由。\n"
            "（只加测试不加调用，等于给自己发一张作业已完成证明。）"
        )


def test_baseline_has_no_stale_entries():
    """基线里的模块如果已经接线，必须从基线删除。"""
    baseline = reachability.read_baseline(BASELINE)
    actual = set(reachability.dangling())
    stale = sorted(baseline - actual)

    if stale:
        detail = "\n".join(f"  - {module}" for module in stale)
        pytest.fail(
            f"以下模块已经从 {BASELINE.name} 失效（要么已接线，要么已被删除），"
            "请从基线移除，别让它变成永久白名单：\n"
            f"{detail}"
        )


def test_analyzer_detects_dangling_module(tmp_path: Path):
    """分析器自身有效性：能识别出没被引用的模块。"""
    (tmp_path / "api" / "services").mkdir(parents=True)
    (tmp_path / "api" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "api" / "main.py").write_text("from .services import live\n", encoding="utf-8")
    (tmp_path / "api" / "services" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "api" / "services" / "live.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "api" / "services" / "dead.py").write_text("VALUE = 2\n", encoding="utf-8")

    assert reachability.dangling(tmp_path) == ["api.services.dead"]


def test_analyzer_resolves_relative_imports(tmp_path: Path):
    """相对 import 也要算作可达，否则会误报。"""
    (tmp_path / "api" / "routers").mkdir(parents=True)
    (tmp_path / "api" / "services").mkdir(parents=True)
    (tmp_path / "api" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "api" / "main.py").write_text("from .routers import use\n", encoding="utf-8")
    (tmp_path / "api" / "routers" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "api" / "routers" / "use.py").write_text(
        "from ..services.helper import thing\n", encoding="utf-8"
    )
    (tmp_path / "api" / "services" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "api" / "services" / "helper.py").write_text("thing = 1\n", encoding="utf-8")

    assert reachability.dangling(tmp_path) == []


def test_analyzer_treats_package_init_as_reachable(tmp_path: Path):
    """`from ..services import helper` 这种包导入要能把子模块带上。"""
    (tmp_path / "api" / "routers").mkdir(parents=True)
    (tmp_path / "api" / "services").mkdir(parents=True)
    (tmp_path / "api" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "api" / "main.py").write_text("from .routers import use\n", encoding="utf-8")
    (tmp_path / "api" / "routers" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "api" / "routers" / "use.py").write_text(
        "from ..services import helper\n", encoding="utf-8"
    )
    (tmp_path / "api" / "services" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "api" / "services" / "helper.py").write_text("thing = 1\n", encoding="utf-8")

    assert reachability.dangling(tmp_path) == []


# ---------------------------------------------------------------------------
# 路由 → UI 可达性
#
# 2026-11-11：上面的 dangling() 只看 Python import，抓不到
# 「后端有路由、前端一行都没调用」。这里按前缀核对一遍，避免某个
# 路由悄悄变成没有 UI 入口的孤儿。
# ---------------------------------------------------------------------------


def test_no_backend_prefix_without_ui():
    """后端有路由、前端却没接入的前缀，必须接线或显式豁免。"""
    missing = reachability.routes_without_ui()
    if not missing:
        return
    detail = "\n".join(f"  - /api/{p}（{c} 条路由）" for p, c in sorted(missing.items()))
    pytest.fail(
        "以下后端能力没有任何前端入口：\n"
        f"{detail}\n\n"
        "处理方式二选一：\n"
        "  1. 接进 web_react（至少接上主干路由）；\n"
        "  2. 确认只给 CLI/脚本用，则加入 tools/reachability.UI_EXEMPT_PREFIXES 并写清理由。"
    )


def test_insight_prefix_is_wired_to_a_page():
    """洞察链路应至少接上几个主干端点。"""
    called = reachability.frontend_called_paths()
    insight_calls = [p for p in called if p.split("/")[0] == "analysis"]
    assert len(insight_calls) >= 3, "InsightPage 应至少接上几个主干端点"


def test_ui_exemptions_are_documented():
    """豁免表里每一条都要有理由，避免变成随手加的免死金牌。"""
    for prefix, reason in reachability.UI_EXEMPT_PREFIXES.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 8, f"{prefix} 的豁免理由太短"


def test_detector_flags_prefix_without_ui(tmp_path: Path):
    """检测器有效性：造一个后端有、前端没有的前缀，必须被抓出来。"""
    routers = tmp_path / "api" / "routers"
    routers.mkdir(parents=True)
    (routers / "ghost.py").write_text(
        'from fastapi import APIRouter\nrouter = APIRouter(prefix="/ghost")\n'
        '@router.get("/a")\nasync def a():\n    return {}\n'
        '@router.post("/b")\nasync def b():\n    return {}\n',
        encoding="utf-8",
    )
    client = tmp_path / "web_react" / "src" / "lib"
    client.mkdir(parents=True)
    (client / "api.ts").write_text(
        "export const api = {\n  other: () => req<X>('/other/thing'),\n}\n", encoding="utf-8"
    )

    missing = reachability.routes_without_ui(tmp_path)
    assert "ghost" in missing


def test_detector_accepts_prefix_with_enough_ui_calls(tmp_path: Path):
    """接上足够多主干路由后就不该再被报缺失。"""
    routers = tmp_path / "api" / "routers"
    routers.mkdir(parents=True)
    (routers / "live.py").write_text(
        'from fastapi import APIRouter\nrouter = APIRouter(prefix="/live")\n'
        '@router.get("/a")\nasync def a():\n    return {}\n'
        '@router.post("/b")\nasync def b():\n    return {}\n'
        '@router.get("/c")\nasync def c():\n    return {}\n',
        encoding="utf-8",
    )
    client = tmp_path / "web_react" / "src" / "lib"
    client.mkdir(parents=True)
    (client / "api.ts").write_text(
        "export const api = {\n"
        "  a: () => req<X>('/live/a'),\n"
        "  b: () => req<X>('/live/b', { method: 'POST', body: '{}' }),\n"
        "  c: () => req<X>('/live/c'),\n"
        "}\n",
        encoding="utf-8",
    )

    assert "live" not in reachability.routes_without_ui(tmp_path)


def test_detector_reads_split_api_clients_but_not_test_requests(tmp_path: Path):
    client = tmp_path / "web_react" / "src" / "lib"
    client.mkdir(parents=True)
    (client / "extra-api.ts").write_text("req<X>('/analysis/runs')", encoding="utf-8")
    (client / "api.test.ts").write_text("req<X>('/phantom/not-production')", encoding="utf-8")
    called = reachability.frontend_called_paths(tmp_path)
    assert "analysis/runs" in called
    assert not any("phantom" in path for path in called)
