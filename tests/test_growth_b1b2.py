# -*- coding: utf-8 -*-
"""Stage B1/B2: UserSegmentReport、目标理解路径（mock 占位）、连续对话。"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.growth import demo_data, seeds, store
from api.services.growth.orchestrator import Orchestrator, SessionConfig, load_session
from api.services.growth.tools import ToolContext, execute_tool
from api.services.growth.models import Signal, SignalSourceType


@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    return "youvibe"


def _seed_signals(pid, n=6):
    needs = ["这个 AI 动画到底怎么做的"] * 3 + ["AI 生成网页需要代码吗"] * 2 + ["能免费试吗"] * 1
    store.add_signals([
        Signal(signal_id=f"s{i}", product_id=pid, source_type=SignalSourceType.EXTERNAL_COMMENT,
               source_platform="bili", need_or_problem=needs[i], confidence=0.7)
        for i in range(len(needs))
    ])


def test_segment_report_validation(tmp_store):
    _seed_signals("youvibe")
    ctx = ToolContext(product_id="youvibe", session_id="s1")
    # 缺 data_limitations → 拒绝
    r = execute_tool("create_segment_report", {"goal": "g", "segments": []}, ctx, {})
    assert r.status == "error" and "data_limitations" in r.error
    # evidence 引用不存在 → 拒绝
    r = execute_tool("create_segment_report", {"goal": "g", "data_limitations": "样本少",
        "segments": [{"name": "x", "certainty": "evidenced", "evidence_refs": ["ghost"]}]}, ctx, {})
    assert r.status == "error" and "无法解析" in r.error
    # evidenced 但无引用 → 拒绝
    r = execute_tool("create_segment_report", {"goal": "g", "data_limitations": "x",
        "segments": [{"name": "x", "certainty": "evidenced"}]}, ctx, {})
    assert r.status == "error"
    # 合法
    r = execute_tool("create_segment_report", {"goal": "找用户", "data_limitations": "仅代理样本",
        "segments": [{"name": "AI 动画学习者", "core_needs": ["怎么做动画"],
                      "evidence_refs": ["s0", "s1"], "platforms": ["bili"],
                      "product_fit": "weak", "product_fit_reason": "部分重合",
                      "reach_methods": ["内容承接"], "hypothesized_channels": ["知识区"],
                      "certainty": "evidenced"}]}, ctx, {})
    assert r.status == "ok"
    reports = store.list_segment_reports("youvibe")
    assert len(reports) == 1
    seg = reports[0].segments[0]
    assert seg.certainty.value == "evidenced" and seg.platforms == ["bili"]
    assert seg.hypothesized_channels == ["知识区"]  # 推测渠道单列
    assert reports[0].created_by_session == "s1"


def test_mock_user_research_path(tmp_store):
    _seed_signals("youvibe")
    s = Orchestrator(SessionConfig(product_id="youvibe", goal="帮我找 YouVibe 的潜在用户",
                                   use_mock=True)).run()
    assert s.status == "done"
    reports = store.list_segment_reports("youvibe")
    assert len(reports) == 1  # 产出的是用户研究，不是内容选题
    assert store.list_briefs("youvibe") == []
    assert store.list_opportunities("youvibe") == []
    assert "代理" in reports[0].data_limitations or "不能代表" in reports[0].data_limitations


def test_mock_cross_goal_research_then_plan(tmp_store):
    _seed_signals("youvibe")
    from api.services.growth.models import ContentAsset, LicenseStatus
    store.upsert_asset(ContentAsset(asset_id="a1", product_id="youvibe", title="AI 动画教程素材",
                                    topics=["AI 动画"], license_status=LicenseStatus.OWNED))
    s = Orchestrator(SessionConfig(
        product_id="youvibe", goal="帮我找潜在用户，并据此规划下周内容", use_mock=True)).run()
    assert s.status == "done"
    assert len(store.list_segment_reports("youvibe")) == 1  # 先研究
    opps = store.list_opportunities("youvibe")
    assert len(opps) >= 1  # 再策划（复用证据，不重复查信号）


def test_mock_research_no_data_admits_insufficient(tmp_store):
    s = Orchestrator(SessionConfig(product_id="youvibe", goal="找潜在用户", use_mock=True)).run()
    assert s.status == "done" and "无法研究" in s.final_answer
    assert store.list_segment_reports("youvibe") == []


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    return TestClient(app)


def test_followup_keeps_context_and_no_duplicates(client):
    _seed_signals("youvibe")
    r = client.post("/api/growth/agent/run", json={
        "product_id": "youvibe", "goal": "帮我找 YouVibe 的潜在用户", "use_mock": True})
    parent = r.json()
    assert parent["status"] == "done"
    # 连续追问：深化第一个群体
    r2 = client.post(f"/api/growth/agent/sessions/{parent['session_id']}/followup",
                     params={"product_id": "youvibe"},
                     json={"message": "只保留第一个群体，深入分析", "use_mock": True})
    assert r2.status_code == 200
    assert r2.json()["parent_session_id"] == parent["session_id"]
    import time
    child = None
    for _ in range(30):
        time.sleep(0.4)
        child = client.get(f"/api/growth/agent/sessions/{r2.json()['session_id']}",
                           params={"product_id": "youvibe"}).json()
        if child["status"] != "running":
            break
    assert child["config"]["parent_session_id"] == parent["session_id"]
    assert "原目标" in child["config"]["extra_context"]
    # followup 走用户研究路径（关键词命中）→ 重复创建被幂等拦截
    assert len(store.list_segment_reports("youvibe")) <= 2
