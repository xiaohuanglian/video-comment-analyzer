# -*- coding: utf-8 -*-
"""Ensure analysis prompts match product spec."""

from api.services.insight.prompts import HYPOTHESES


def test_hypotheses_match_product_spec():
    assert "训练动力" in HYPOTHESES["H1"]
    assert "单向视频无法" in HYPOTHESES["H2"]
    assert "Agent" in HYPOTHESES["H3"] or "规划" in HYPOTHESES["H3"]
    assert "伤病" not in HYPOTHESES["H1"]
    assert "轻量" not in HYPOTHESES["H3"]

