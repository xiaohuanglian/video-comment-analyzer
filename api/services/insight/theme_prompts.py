# -*- coding: utf-8 -*-
"""Prompts for two-round open-theme clustering (token-lean)."""

from __future__ import annotations

import json
from typing import List

from .theme_schemas import RawSignalItem

ROUND1_SYSTEM = """将 new_signals 归并为候选主题。

规则：只用输入 id；included_signal_ids 必须原样复制输入 id 字符串（如 "s0001"），勿改成数字、勿省略 s 前缀；勿编造；勿强行合并不同问题；勿输出评论数。
每主题 included_signal_ids 最多 12 个代表性 id（同义合并后取样即可，勿堆砌）；单批候选主题建议 ≤8 个。
theme_name≤20字；theme_type 必填（可用 new_problem/new_barrier/new_scene/other 等）；definition/implication≤60字；
relation: supports_existing|extends_existing|weakens_existing|unrelated_notable（与已有研究主题的关系类型）；confidence 0~1。
输出JSON：{"candidate_themes":[{"theme_name":"","theme_type":"other","definition":"","included_signal_ids":["s0001"],"relation_to_existing_hypotheses":"extends_existing","implication":"","confidence":0.0}]}"""

ROUND2_SYSTEM = """合并高度相似的候选开放主题。

规则：included_signal_ids 仅填写输入候选 id（如 "c0001"），勿改成数字；措辞不同但义同则合并；本质不同勿合并。
theme_type 必填；relation: supports_existing|extends_existing|weakens_existing|unrelated_notable。
输出JSON：{"themes":[{"theme_name":"","theme_type":"other","definition":"","included_signal_ids":["c0001"],"relation_to_existing_hypotheses":"extends_existing","implication":"","confidence":0.0}]}"""


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
                "id": item.get("candidate_id", ""),
                "theme_name": item.get("theme_name", ""),
                "theme_type": item.get("theme_type", ""),
                "definition": item.get("definition", ""),
                "n": item.get("signal_count", 0),
                "relation_to_existing_hypotheses": item.get(
                    "relation_to_existing_hypotheses", "extends_existing"
                ),
            }
        )
    return "合并候选主题：\n" + _compact_json(slim)
