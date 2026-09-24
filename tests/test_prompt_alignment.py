# -*- coding: utf-8 -*-
"""Hypotheses must stay domain-neutral (no vertical-specific defaults)."""

from __future__ import annotations

from api.services.insight.prompts import HYPOTHESES, HYPOTHESIS_SHORT, SIGNAL_ENUM


def test_hypotheses_are_domain_neutral():
    for hid in ("H1", "H2", "H3"):
        assert HYPOTHESES[hid]
        assert HYPOTHESIS_SHORT[hid]
    joined = " ".join(HYPOTHESES.values()) + " ".join(HYPOTHESIS_SHORT.values())
    for banned in ("教程", "训练", "跟练", "步骤", "肌群", "老师"):
        assert banned not in joined


def test_signal_enum_is_domain_neutral():
    joined = " ".join(SIGNAL_ENUM)
    for banned in ("training", "muscle", "exercise", "coach", "video"):
        assert banned not in joined
