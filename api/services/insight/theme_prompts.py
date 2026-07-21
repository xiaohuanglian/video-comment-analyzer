# -*- coding: utf-8 -*-
"""Prompts for two-round open-theme clustering (token-lean)."""

from __future__ import annotations

import json
from typing import List

from .prompts import HYPOTHESIS_SHORT
from .theme_schemas import RawSignalItem

_HYP_LINE = " | ".join(f"{k} {v}" for k, v in HYPOTHESIS_SHORT.items())

ROUND1_SYSTEM = f"""将 new_signals 归并为候选主题。假设参考：{_HYP_LINE}

规则：只用输入 signal_id；勿编造；勿强行合并不同问题；勿输出评论数。
theme_name≤20字；definition/implication≤60字；
relation: supports_existing|extends_existing|weakens_existing|unrelated_notable；confidence 0~1。
输出JSON：{{"candidate_themes":[{{"theme_name":"","theme_type":"","definition":"","included_signal_ids":[],"relation_to_existing_hypotheses":"extends_existing","implication":"","confidence":0.0}}]}}"""

ROUND2_SYSTEM = f"""合并高度相似的候选开放主题。假设参考：{_HYP_LINE}

规则：included_signal_ids 仅来自输入；措辞不同但义同则合并；本质不同勿合并。
relation: supports_existing|extends_existing|weakens_existing|unrelated_notable。
输出JSON：{{"themes":[{{"theme_name":"","theme_type":"","definition":"","included_signal_ids":[],"relation_to_existing_hypotheses":"extends_existing","implication":"","confidence":0.0}}]}}"""


def _compact_json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_round1_user_message(signals: List[RawSignalItem]) -> str:
    payload = []
    for item in signals:
        quotes = item.sample_quotes[:2]
        # Drop quote identical to text
        quotes = [q for q in quotes if q and q != item.text]
        row = {
            "id": item.signal_id,
            "type": item.signal_type,
            "text": item.text,
            "n": item.frequency,
        }
        if quotes:
            row["q"] = quotes[:1]
        payload.append(row)
    return "归并新信号：\n" + _compact_json(payload)


def build_round2_user_message(candidates: List[dict]) -> str:
    slim = []
    for item in candidates:
        slim.append(
            {
                "theme_name": item.get("theme_name", ""),
                "theme_type": item.get("theme_type", ""),
                "definition": item.get("definition", ""),
                "included_signal_ids": item.get("included_signal_ids") or [],
                "relation_to_existing_hypotheses": item.get(
                    "relation_to_existing_hypotheses", "extends_existing"
                ),
                "implication": (item.get("implication") or "")[:80],
                "confidence": item.get("confidence", 0),
            }
        )
    return "合并候选主题：\n" + _compact_json(slim)
