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
