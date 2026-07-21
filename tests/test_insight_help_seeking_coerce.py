# -*- coding: utf-8 -*-
"""Coerce messy LLM help_seeking values and aggregate error reasons."""

from api.services.insight.schemas import (
    CommentAnalysisLLMOutput,
    PrimaryIntent,
    RunProgress,
    coerce_boolish,
    is_status_only_message,
    summarize_error_message,
)


def test_coerce_boolish_handles_common_llm_mistakes():
    assert coerce_boolish(True) is True
    assert coerce_boolish(False) is False
    assert coerce_boolish([]) is False
    assert coerce_boolish(["x"]) is False
    assert coerce_boolish("question") is False
    assert coerce_boolish("询问如何防止滑动") is False
    assert coerce_boolish("true") is True
    assert coerce_boolish("是") is True
    assert coerce_boolish("0") is False


def test_llm_output_accepts_non_bool_help_seeking():
    payload = {
        "primary_intent": PrimaryIntent.QUESTION.value,
        "help_seeking": [],
        "hypothesis_relations": [
            {"hypothesis_id": "H1", "relation": "irrelevant", "evidence_quote": ""},
            {"hypothesis_id": "H2", "relation": "irrelevant", "evidence_quote": ""},
            {"hypothesis_id": "H3", "relation": "irrelevant", "evidence_quote": ""},
        ],
    }
    out = CommentAnalysisLLMOutput.model_validate(payload)
    assert out.help_seeking is False

    payload["help_seeking"] = "question"
    out2 = CommentAnalysisLLMOutput.model_validate(payload)
    assert out2.help_seeking is False


def test_error_summary_groups_help_seeking_failures():
    msg_a = (
        "LLM 返回 JSON 无法解析: 1 validation error for CommentAnalysisLLMOutput\n"
        "help_seeking\n  Input should be a valid boolean, unable to interpret input "
        "[type=bool_parsing, input_value='question', input_type=str]"
    )
    msg_b = (
        "LLM 返回 JSON 无法解析: 1 validation error for CommentAnalysisLLMOutput\n"
        "help_seeking\n  Input should be a valid boolean [type=bool_type, input_value=[], input_type=list]"
    )
    key_a = summarize_error_message(msg_a)
    key_b = summarize_error_message(msg_b)
    assert key_a == key_b

    progress = RunProgress(
        failed=2,
        failed_record_ids=["r1", "r2"],
        failed_errors={"r1": msg_a, "r2": msg_b},
        last_error=msg_b,
    )
    summary = progress.error_summary
    assert len(summary) == 1
    assert summary[0]["count"] == 2
    assert "help_seeking" in summary[0]["message"]


def test_error_summary_ignores_stop_message_without_failed_errors():
    assert is_status_only_message("用户已停止分析")
    progress = RunProgress(
        failed=147,
        failed_record_ids=["r1"],
        last_error="用户已停止分析",
    )
    assert progress.error_summary == []
