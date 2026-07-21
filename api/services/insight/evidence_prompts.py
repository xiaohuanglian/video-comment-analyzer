# -*- coding: utf-8 -*-
"""Prompts for evidence_items_v1 (compact, cache-friendly)."""

from __future__ import annotations

import json
from typing import Iterable, List, Optional

from .evidence_schemas import EVIDENCE_PROMPT_VERSION
from .prompts import HYPOTHESES, HYPOTHESIS_SHORT
from .schemas import SourceRecord

_CONTEXT_CHAR_LIMIT = 200

EVIDENCE_SYSTEM_PROMPT = """评论证据提取器。只输出可追溯证据，不做产品结论，不判断假设。

输出唯一 JSON：{"cards":[...]}，每条输入一项，record_id 必须一致。

字段：
- record_status: usable|off_topic|machine_generated|spam|garbled|unclear
- primary_expression: question|help_request|complaint|result_feedback|check_in|praise|other
- evidence_items: [{type,text,evidence_quote,speaker_scope,certainty,subtype?}]

type: problem|behavior|result|context|solution|barrier|action_gap|engagement|opinion|quantitative
speaker_scope: self|other_user|general_observation|unclear
certainty: high|medium|low

硬规则：
1) 每项 evidence_quote 必须是评论/父评/博主回复的连续原文子串；宁可短 quote，不可改写。无合法 quote 则删该项。
2) usable 且评论含明确事实时，evidence_items 不得为空。至少抽 1 条。
3) 行动差距（核心不是讽刺）：
   - 「收藏退出/收藏不练/只看看不练/看看就算了」→ engagement + action_gap（self, high）
   - 「两年前收藏」→ engagement.saved + action_gap（self, low/medium）
   - 「关注收藏就学会」→ action_gap（general_observation, medium）
4) 「刚刚试了试/做到X分钟/做完N个」→ behavior.attempted 或 completed_once，并尽量加 quantitative。
5) 「会做几个/可以倒立」→ behavior.self_reported_ability，不是 planned。
6) 「办卡/健身房」→ behavior.sought_paid_help；无效果再加 action_gap.paid_but_no_result。
7) 次数/秒数/组数/周期/斤数/进步 → quantitative（可多条）；训练计划清单也要 quant，但无第一人称执行则不要 behavior。
8) 啤酒鸭段子、纹身跑题、门修好玩梗 → off_topic，不是 spam。仅广告导流→spam；乱码→garbled；AI助理摘要→machine_generated。
9) 健康信息写「用户提及…」。不要输出 evidence_level、contact_value、reasoning、possible_new_signal。
""".strip()

RESEARCH_SYSTEM_PROMPT = """你是数据集级评论研究分析师。输入是已提取的 evidence_items 摘要与代码统计。

职责：主题归并、假设评估、反例、机会假设、访谈与实验建议。

规则：
- 只引用输入中的完整 record_id 与 evidence_item_id。
- 不要自行估算评论数/用户数。
- 禁止输出代表原话文本、禁止改写/拼接/润色 evidence_quote。
- 需要引用证据时，只输出 {{"record_id","evidence_item_id"}}。
- 每条支持/削弱证据给 strength：direct|behavioral|weak_context；weak_context 不得撑结论。
- 机会必须是「值得验证」，禁止写成已证明需求或一定会付费。
- 输出唯一 JSON，字段见用户消息。

假设简版：
- H1：{h1}
- H2：{h2}
- H3：{h3}
""".format(
    h1=HYPOTHESIS_SHORT["H1"],
    h2=HYPOTHESIS_SHORT["H2"],
    h3=HYPOTHESIS_SHORT["H3"],
)

REVIEW_SYSTEM_PROMPT = """结构审查员（仅异常抽检时使用）。检查 record_id、原话可追溯、反例、个案夸大、弱证据撑结论。
输出 JSON：{"structural_review_passed":bool,"issues":[{"type":"...","description":"...","related_record_ids":[]}],"corrected_sections":{}}
""".strip()

# Compact project context placeholder — filled by caller when available
DEFAULT_PROJECT_CONTEXT_COMPACT = (
    "研究目标：健身内容评论中的训练障碍、行动差距与产品机会。"
    "目标用户：跟练/自重训练新手到进阶。"
    "禁止：把玩梗当核心标签；把难度直接当成需要系统代规划的证明；医疗确诊措辞。"
)


def _clip(text: str, limit: int = _CONTEXT_CHAR_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_evidence_batch_user_message(
    records: Iterable[SourceRecord],
    *,
    project_context_compact: str = "",
) -> str:
    items: List[dict] = []
    for record in records:
        items.append(
            {
                "record_id": record.internal_record_id,
                "comment_text": record.comment_text or "",
                "parent_comment": _clip(record.parent_comment),
                "creator_reply": _clip(record.creator_reply),
                "video_title": _clip(record.video_title or "", 80),
            }
        )
    ctx = (project_context_compact or DEFAULT_PROJECT_CONTEXT_COMPACT).strip()
    return (
        f"prompt_version={EVIDENCE_PROMPT_VERSION}\n"
        f"project_context:{ctx}\n"
        "为下列评论输出证据卡。\n"
        + json.dumps({"comments": items}, ensure_ascii=False)
    )


def build_research_user_message(
    *,
    card_summaries: List[dict],
    known_record_ids: List[str],
    dataset_summary: Optional[dict] = None,
    project_context: str = "",
) -> str:
    payload = {
        "hypotheses": {hid: HYPOTHESES[hid] for hid in ("H1", "H2", "H3")},
        "project_context": (project_context or DEFAULT_PROJECT_CONTEXT_COMPACT)[:2000],
        "code_dataset_summary": dataset_summary or {},
        "known_record_id_count": len(known_record_ids),
        "evidence_cards": card_summaries,
        "output_schema": {
            "themes": [
                {
                    "theme_id": "T1",
                    "theme_name": "",
                    "theme_definition": "",
                    "comment_record_ids": [],
                    "representative_evidence_refs": [{"record_id": "", "evidence_item_id": ""}],
                    "current_solutions": [],
                    "impact_or_cost": [],
                    "counter_evidence": [],
                    "confidence": 0.0,
                }
            ],
            "hypothesis_assessment": [
                {
                    "hypothesis_id": "H1",
                    "conclusion": "supported|weakened|mixed|insufficient",
                    "supporting_record_ids": [],
                    "weakening_record_ids": [],
                    "supporting_evidence_refs": [
                        {
                            "record_id": "",
                            "evidence_item_id": "",
                            "strength": "direct|behavioral|weak_context",
                            "note": "",
                        }
                    ],
                    "weakening_evidence_refs": [
                        {
                            "record_id": "",
                            "evidence_item_id": "",
                            "strength": "direct|behavioral|weak_context",
                            "note": "",
                        }
                    ],
                    "reasoning_summary": "",
                    "unknowns": [],
                }
            ],
            "unexpected_findings": [
                {
                    "finding": "",
                    "conclusion": "",
                    "record_ids": [],
                    "supporting_evidence_refs": [{"record_id": "", "evidence_item_id": ""}],
                    "why_it_matters": "",
                    "limitations": "",
                    "next_step": "",
                }
            ],
            "opportunity_hypotheses": [
                {
                    "opportunity_name": "",
                    "target_users": "",
                    "concrete_problem": "",
                    "current_alternatives": [],
                    "supporting_evidence": [],
                    "supporting_evidence_refs": [{"record_id": "", "evidence_item_id": ""}],
                    "counter_evidence": [],
                    "counter_evidence_refs": [{"record_id": "", "evidence_item_id": ""}],
                    "behavior_evidence_refs": [{"record_id": "", "evidence_item_id": ""}],
                    "possible_product_form": [],
                    "possible_content_form": [],
                    "current_unknowns": [],
                    "recommended_validation": [],
                    "supporting_record_ids": [],
                }
            ],
            "research_conclusions": [],
            "recommended_interviews": [],
            "recommended_experiments": [],
        },
    }
    return "基于证据项完成数据集研究。\n" + json.dumps(payload, ensure_ascii=False)


def build_review_user_message(
    *,
    research: dict,
    dataset_summary: dict,
    source_quote_index: dict,
) -> str:
    payload = {
        "research_analysis": research,
        "code_computed_summary": dataset_summary,
        "sample_quotes": {k: v[:120] for k, v in list(source_quote_index.items())[:40]},
    }
    return "审查研究报告结构。\n" + json.dumps(payload, ensure_ascii=False)
