# -*- coding: utf-8 -*-
"""Phase 3.6: demand-first / asset-first 模式 + mock 经验隔离。"""

import pytest

from api.services.growth import seeds, store
from api.services.growth.orchestrator import Orchestrator, SessionConfig
from api.services.growth.tools import ToolContext, execute_tool
from api.services.growth.models import (
    ContentAsset,
    LearningRecord,
    LicenseStatus,
    Signal,
    SignalSourceType,
)


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    return ToolContext(product_id="youvibe", session_id="s_p36")


def test_demand_first_opportunity_requires_production_need(ctx):
    r = execute_tool("create_opportunity", {
        "problem": "想学 AI 动画但素材库无教程", "verdict": "hold",
        "verdict_rationale": "有需求无素材",
    }, ctx, {})
    assert r.status == "error" and "production_need" in r.error


def test_demand_first_never_recommend_publish(ctx):
    r = execute_tool("create_opportunity", {
        "problem": "想学 AI 动画", "verdict": "recommend",
        "verdict_rationale": "需求强", "production_need": "制作零基础教程",
    }, ctx, {})
    assert r.status == "ok"
    assert r.data["opportunity_kind"] == "demand_first"
    assert r.data["verdict"] == "hold"  # 待制作机会不能直接 recommend 发布


def test_asset_ready_opportunity_rejects_unlicensed(ctx):
    store.upsert_asset(ContentAsset(asset_id="u1", product_id="youvibe", title="t",
                                    license_status=LicenseStatus.UNKNOWN))
    r = execute_tool("create_opportunity", {
        "problem": "p", "verdict": "recommend", "verdict_rationale": "r",
        "usable_assets": ["u1"],
    }, ctx, {})
    assert r.status == "denied" and "授权" in r.error


def test_brief_requires_assets(ctx):
    r = execute_tool("create_content_brief", {
        "title": "t", "problem": "p", "rationale": "r", "hook": "h",
        "visit_reason": "v", "asset_ids": [],
    }, ctx, {})
    assert r.status == "error" and "demand_first" in r.error


def test_mock_learnings_excluded_from_formal_recall(ctx):
    # 真实经验
    store.upsert_learning(LearningRecord(learning_id="l_real", product_id="youvibe",
                                         what_tested="真实实验A", outcome="o"))
    # mock 会话写入
    mock_ctx = ToolContext(product_id="youvibe", session_id="s_m", mock=True)
    execute_tool("record_learning", {"what_tested": "mock试验", "outcome": "x"}, mock_ctx, {})
    stored = {r.learning_id: r for r in store.list_learnings("youvibe")}
    assert stored["l_real"].data_nature == "real"
    mock_ids = [k for k, v in stored.items() if v.data_nature == "mock"]
    assert len(mock_ids) == 1
    # 默认检索排除 mock
    real_ctx = ToolContext(product_id="youvibe", session_id="s_r")
    r = execute_tool("recall_learnings", {}, real_ctx, {})
    assert r.data["total"] == 1 and r.data["learnings"][0]["learning_id"] == "l_real"
    # 显式要求才可见
    r2 = execute_tool("recall_learnings", {"include_mock": True}, real_ctx, {})
    assert r2.data["total"] == 2


def test_mock_agent_creates_demand_first_when_no_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    store.add_signals([Signal(signal_id="s1", product_id="youvibe",
                              source_type=SignalSourceType.EXTERNAL_COMMENT,
                              need_or_problem="想学 AI 动画制作")])
    s = Orchestrator(SessionConfig(product_id="youvibe", goal="推荐下周最值得做的内容",
                                   use_mock=True)).run()
    assert s.status == "done"
    opps = store.list_opportunities("youvibe")
    assert len(opps) == 1
    assert opps[0].opportunity_kind == "demand_first"
    assert opps[0].verdict == "hold" and opps[0].production_need
    assert store.list_briefs("youvibe") == []  # 不产出可发布任务书


def test_mock_agent_no_signals_still_admits_insufficient(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    s = Orchestrator(SessionConfig(product_id="youvibe", goal="推荐内容", use_mock=True)).run()
    assert s.status == "done"
    assert "数据不足" in s.final_answer
    assert store.list_opportunities("youvibe") == []
