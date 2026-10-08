# -*- coding: utf-8 -*-
"""Phase 3.5: evaluation harness, dedupe interception, import batches."""

import pytest

from api.services.growth import seeds, store
from api.services.growth.evaluate import (
    EVAL_TASKS,
    export_scoresheet_csv,
    run_evaluation,
    verify_record_integrity,
)
from api.services.growth.models import (
    ContentAsset,
    ContentBrief,
    GrowthOpportunity,
    LicenseStatus,
    MetricsObservation,
    MetricKind,
    Signal,
    SignalSourceType,
)
from api.services.growth.orchestrator import Orchestrator, SessionConfig, build_session_summary
from api.services.growth.tools import ToolContext, execute_tool


@pytest.fixture()
def product(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))  # attribution=none
    return "youvibe"


def test_integrity_detects_fabricated_asset(product):
    store.upsert_asset(ContentAsset(asset_id="a1", product_id="youvibe", title="t",
                                    license_status=LicenseStatus.OWNED))
    store.upsert_brief(ContentBrief(brief_id="b_bad", product_id="youvibe", title="t",
                                    problem="p", rationale="r", hook="h", visit_reason="v",
                                    audience="u", asset_ids=["ghost_asset"],
                                    validation_metrics=["views"]))
    violations = verify_record_integrity("youvibe")
    assert any(v["rule"] == "asset_exists" and v["record"] == "b_bad" for v in violations)


def test_integrity_detects_unlicensed_and_missing_rationale(product):
    store.upsert_asset(ContentAsset(asset_id="a2", product_id="youvibe", title="t",
                                    license_status=LicenseStatus.UNKNOWN))
    store.upsert_opportunity(GrowthOpportunity(
        opportunity_id="op_bad", product_id="youvibe", problem="p",
        usable_assets=["a2"], verdict="recommend", verdict_rationale=""))
    rules = {v["rule"] for v in verify_record_integrity("youvibe")}
    assert "asset_licensed" in rules and "rationale_required" in rules


def test_integrity_unknown_discipline(product):
    store.add_observations([MetricsObservation(
        observation_id="o_bad", product_id="youvibe", metric_kind=MetricKind.PRODUCT,
        name="signups", value=100, attribution_note="")])
    violations = verify_record_integrity("youvibe")
    assert any(v["rule"] == "unknown_discipline" for v in violations)



def test_integrity_clean_passes(product):
    store.upsert_asset(ContentAsset(asset_id="a1", product_id="youvibe", title="t",
                                    license_status=LicenseStatus.OWNED))
    store.add_signals([Signal(signal_id="s1", product_id="youvibe",
                              source_type=SignalSourceType.EXTERNAL_COMMENT,
                              need_or_problem="n")])
    store.upsert_brief(ContentBrief(brief_id="b_ok", product_id="youvibe", title="t",
                                    problem="p", rationale="r", hook="h", visit_reason="v",
                                    audience="u", asset_ids=["a1"],
                                    evidence_refs=["s1"], validation_metrics=["views"]))
    assert verify_record_integrity("youvibe") == []


def test_mock_eval_smoke_marked(product):
    report = run_evaluation("youvibe", use_mock=True, max_tasks=3)
    assert report["mode"] == "mock"
    assert len(report["tasks"]) == 3
    assert all(t["mock"] for t in report["tasks"])
    csv_text = export_scoresheet_csv(report)
    assert "human_evidence_score" in csv_text and "t01" in csv_text
    assert len(EVAL_TASKS) == 10


def test_identical_repeat_calls_intercepted(product):
    class ScriptClient:
        n = 0

        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

        def create(self, **kw):
            from types import SimpleNamespace
            import json as j
            self.n += 1
            if self.n <= 2:
                tc = SimpleNamespace(id=f"c{self.n}", function=SimpleNamespace(
                    name="query_signals", arguments=j.dumps({"limit": 30})))
                msg = SimpleNamespace(content="", tool_calls=[tc])
            else:
                msg = SimpleNamespace(content="停止重复，直接回答", tool_calls=None)
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=msg)])

    s = Orchestrator(SessionConfig(product_id="youvibe", goal="g", use_mock=False),
                     client=ScriptClient()).run()
    assert s.status == "done"
    tool_msgs = [m for m in s.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    import json
    first = json.loads(tool_msgs[0]["content"])
    second = json.loads(tool_msgs[1]["content"])
    assert first["status"] == "ok"
    assert second["status"] == "denied" and "重复" in second["error"] or "拦截" in second["error"]
    # 审计只记录一次真实执行
    assert sum(1 for a in store.list_audit("youvibe") if a.action == "query_signals") == 1


def test_import_batch_recorded(product):
    ctx = ToolContext(product_id="youvibe", session_id="s1")
    execute_tool("import_assets", {"assets": [{"asset_id": "a1", "title": "t"}],
                                   "data_nature": "real", "note": "团队素材第一批"}, ctx, {})
    batches = store.list_import_batches("youvibe")
    assert batches and batches[0]["data_nature"] == "real" and batches[0]["count"] == 1


def test_session_summary(product):
    s = Orchestrator(SessionConfig(product_id="youvibe", goal="规划下周内容", use_mock=True,
                                   max_iterations=8)).run()
    summary = build_session_summary("youvibe", s.session_id)
    assert summary["data_inventory"]["signals"] == 0
    assert any("无用户信号" in g for g in summary["data_gaps"])
    assert any("站内转化不可验证" in g for g in summary["data_gaps"])  # attribution=none
    assert summary["pending_human"]["note"]
    assert summary["tools_called"]
