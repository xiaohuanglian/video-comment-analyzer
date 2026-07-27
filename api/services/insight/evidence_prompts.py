# -*- coding: utf-8 -*-
"""Prompts for evidence_items_v1 (compact, cache-friendly)."""

from __future__ import annotations

import json
from typing import Iterable, List, Optional

from .evidence_schemas import EVIDENCE_PROMPT_VERSION
from .prompts import HYPOTHESES, HYPOTHESIS_SHORT
from .schemas import SourceRecord

_CONTEXT_CHAR_LIMIT = 200

EVIDENCE_SYSTEM_PROMPT = """提取可追溯证据，不做产品结论。只输出单行紧凑 JSON，禁止缩进、空格和换行。

格式：{"r":[{"i":1,"s":"u","x":"h","e":[["p","","s","h","原文"]]}]}。
i 是输入短编号，禁止返回 record_id；s 是状态，x 是表达，禁止合并或调换。
s 只能是：u可用/o跑题/m机器生成/s垃圾/g乱码/c不清楚；禁止把 x 的码写进 s（尤其禁止 s=k）。
x: q提问/h求助/c抱怨/r结果反馈/k打卡/p赞赏/o其他；打卡必须写 x=k 且 s=u，例如 sx=uk。
e 每项固定 [类型,subtype,范围,确定性,原文]：
类型 p问题/d障碍/b行为/r结果/c背景/s解决方式/a行动差距/e互动/o观点/q量化；
范围 s本人/g泛指/o他人/u不清楚；确定性 h高/m中/l低。
subtype 仅行为可用 a尝试/c完成一次/n持续/p计划/x停止/f付费求助/y自报能力；
行动差距可用 s收藏未行动/w观看未行动/f付费无结果；其他类型无必要就填空串。

规则：
1) 原文必须是 c、p 或 r 的连续子串；不可改写，无合法原文就删。
2) 默认每条最多2项；仅“问题+行为+结果”、付费且无结果、多个独立事实或量化兼有核心问题时可3—4项。
3) 超限优先：问题/障碍、行为、行动差距、结果、付费、量化、解决方式、观点、赞赏。
4) 同一句不得换类型重复；低信息可 e=[]。
5) 只要本人明确“做了/练了/试了/测了/跟练完/坚持/看医生/付费”，必须优先保留 b 行为；不能标成 d 障碍。
6) “做完后改善/疼痛”通常保留 b 行为 + r 结果；训练周期同时属于行为，不要只标量化。
7) 收藏不练→互动+行动差距；办卡/付费治疗→b,f，无结果再加 a,f。
8) 玩梗跑题→o；广告→s；乱码→g；AI摘要→m。
""".strip()

RESEARCH_SYSTEM_PROMPT = """你是数据集级评论研究分析师。输入是全量 evidence_items 的代码聚合组与代码统计。

职责：主题归并、假设评估、反例和最多 3 个意外发现。

规则：
- 只引用输入中的短 ref_id（如 R1），禁止输出完整 record_id。
- 不要自行估算评论数/用户数。
- 禁止输出代表原话文本、禁止改写/拼接/润色 evidence_quote。
- 普通引用只输出 "R1"；假设引用输出 {{"r":"R1","s":"d|b|w"}}，分别代表 direct、behavioral、weak_context。
- weak_context 不得撑结论。
- 主题只能从 cluster_ids 选择，禁止把代表引用数量当成主题总量。
- H1：只有部分已行动样本且缺未行动对照时，结论必须 mixed 或 insufficient。
- H2：方向判断/动作标准问题最多构成中等支持，不等于必须实时视觉识别。
- H3：记不住动作/不知道下一步/需要降阶只能构成弱支持或证据不足。
- 禁止声称付费意愿、市场空白、需求已验证或「大部分用户」，除非代码统计直接支持。
- 只输出用户消息定义的精简字段，单行 JSON，禁止额外解释。

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

SEMANTIC_REVIEW_SYSTEM_PROMPT = """你是精确优先的证据审查员，不是报告写作者。
逐项判断候选结论是否被附带原文直接支持。只可使用输入原文与程序统计，禁止补充常识、生成新结论或改写证据。
判断：
- supported：结论每个关键语义都被原文直接支持，且未夸大范围、因果、疗效、付费或本人经历。
- contradicted：原文与结论含义相反，或把计划当执行、推销当购买、省钱当付费失败、他人当本人、疼痛当有效。
- insufficient：原文相关但不足以支持结论，或只有少数样本却声称普遍、相关却声称因果。
程序 hard_verdict 为 contradicted/insufficient 时不得改成 supported。
只输出单行紧凑 JSON：{"r":[{"i":"claim_id","v":"supported|contradicted|insufficient","x":"短理由"}]}。
必须覆盖输入中的每个 claim_id；禁止输出其他字段。
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
    for index, record in enumerate(records, 1):
        items.append(
            {
                "i": index,
                "c": record.comment_text or "",
                "p": _clip(record.parent_comment),
                "r": _clip(record.creator_reply),
            }
        )
    ctx = (project_context_compact or DEFAULT_PROJECT_CONTEXT_COMPACT).strip()
    return (
        f"prompt_version={EVIDENCE_PROMPT_VERSION}\n"
        f"project_context:{ctx}\n"
        + json.dumps({"d": items}, ensure_ascii=False, separators=(",", ":"))
    )


def build_research_user_message(
    *,
    evidence_clusters: List[dict],
    known_record_ids: List[str],
    dataset_summary: Optional[dict] = None,
    project_context: str = "",
) -> str:
    payload = {
        "hypotheses": {hid: HYPOTHESES[hid] for hid in ("H1", "H2", "H3")},
        "project_context": (project_context or DEFAULT_PROJECT_CONTEXT_COMPACT)[:2000],
        "code_dataset_summary": dataset_summary or {},
        "known_record_id_count": len(known_record_ids),
        "evidence_clusters": evidence_clusters,
        "output_schema": {
            "themes": [
                {
                    "theme_id": "T1",
                    "cluster_ids": [],
                    "theme_name": "",
                    "theme_definition": "",
                    "representative_evidence_refs": ["R1"],
                    "current_solutions": [],
                    "impact_or_cost": [],
                    "counter_evidence": [],
                }
            ],
            "hypothesis_assessment": [
                {
                    "hypothesis_id": "H1",
                    "conclusion": "supported|weakened|mixed|insufficient",
                    "supporting_evidence_refs": [{"r": "R1", "s": "d|b|w"}],
                    "weakening_evidence_refs": [{"r": "R2", "s": "d|b|w"}],
                    "reasoning_summary": "",
                    "unknowns": [],
                }
            ],
            "unexpected_findings": [
                {
                    "finding": "",
                    "conclusion": "",
                    "supporting_evidence_refs": ["R1"],
                    "why_it_matters": "",
                    "limitations": "",
                    "next_step": "",
                }
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


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


def build_semantic_review_user_message(claims: List[dict], *, total_comments: int) -> str:
    compact = []
    for claim in claims[:20]:
        compact.append(
            {
                "i": claim.get("claim_id"),
                "t": claim.get("text"),
                "q": (claim.get("evidence_quotes") or [])[:3],
                "n": claim.get("record_count", 0),
                "h": claim.get("hard_verdict", "needs_review"),
                "hr": (claim.get("hard_reasons") or [])[:2],
            }
        )
    return json.dumps(
        {"total_comments": total_comments, "claims": compact},
        ensure_ascii=False,
        separators=(",", ":"),
    )
