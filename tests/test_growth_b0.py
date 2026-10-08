# -*- coding: utf-8 -*-
"""Stage B0: 幂等、任务归属、data_nature 隔离、审计 refs。"""

import pytest

from api.services.growth import demo_data, seeds, store
from api.services.growth.tools import ToolContext, execute_tool
from api.services.growth.models import ContentAsset, LicenseStatus


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    return ToolContext(product_id="youvibe", session_id="sess_A")


def _opp_args():
    return {"problem": "想学 AI 动画", "verdict": "hold", "verdict_rationale": "需求 34 条",
            "production_need": "制作零基础教程"}


def test_duplicate_opportunity_not_recreated(ctx):
    r1 = execute_tool("create_opportunity", _opp_args(), ctx, {})
    r2 = execute_tool("create_opportunity", _opp_args(), ctx, {})  # 相同请求重试
    r3 = execute_tool("create_opportunity", {**_opp_args(), "problem": "想学AI动画 ！"}, ctx, {})  # 归一化后同义
    assert r1.status == r2.status == r3.status == "ok"
    assert r1.data["deduped"] is False
    assert r2.data["deduped"] is True and r3.data["deduped"] is True
    assert r2.data["opportunity_id"] == r1.data["opportunity_id"]
    assert len(store.list_opportunities("youvibe")) == 1  # 重复请求不产生新记录


def test_task_ownership_and_nature(ctx):
    r = execute_tool("create_opportunity", _opp_args(), ctx, {})
    opp = store.list_opportunities("youvibe")[0]
    assert opp.created_by_session == "sess_A"  # 任务归属
    assert opp.data_nature == "real"  # 非 mock 会话


def test_mock_session_marks_mock(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    mctx = ToolContext(product_id="youvibe", session_id="s_m", mock=True)
    execute_tool("create_opportunity", _opp_args(), mctx, {})
    assert store.list_opportunities("youvibe")[0].data_nature == "mock"


def test_demo_product_marks_demo(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    demo_data.seed_demo_dataset()
    dctx = ToolContext(product_id="youvibe_demo", session_id="s_d")  # 非 mock ctx，但产品本身是演示
    r = execute_tool("create_opportunity", _opp_args(), dctx, {})
    assert r.status == "ok"
    opp = [o for o in store.list_opportunities("youvibe_demo") if o.problem == "想学 AI 动画"][0]
    assert opp.data_nature == "demo"


def test_brief_dedupe_and_audit_ref(ctx):
    store.upsert_asset(ContentAsset(asset_id="a1", product_id="youvibe", title="t",
                                    license_status=LicenseStatus.OWNED))
    args = {"title": "AI 动画教程", "problem": "想学", "rationale": "r", "hook": "h",
            "visit_reason": "v", "asset_ids": ["a1"]}
    r1 = execute_tool("create_content_brief", args, ctx, {})
    r2 = execute_tool("create_content_brief", args, ctx, {})
    assert r2.data["deduped"] is True and r2.data["brief_id"] == r1.data["brief_id"]
    assert len(store.list_briefs("youvibe")) == 1
    brief = store.list_briefs("youvibe")[0]
    assert brief.created_by_session == "sess_A"
    # 审计 refs 包含 brief_id（修复漏记）
    audit = store.list_audit("youvibe")
    brief_audits = [a for a in audit if a.action == "create_content_brief" and a.status == "ok"]
    assert brief_audits and brief_audits[0].output_refs == [r1.data["brief_id"]]


def test_different_versions_allowed(ctx):
    """同一机会的不同内容版本（不同标题/角度）不应被错误去重。"""
    store.upsert_asset(ContentAsset(asset_id="a1", product_id="youvibe", title="t",
                                    license_status=LicenseStatus.OWNED))
    base = {"problem": "想学 AI 动画", "rationale": "r", "hook": "h",
            "visit_reason": "v", "asset_ids": ["a1"]}
    r1 = execute_tool("create_content_brief", {**base, "title": "3分钟教会你 AI 动画"}, ctx, {})
    r2 = execute_tool("create_content_brief", {**base, "title": "AI 动画避坑指南"}, ctx, {})
    assert r1.data["deduped"] is False and r2.data["deduped"] is False
    assert len(store.list_briefs("youvibe")) == 2
