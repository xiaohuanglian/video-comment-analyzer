# -*- coding: utf-8 -*-
"""Human-readable research report for product / content teams."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

from .evidence_adapter import assign_evidence_item_ids
from .evidence_schemas import EvidenceCard, EvidenceItemType
from .research_agent import _index_evidence_items
from .schemas import SourceRecord
from .user_identity import user_key


def _users_for_ids(records: Sequence[SourceRecord], ids: Sequence[str]) -> int:
    want = set(ids)
    users = set()
    for r in records:
        if r.internal_record_id not in want:
            continue
        uk = user_key(
            {
                "user_id": r.user_id,
                "username": r.username,
                "user_homepage_url": r.user_homepage_url,
            }
        )
        users.add(uk or r.internal_record_id)
    return len(users)


def _format_quotes_from_refs(refs: Sequence[dict], item_index: Dict[str, dict], *, limit: int = 3) -> List[str]:
    quotes: List[str] = []
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        eid = str(ref.get("evidence_item_id") or "").strip()
        item = item_index.get(eid)
        if not item:
            continue
        quote = (item.get("evidence_quote") or "").strip()
        if quote and quote not in quotes:
            quotes.append(quote)
        if len(quotes) >= limit:
            break
    return quotes


def _quote_meta(refs: Sequence[dict], item_index: Dict[str, dict], *, limit: int = 3) -> List[str]:
    """Backfill quote + scope/certainty labels from evidence ids only."""
    lines: List[str] = []
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        eid = str(ref.get("evidence_item_id") or "").strip()
        item = item_index.get(eid)
        if not item:
            continue
        quote = (item.get("evidence_quote") or "").strip()
        if not quote:
            continue
        scope = item.get("speaker_scope") or "unclear"
        cert = item.get("certainty") or "medium"
        lines.append(f"「{quote}」（{scope} / {cert}）")
        if len(lines) >= limit:
            break
    return lines


def build_readable_report(
    *,
    research: dict,
    records: Sequence[SourceRecord],
    card_rows: Sequence[dict],
    run_id: str = "",
    performance: Optional[dict] = None,
) -> str:
    summary = research.get("dataset_summary") or {}
    cards: List[EvidenceCard] = []
    by_id: Dict[str, EvidenceCard] = {}
    for row in card_rows:
        card = EvidenceCard.model_validate(row.get("card") or row)
        card = assign_evidence_item_ids(card)
        by_id[card.record_id] = card
        cards.append(card)
    item_index = _index_evidence_items(card_rows)

    problem_ids = [c.record_id for c in cards if any(i.type == EvidenceItemType.PROBLEM for i in c.evidence_items)]
    behavior_ids = [c.record_id for c in cards if any(i.type == EvidenceItemType.BEHAVIOR for i in c.evidence_items)]
    gap_ids = [c.record_id for c in cards if any(i.type == EvidenceItemType.ACTION_GAP for i in c.evidence_items)]

    behavior_buckets: Dict[str, List[str]] = defaultdict(list)
    gap_by_scope: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for c in cards:
        for item in c.evidence_items:
            if item.type == EvidenceItemType.BEHAVIOR and item.subtype:
                behavior_buckets[item.subtype].append(c.record_id)
            if item.type == EvidenceItemType.ACTION_GAP:
                key = item.subtype or "action_gap"
                behavior_buckets[key].append(c.record_id)
                gap_by_scope[key][item.speaker_scope.value].append(c.record_id)
                gap_by_scope[key][f"cert:{item.certainty.value}"].append(c.record_id)

    conclusions = research.get("research_conclusions") or []
    findings = research.get("unexpected_findings") or []
    themes = research.get("themes") or []
    hyps = research.get("hypothesis_assessment") or []
    opps = research.get("opportunity_hypotheses") or []
    dropped = (research.get("model_draft") or {}).get("dropped_evidence_refs") or []

    lines: List[str] = []
    lines.append(f"# 评论洞察研究报告{' · ' + run_id if run_id else ''}")
    lines.append("")
    lines.append("## 1. 执行摘要")
    lines.append("")
    if conclusions:
        for c in conclusions[:4]:
            lines.append(f"- {c}")
    else:
        lines.append("- （研究 Agent 未给出浓缩结论；请结合下方发现与假设阅读。）")
    lines.append("")
    lines.append("须直接回答：用户最主要问题、最重要行为信号、最值得先验证的机会、当前证据不能证明什么。")
    lines.append("")

    lines.append("## 2. 核心数据")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---:|")
    lines.append(f"| 评论总数 | {summary.get('total_comments', len(records))} |")
    lines.append(f"| 独立用户数 | {summary.get('unique_users', 0)} |")
    lines.append(f"| 可用评论 | {summary.get('usable_comments', 0)} |")
    lines.append(
        f"| 强/中证据评论 | {summary.get('strong_evidence_comments', 0)} / {summary.get('medium_evidence_comments', 0)} |"
    )
    lines.append(f"| 有具体问题 | {summary.get('problem_comments', len(problem_ids))}（用户 {_users_for_ids(records, problem_ids)}） |")
    lines.append(f"| 有真实行为 | {summary.get('behavior_comments', len(behavior_ids))}（用户 {_users_for_ids(records, behavior_ids)}） |")
    lines.append(f"| 有行动差距 | {summary.get('action_gap_comments', len(gap_ids))}（用户 {_users_for_ids(records, gap_ids)}） |")
    lines.append(f"| 主题覆盖率 | {summary.get('theme_coverage_rate', 0)} |")
    lines.append("")

    lines.append("## 3. 最重要的 3—5 个发现")
    lines.append("")
    display_findings = findings[:5] if findings else []
    if display_findings:
        for i, f in enumerate(display_findings, 1):
            rids = f.get("record_ids") or []
            refs = f.get("supporting_evidence_refs") or []
            quote_lines = _quote_meta(refs, item_index)
            # Only fall back to record's first item when no refs were supplied at all
            if not quote_lines and not refs and rids:
                for rid in rids[:2]:
                    card = by_id.get(rid)
                    if not card or not card.evidence_items:
                        continue
                    it = card.evidence_items[0]
                    if it.evidence_quote:
                        quote_lines.append(
                            f"「{it.evidence_quote}」（{it.speaker_scope.value} / {it.certainty.value}）"
                        )
            lines.append(f"### 发现 {i}：{f.get('finding') or '（未命名）'}")
            lines.append("")
            lines.append(f"- **结论**：{f.get('conclusion') or f.get('finding') or '—'}")
            lines.append(f"- **为什么重要**：{f.get('why_it_matters') or '—'}")
            lines.append(f"- **涉及评论数**：{len(rids)}")
            lines.append(f"- **涉及独立用户数**：{_users_for_ids(records, rids)}")
            if quote_lines:
                lines.append(f"- **代表原话**：{'；'.join(quote_lines)}")
            else:
                lines.append("- **代表原话**：—（无有效 evidence_item_id 引用）")
            lines.append(f"- **反例或限制**：{f.get('limitations') or '—'}")
            lines.append(f"- **下一步建议**：{f.get('next_step') or '—'}")
            lines.append("")
    else:
        for i, theme in enumerate(themes[:5], 1):
            rids = theme.get("comment_record_ids") or []
            refs = theme.get("representative_evidence_refs") or []
            quote_lines = _quote_meta(refs, item_index)
            lines.append(f"### 发现 {i}：{theme.get('theme_name') or theme.get('theme_id')}")
            lines.append("")
            lines.append(f"- **结论**：{theme.get('theme_definition') or '—'}")
            lines.append("- **为什么重要**：主题高频出现，需产品/内容跟进验证")
            lines.append(f"- **涉及评论数**：{theme.get('comment_count') or len(rids)}")
            lines.append(f"- **涉及独立用户数**：{theme.get('unique_user_count', _users_for_ids(records, rids))}")
            if quote_lines:
                lines.append(f"- **代表原话**：{'；'.join(quote_lines)}")
            else:
                lines.append("- **代表原话**：—（无有效 evidence_item_id 引用）")
            counter = theme.get("counter_evidence") or []
            lines.append(f"- **反例或限制**：{counter[0] if counter else '—'}")
            lines.append("- **下一步建议**：抽样访谈该主题用户，验证是否可产品化")
            lines.append("")
    if not display_findings and not themes:
        lines.append("- （暂无发现）")
        lines.append("")

    lines.append("## 4. 用户问题结构")
    lines.append("")
    for theme in themes[:8]:
        lines.append(f"### {theme.get('theme_name') or theme.get('theme_id')}")
        lines.append("")
        lines.append(f"- 一级问题：{theme.get('theme_name') or '—'}")
        lines.append(f"- 定义 / 场景：{theme.get('theme_definition') or '—'}")
        sols = theme.get("current_solutions") or []
        impacts = theme.get("impact_or_cost") or []
        if sols:
            lines.append(f"- 现有解决方式：{'；'.join(sols[:3])}")
        if impacts:
            lines.append(f"- 未解决部分：{'；'.join(impacts[:3])}")
        lines.append("")
    if not themes:
        lines.append("- （暂无主题）")
        lines.append("")

    lines.append("## 5. 用户行为与行动差距")
    lines.append("")
    labels = {
        "attempted": "已尝试",
        "continued": "持续训练",
        "stopped": "尝试后停止",
        "started_but_stopped": "尝试后停止",
        "saved_but_not_started": "收藏但未开始",
        "watched_but_not_practiced": "观看但未实践",
        "planned_but_not_started": "有计划但未执行",
        "intended_but_avoided": "想改变但觉得方案太难",
        "paid_but_no_result": "付费但无结果",
        "paid_but_not_used": "付费但未使用",
        "sought_paid_help": "寻求付费帮助",
        "planned": "有计划未确认执行",
        "checked_in": "只打卡或互动",
        "self_reported_ability": "自报能力",
        "completed_once": "完成一次",
        "progress": "有进步",
    }
    if behavior_buckets:
        for key, rids in sorted(behavior_buckets.items(), key=lambda x: -len(set(x[1]))):
            uniq = list(dict.fromkeys(rids))
            scope_bits = gap_by_scope.get(key) or {}
            self_n = len(set(scope_bits.get("self") or []))
            gen_n = len(set(scope_bits.get("general_observation") or []))
            other_n = len(set(scope_bits.get("other_user") or []))
            lines.append(
                f"- **{labels.get(key, key)}**：{len(uniq)} 条 / {_users_for_ids(records, uniq)} 用户"
                f"（self={self_n}, general_observation={gen_n}, other_user={other_n}）"
            )
    else:
        lines.append("- （本批未提取到结构化行为或行动差距）")
    lines.append("")
    lines.append("> 不要把 `general_observation` 当成用户本人经历；并区分 high/medium/low certainty。")
    lines.append("")

    lines.append("## 6. 假设判断")
    lines.append("")
    for hyp in hyps:
        lines.append(f"### {hyp.get('hypothesis_id')}")
        lines.append("")
        lines.append(f"- **结论**：{hyp.get('conclusion')}")
        refs = hyp.get("supporting_evidence_refs") or []
        weak_refs = [r for r in refs if (r.get("strength") or "") == "weak_context"]
        strong_refs = [r for r in refs if (r.get("strength") or "") in {"direct", "behavioral"}]
        strong_quotes = _quote_meta(strong_refs, item_index, limit=3)
        if strong_quotes:
            lines.append(f"- **强支持证据**：{'；'.join(strong_quotes)}")
        elif strong_refs:
            lines.append(
                "- **强支持证据**："
                + "；".join(f"{r.get('evidence_item_id')}({r.get('strength')})" for r in strong_refs[:5])
            )
        else:
            lines.append("- **强支持证据**：—")
        weaken = hyp.get("weakening_record_ids") or []
        w_refs = hyp.get("weakening_evidence_refs") or []
        w_quotes = _quote_meta(w_refs, item_index, limit=2)
        if w_quotes:
            lines.append(f"- **反证**：{'；'.join(w_quotes)}")
        elif weaken:
            lines.append(f"- **反证**：{', '.join(weaken[:5])}")
        else:
            lines.append("- **反证**：—")
        if weak_refs:
            lines.append(f"- **弱相关证据**：{len(weak_refs)} 条（不得撑结论）")
        else:
            lines.append("- **弱相关证据**：—")
        unknowns = hyp.get("unknowns") or []
        lines.append(f"- **当前未知**：{'；'.join(unknowns[:3]) if unknowns else '—'}")
        lines.append(f"- **下一步验证**：{hyp.get('reasoning_summary') or '抽样访谈 + 对照实验'}")
        lines.append("")

    lines.append("## 7. 产品机会（值得验证的机会）")
    lines.append("")
    for opp in opps[:6]:
        lines.append(f"### {opp.get('opportunity_name')}")
        lines.append("")
        lines.append(f"- **对应用户**：{opp.get('target_users') or '—'}")
        lines.append(f"- **具体问题**：{opp.get('concrete_problem') or '—'}")
        alts = opp.get("current_alternatives") or []
        lines.append(f"- **当前解决方式**：{'；'.join(alts[:3]) if alts else '—'}")
        b_quotes = _quote_meta(opp.get("behavior_evidence_refs") or [], item_index, limit=2)
        lines.append(f"- **行为证据**：{'；'.join(b_quotes) if b_quotes else '—'}")
        s_quotes = _quote_meta(opp.get("supporting_evidence_refs") or [], item_index, limit=2)
        if s_quotes:
            lines.append(f"- **支持证据**：{'；'.join(s_quotes)}")
        elif opp.get("supporting_evidence"):
            lines.append(f"- **支持证据**：{'；'.join((opp.get('supporting_evidence') or [])[:3])}")
        else:
            lines.append("- **支持证据**：—")
        c_quotes = _quote_meta(opp.get("counter_evidence_refs") or [], item_index, limit=2)
        if c_quotes:
            lines.append(f"- **反证**：{'；'.join(c_quotes)}")
        elif opp.get("counter_evidence"):
            lines.append(f"- **反证**：{'；'.join((opp.get('counter_evidence') or [])[:2])}")
        else:
            lines.append("- **反证**：—")
        if opp.get("possible_product_form"):
            lines.append(f"- **可能产品形式**：{'；'.join((opp.get('possible_product_form') or [])[:3])}")
        else:
            lines.append("- **可能产品形式**：—")
        lines.append(f"- **当前未知**：{'；'.join((opp.get('current_unknowns') or [])[:3]) or '—'}")
        lines.append(f"- **最小验证实验**：{'；'.join((opp.get('recommended_validation') or [])[:3]) or '—'}")
        lines.append("")
    if not opps:
        lines.append("- （暂无机会假设）")
        lines.append("")

    lines.append("## 8. 推荐访谈对象与问题")
    lines.append("")
    for item in research.get("recommended_interviews") or []:
        lines.append(f"- {item}")
    if not research.get("recommended_interviews"):
        lines.append("- （暂无）")
    lines.append("")

    lines.append("## 9. 推荐验证实验")
    lines.append("")
    for item in research.get("recommended_experiments") or []:
        lines.append(f"- {item}")
    if not research.get("recommended_experiments"):
        lines.append("- （暂无）")
    lines.append("")

    lines.append("## 10. 方法、覆盖率与限制")
    lines.append("")
    lines.append("- 流水线：微批次证据提取 → 代码校验/统计 → 一次数据集研究 Agent → 本报告")
    lines.append("- 代表原话由代码按 `evidence_item_id` 从证据卡原样回填，研究 Agent 不得改写 quote")
    lines.append("- 单条评论不直接做产品结论；假设与机会仅在数据集级产出")
    lines.append(
        f"- 状态分布：usable={summary.get('usable_comments')} / off_topic={summary.get('off_topic_comments')} / "
        f"machine={summary.get('machine_generated_comments')} / spam={summary.get('spam_comments')} / "
        f"garbled={summary.get('garbled_comments')}"
    )
    if dropped:
        lines.append(f"- 结构警告：跳过无效证据引用 {len(dropped)} 条（不补写原话）")
    if performance:
        lines.append(
            f"- 性能：extract={performance.get('extract_elapsed_seconds')}s，"
            f"research={performance.get('research_elapsed_seconds')}s，"
            f"cph={performance.get('comments_per_hour')}，"
            f"concurrency={performance.get('concurrency')}，"
            f"cost={performance.get('actual_cost')}"
        )
    lines.append("")
    lines.append("## 11. 证据明细")
    lines.append("")
    lines.append("完整 `evidence_items` 与原评论见任务目录 `evidence_cards.jsonl`，不在正文堆叠 JSON。")
    lines.append("")
    return "\n".join(lines)
