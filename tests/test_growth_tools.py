# -*- coding: utf-8 -*-
"""Phase 2: tool registry permissions, audit, limits (场景 G 切片)."""

import pytest

from api.services.growth import seeds, store
from api.services.growth.models import ContentAsset, MetricsObservation, MetricKind
from api.services.growth.tools import REGISTRY, ToolContext, execute_tool


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    return ToolContext(product_id="youvibe", session_id="s_test")


def test_l1_tool_executes(ctx):
    r = execute_tool("query_assets", {}, ctx, {})
    assert r.status == "ok" and r.data["total"] == 0


def test_l3_always_denied(ctx):
    r = execute_tool("send_external_reply", {"to": "u1", "content": "hi"}, ctx, {})
    assert r.status == "denied"
    audits = store.list_audit("youvibe")
    assert audits[-1].action == "send_external_reply" and audits[-1].status == "denied"


def test_l2_requires_grant(ctx):
    r = execute_tool("crawl_external", {"platform": "bilibili", "target": "BV1"}, ctx, {})
    assert r.status == "denied" and "L2" in r.error
    ctx2 = ToolContext(product_id="youvibe", session_id="s2", l2_grants=["crawl_external"])
    r2 = execute_tool("crawl_external", {"platform": "bilibili", "target": "BV1"}, ctx2, {})
    assert r2.status == "ok"


def test_per_session_call_cap(ctx):
    counts = {}
    for _ in range(2):
        r = execute_tool("import_signals_from_run", {"run_id": "nope"}, ctx, counts)
        assert r.status == "error"  # run 不存在 → 安全报错，不计数
    results = [execute_tool("query_signals", {}, ctx, counts) for _ in range(6)]
    assert all(r.status == "ok" for r in results[:5])
    assert results[5].status == "denied" and "上限" in results[5].error


def test_schema_validation(ctx):
    r = execute_tool("get_run_summary", {}, ctx, {})
    assert r.status == "error" and "run_id" in r.error


def test_unknown_tool(ctx):
    assert execute_tool("delete_everything", {}, ctx, {}).status == "error"


def test_match_assets_blocks_unlicensed(ctx):
    store.upsert_asset(ContentAsset(asset_id="a1", product_id="youvibe",
                                    title="AI 动画怎么做", topics=["AI 动画"],
                                    license_status="owned"))
    store.upsert_asset(ContentAsset(asset_id="a2", product_id="youvibe",
                                    title="AI 动画搬运素材", topics=["AI 动画"],
                                    license_status="unknown"))
    from api.services.growth.models import Signal, SignalSourceType
    store.add_signals([Signal(signal_id="s1", product_id="youvibe",
                              source_type=SignalSourceType.EXTERNAL_COMMENT,
                              need_or_problem="这个 AI 动画到底是怎么做的")])
    r = execute_tool("match_assets_to_needs", {}, ctx, {})
    assert r.status == "ok"
    m = r.data["matches"][0]
    assert m["usable_assets"] == ["a1"] and m["blocked_unlicensed"] == ["a2"]


def test_metrics_note_flags_no_attribution(ctx):
    store.add_observations([MetricsObservation(
        observation_id="o1", product_id="youvibe", experiment_id="e1",
        metric_kind=MetricKind.REACH, name="views", value=100, verified=True)])
    r = execute_tool("compute_experiment_metrics", {"experiment_id": "e1"}, ctx, {})
    assert r.status == "ok"
    assert r.data["attribution_capability"] == "none"
    assert "不可验证" in r.data["note"]


def test_audit_records_accumulate(ctx):
    execute_tool("query_assets", {}, ctx, {})
    execute_tool("recall_learnings", {}, ctx, {})
    actions = [a.action for a in store.list_audit("youvibe")]
    assert "query_assets" in actions and "recall_learnings" in actions
