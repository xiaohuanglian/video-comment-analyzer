# -*- coding: utf-8 -*-
"""Theme schema coercion tests."""

from __future__ import annotations

from api.services.insight.theme_schemas import Round1ResponseLLM, Round2ResponseLLM


def test_round1_accepts_missing_theme_type():
    parsed = Round1ResponseLLM.model_validate(
        {
            "candidate_themes": [
                {
                    "theme_name": "久坐导致腰痛",
                    "definition": "用户反馈久坐后腰痛",
                    "included_signal_ids": ["s0001"],
                    "confidence": 0.8,
                }
            ]
        }
    )
    assert parsed.candidate_themes[0].theme_type == "other"
    assert parsed.candidate_themes[0].theme_name == "久坐导致腰痛"


def test_round1_accepts_type_alias_and_list_root():
    parsed = Round1ResponseLLM.model_validate(
        [
            {
                "name": "膝盖运动不适",
                "type": "new_problem",
                "desc": "练完膝盖疼",
                "signals": ["s0002"],
                "confidence": 0.9,
            }
        ]
    )
    theme = parsed.candidate_themes[0]
    assert theme.theme_name == "膝盖运动不适"
    assert theme.theme_type == "new_problem"
    assert theme.definition == "练完膝盖疼"
    assert theme.included_signal_ids == ["s0002"]


def test_round1_accepts_integer_signal_ids():
    parsed = Round1ResponseLLM.model_validate(
        {
            "candidate_themes": [
                {
                    "theme_name": "斜方肌粗大",
                    "theme_type": "new_problem",
                    "definition": "用户反馈斜方肌问题",
                    "included_signal_ids": [3401, 3402, "s3403"],
                    "confidence": 0.8,
                }
            ]
        }
    )
    assert parsed.candidate_themes[0].included_signal_ids == ["3401", "3402", "s3403"]


def test_resolve_signal_ids_maps_bare_numbers():
    from api.services.insight.theme_clustering import resolve_signal_ids

    valid = {"s3401", "s3402", "s3415"}
    assert resolve_signal_ids(["3401", "3402", "s3415", "9999"], valid) == [
        "s3401",
        "s3402",
        "s3415",
    ]


def test_round2_accepts_missing_theme_type():
    parsed = Round2ResponseLLM.model_validate(
        {
            "themes": [
                {
                    "theme_name": "实用内容反馈",
                    "included_signal_ids": ["s0003"],
                    "confidence": 0.7,
                }
            ]
        }
    )
    assert parsed.themes[0].theme_type == "other"
    assert parsed.themes[0].definition == "实用内容反馈"


def test_round2_accepts_integer_signal_ids():
    parsed = Round2ResponseLLM.model_validate(
        {
            "themes": [
                {
                    "theme_name": "肩颈问题",
                    "included_signal_ids": [3411, 3417],
                    "confidence": 0.6,
                }
            ]
        }
    )
    assert parsed.themes[0].included_signal_ids == ["3411", "3417"]


def test_truncated_json_error_detection():
    from api.services.insight.theme_clustering import _is_truncated_json_error

    assert _is_truncated_json_error(
        RuntimeError("Unterminated string starting at: line 16 column 71")
    )
    assert _is_truncated_json_error(ValueError("x"), finish_reason="length")
    assert _is_truncated_json_error(
        RuntimeError("主题模型调用失败，已重试 3 次：output truncated by max_tokens")
    )
    assert not _is_truncated_json_error(RuntimeError("connection reset"))


def test_round2_prompt_uses_compact_candidate_references():
    from api.services.insight.theme_prompts import build_round2_user_message

    prompt = build_round2_user_message(
        [
            {
                "candidate_id": "c0001",
                "theme_name": "肩颈不适",
                "theme_type": "new_problem",
                "definition": "训练后肩颈疼",
                "signal_count": 99,
                "included_signal_ids": ["s0001", "s0002", "s0003"],
            }
        ]
    )
    assert '"id":"c0001"' in prompt
    assert '"n":99' in prompt
    assert "s0001" not in prompt
