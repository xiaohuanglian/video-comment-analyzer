# -*- coding: utf-8 -*-
"""Report-level ranking and sampling transparency."""

from __future__ import annotations

from api.services.insight import readable_report
from api.services.insight.readable_report import build_readable_report
from api.services.insight.schemas import SourceRecord


def _rec(rid: str, text: str) -> SourceRecord:
    return SourceRecord(
        internal_record_id=rid,
        source_file="a.csv",
        source_row_number=1,
        comment_text=text,
        user_id=rid,
        username=f"u-{rid}",
    )


def _finding(name: str, ids: list[str]) -> dict:
    return {
        "finding": name,
        "conclusion": "存在一致问题",
        "why_it_matters": "值得进一步验证",
        "record_ids": ids,
        "supporting_evidence_refs": [{"record_id": rid} for rid in ids],
        "limitations": "样本有限",
        "next_step": "小样本验证",
    }


def test_findings_ranked_by_user_count_and_hidden_counted(monkeypatch):
    monkeypatch.setattr(readable_report, "MAX_REPORT_FINDINGS", 2)
    records = [_rec(f"r{i}", f"问题 {i}") for i in range(6)]
    research = {
        "dataset_summary": {"total_comments": 6, "unique_users": 6, "usable_comments": 6},
        "unexpected_findings": [
            _finding("小发现", ["r0"]),
            _finding("大发现", ["r1", "r2", "r3", "r4"]),
            _finding("中发现", ["r5"]),
        ],
        "themes": [],
    }
    md = build_readable_report(research=research, records=records, card_rows=[], run_id="t")
    # Highest-user finding must be expanded first.
    assert "### 发现 1：大发现" in md
    # Third finding is above threshold but not expanded; it must be counted.
    assert "另有 1 条达到证据门槛的发现" in md


def test_report_states_analyzed_coverage():
    records = [_rec("r1", "这个动作怎么做？")]
    research = {
        "dataset_summary": {"total_comments": 1, "unique_users": 1, "usable_comments": 1},
        "unexpected_findings": [],
        "themes": [],
    }
    md = build_readable_report(research=research, records=records, card_rows=[], run_id="t")
    assert "本报告基于 0 / 1 条评论的证据卡" in md