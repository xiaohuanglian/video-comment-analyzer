# -*- coding: utf-8 -*-
"""Phase 2.5B: real-shaped evidence_items_v1 run → signal adapter verification."""

import pytest

from api.services.growth import seeds, store
from api.services.growth.tools import ToolContext, execute_tool
from api.services.insight import storage as run_storage
from api.services.insight.schemas import (
    CommentAnalysisResult,
    FieldMapping,
    NewSignal,
    NewSignalType,
    PrimaryIntent,
    RunConfig,
    SourceRecord,
)


@pytest.fixture()
def run_with_results(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")
    monkeypatch.setattr(store, "GROWTH_ROOT", data_dir / "growth")

    records = [
        SourceRecord(internal_record_id=f"csv:1:{i}", source_file="comments.csv",
                     source_row_number=i, comment_text=f"评论{i}", platform="bilibili")
        for i in range(1, 6)
    ]
    config = RunConfig(run_id="demo_run", name="demo", file_paths=["comments.csv"],
                       field_mapping=FieldMapping(comment_text="content"), use_mock=True)
    run_storage.create_run(config, records)
    # 模拟真实 evidence_items_v1：potential_needs 常为空，new_signals 富含文本
    analyses = [
        CommentAnalysisResult(record_id="csv:1:1", primary_intent=PrimaryIntent.QUESTION,
                              new_signals=[NewSignal(type=NewSignalType.NEW_PROBLEM,
                                                     text="这个 AI 动画到底是怎么做的",
                                                     evidence_quote="这个 AI 动画到底是怎么做的")],
                              evidence_quotes=["这个 AI 动画到底是怎么做的"], confidence=0.8),
        CommentAnalysisResult(record_id="csv:1:2", primary_intent=PrimaryIntent.QUESTION,
                              new_signals=[NewSignal(type=NewSignalType.NEW_PROBLEM,
                                                     text="这个 AI 动画到底是怎么做的",
                                                     evidence_quote="q2")],
                              evidence_quotes=["q2"], confidence=0.7),
        CommentAnalysisResult(record_id="csv:1:3", primary_intent=PrimaryIntent.DIFFICULTY,
                              potential_needs=["想要系统教程"],
                              evidence_quotes=["有系统教程吗"], confidence=0.9),
        CommentAnalysisResult(record_id="csv:1:4", primary_intent=PrimaryIntent.GRATITUDE),  # 无需求 → 跳过
        CommentAnalysisResult(record_id="csv:1:5", primary_intent=PrimaryIntent.QUESTION,
                              new_signals=[NewSignal(type=NewSignalType.NEW_SCENE,
                                                     text="想用 AI 生成网页",
                                                     evidence_quote="q5")],
                              confidence=0.6),
    ]
    for rec, ana in zip(records, analyses):
        run_storage.append_result("demo_run", rec, ana)

    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    return ToolContext(product_id="youvibe", session_id="s_adapter")


def test_top_needs_reads_new_signals(run_with_results):
    r = execute_tool("get_run_top_needs", {"run_id": "demo_run", "limit": 5}, run_with_results, {})
    assert r.status == "ok"
    needs = dict(r.data["top_needs"])
    problems = dict(r.data["top_problems"])
    assert needs.get("想要系统教程") == 1
    assert problems.get("这个 AI 动画到底是怎么做的") == 2  # new_problem 聚类
    assert needs.get("想用 AI 生成网页") == 1  # new_scene 走 needs
    assert r.data["sample_quotes"]["evidence_quotes"]


def test_import_signals_real_shape_and_idempotent(run_with_results):
    r1 = execute_tool("import_signals_from_run", {"run_id": "demo_run"}, run_with_results, {})
    assert r1.status == "ok"
    assert r1.data["imported"] == 4  # csv:1:4 无需求被安全跳过
    assert r1.data["skipped_duplicates"] == 0

    r2 = execute_tool("import_signals_from_run", {"run_id": "demo_run"}, run_with_results, {})
    assert r2.status == "ok"
    assert r2.data["imported"] == 0 and r2.data["skipped_duplicates"] == 4  # 幂等

    signals = store.list_signals("youvibe")
    assert len(signals) == 4
    # 原始证据引用保留
    assert all(s.evidence_refs for s in signals)
    by_rid = {s.evidence_refs[0]: s for s in signals}
    # new_signals 回退生效
    assert by_rid["csv:1:1"].need_or_problem == "这个 AI 动画到底是怎么做的"
    # 证据引用（quote）保存在内部分类字段中
    assert by_rid["csv:1:1"].ai_classification["evidence_quotes"] == ["这个 AI 动画到底是怎么做的"]
    # 默认为内部使用，不外发
    assert all(s.usage_rights == "internal_only" for s in signals)
    # 其他产品无数据（隔离）
    assert store.list_signals("trainmind") == []


def test_import_with_missing_fields_safe(run_with_results):
    # csv:1:5 无 evidence_quotes / potential_needs：应安全处理
    r = execute_tool("import_signals_from_run", {"run_id": "demo_run"}, run_with_results, {})
    assert r.status == "ok"
    s5 = [s for s in store.list_signals("youvibe") if s.evidence_refs == ["csv:1:5"]][0]
    assert s5.need_or_problem == "想用 AI 生成网页"
    assert s5.ai_classification["evidence_quotes"] == []
