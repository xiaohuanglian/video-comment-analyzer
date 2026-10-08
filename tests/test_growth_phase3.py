# -*- coding: utf-8 -*-
"""Phase 3: content loop — assets import, briefs, publish results, review."""

import pytest

from api.services.growth import demo_data, seeds, store
from api.services.growth.models import BriefStatus, ContentBrief
from api.services.growth.tools import ToolContext, execute_tool


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    return ToolContext(product_id="youvibe", session_id="s_p3")


def _mk_brief(ctx, brief_id="b1", status="draft"):
    store.upsert_brief(ContentBrief(brief_id=brief_id, product_id="youvibe", title="T",
                                    problem="p", rationale="r", hook="h", visit_reason="v",
                                    status=status))


def test_import_assets_defaults_unknown_license(ctx):
    r = execute_tool("import_assets", {"assets": [{"asset_id": "a9", "title": "新素材"}]}, ctx, {})
    assert r.status == "ok"
    asset = [a for a in store.list_assets("youvibe") if a.asset_id == "a9"][0]
    assert asset.license_status == "unknown"


def test_brief_requires_existing_licensed_assets(ctx):
    execute_tool("import_assets", {"assets": [
        {"asset_id": "ok1", "title": "已授权", "license_status": "owned"},
        {"asset_id": "bad1", "title": "未授权", "license_status": "unknown"},
    ]}, ctx, {})
    args = {"title": "t", "problem": "p", "rationale": "r", "hook": "h", "visit_reason": "v"}
    # 不存在的素材 → 拒绝虚构
    r = execute_tool("create_content_brief", {**args, "asset_ids": ["ghost"]}, ctx, {})
    assert r.status == "error" and "素材不存在" in r.error
    # 未授权素材 → 权限拒绝
    r = execute_tool("create_content_brief", {**args, "asset_ids": ["bad1"]}, ctx, {})
    assert r.status == "denied" and "授权" in r.error
    # 已授权素材 → 成功草稿
    r = execute_tool("create_content_brief", {**args, "asset_ids": ["ok1"]}, ctx, {})
    assert r.status == "ok" and r.data["status"] == "draft"


def test_experiment_requires_approved_brief(ctx):
    execute_tool("import_assets", {"assets": [{"asset_id": "ok1", "title": "t", "license_status": "owned"}]}, ctx, {})
    _mk_brief(ctx, "b1", status="draft")
    r = execute_tool("create_experiment", {"goal": "g", "hypothesis": "h", "brief_id": "b1"}, ctx, {})
    assert r.status == "denied" and "批准" in r.error
    # 批准后（模拟人工审批）
    _mk_brief(ctx, "b1", status="approved")
    r = execute_tool("create_experiment", {"goal": "g", "hypothesis": "h", "brief_id": "b1"}, ctx, {})
    assert r.status == "ok"
    exp = [e for e in store.list_experiments("youvibe") if e.experiment_id == r.data["experiment_id"]][0]
    assert exp.brief_id == "b1" and exp.status == "planned"


def test_publish_results_unknown_not_zero(ctx):
    execute_tool("import_assets", {"assets": [{"asset_id": "ok1", "title": "t", "license_status": "owned"}]}, ctx, {})
    _mk_brief(ctx, "b1", status="approved")
    r = execute_tool("create_experiment", {"goal": "g", "hypothesis": "h", "brief_id": "b1"}, ctx, {})
    exp_id = r.data["experiment_id"]
    r2 = execute_tool("record_publish_results", {
        "experiment_id": exp_id, "channel": "bilibili",
        "url": "https://b23.tv/x", "published_at": "2026-04-01",
        "metrics": {"views": 5000, "valid_visits": 120, "signups": None},
        "period_start": "2026-04-01", "period_end": "2026-04-08",
    }, ctx, {})
    assert r2.status == "ok"
    assert r2.data["unknown_metrics"] == ["signups"]
    obs = store.list_observations("youvibe", experiment_id=exp_id)
    by_name = {o.name: o for o in obs}
    assert by_name["signups"].value is None  # Unknown 而不是 0
    assert by_name["views"].metric_kind.value == "reach"
    assert by_name["valid_visits"].metric_kind.value == "traffic"
    assert by_name["signups"].metric_kind.value == "product"
    exp = [e for e in store.list_experiments("youvibe")][0]
    assert exp.status == "running" and exp.publish_records[0].url


def test_review_experiments_facts_not_ranking(ctx):
    execute_tool("import_assets", {"assets": [{"asset_id": "ok1", "title": "t", "license_status": "owned"}]}, ctx, {})
    _mk_brief(ctx, "b1", status="approved")
    r = execute_tool("create_experiment", {"goal": "g", "hypothesis": "教程导流高", "brief_id": "b1"}, ctx, {})
    exp_id = r.data["experiment_id"]
    execute_tool("record_publish_results", {
        "experiment_id": exp_id, "channel": "douyin",
        "metrics": {"views": 300, "valid_visits": 30, "signups": None},
    }, ctx, {})
    r2 = execute_tool("review_experiments", {}, ctx, {})
    assert r2.status == "ok"
    fact = r2.data["experiments"][0]
    assert fact["metrics_known"]["reach"]["views"] == 300
    assert fact["visit_per_view"] == 0.1
    assert "signups" in fact["metrics_unknown"]
    assert fact["sample_flag"] == "small_sample"  # 播放<1000 标记样本不足
    assert r2.data["attribution_warning"]  # youvibe 种子档案 attribution=none


def test_demo_seed_idempotent_and_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    c1 = demo_data.seed_demo_dataset()
    assert c1["assets"] == 5 and c1["signals"] == 100
    assert c1["historical_observations"] == 7
    c2 = demo_data.seed_demo_dataset()  # 幂等
    assert c2["assets"] == 0 and c2["signals"] == 0 and c2["historical_observations"] == 0
    assert len(store.list_signals(demo_data.DEMO_PRODUCT_ID)) == 100
    # 与真实产品隔离
    assert store.list_signals("youvibe") == []
    assert "DEMO" in store.get_product(demo_data.DEMO_PRODUCT_ID).name
    # 演示数据能驱动复盘工具：播放高≠导流好
    ctx = ToolContext(product_id=demo_data.DEMO_PRODUCT_ID, session_id="s_demo")
    r = execute_tool("review_experiments", {}, ctx, {})
    fact = r.data["experiments"][0]
    assert fact["metrics_known"]["traffic"]["valid_visits"] == 1180 + 460 + 940
    assert "signups" in fact["metrics_unknown"]
