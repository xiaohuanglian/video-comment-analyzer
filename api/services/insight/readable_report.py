# -*- coding: utf-8 -*-
"""Human-readable research report for product / content teams."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

from .evidence_adapter import (
    has_explicit_paid_action,
    has_paid_failure,
)
from .evidence_schemas import EvidenceItemType
from .labels import label_intent, label_signal, label_single_video
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


def _quote_meta(refs: Sequence[dict], item_index: Dict[str, dict], *, limit: int = 3) -> List[str]:
    """Backfill quote + scope/certainty labels from evidence ids only."""
    scope_labels = {
        "self": "本人",
        "other_user": "他人",
        "general_observation": "泛指",
        "unclear": "不明确",
    }
    certainty_labels = {"high": "高确定性", "medium": "中确定性", "low": "低确定性"}
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
        lines.append(
            f"「{quote}」（{scope_labels.get(scope, '不明确')} / "
            f"{certainty_labels.get(cert, '中确定性')}）"
        )
        if len(lines) >= limit:
            break
    return lines


REPORT_BEHAVIOR_GROUPS = {
    "已开始尝试": {"attempted", "completed_once", "completed", "self_reported_ability"},
    "正在持续进行": {
        "continued",
        "ongoing_period",
        "sustained_practice",
        "persistence",
        "completed_repeated",
        "completed_repeatedly",
    },
    "已经获得结果": {"progress", "result", "improved"},
    "尝试后停止": {"stopped", "tried_but_gave_up", "started_but_stopped"},
    "有计划但未执行": {"planned", "planned_but_not_started"},
    "付费但无结果": {"paid_but_no_result", "paid_but_not_used"},
    "收藏/观看但未行动": {"saved_but_not_started", "watched_but_not_practiced"},
}


def _finding_has_required_evidence(finding: dict, item_index: Dict[str, dict]) -> bool:
    """Do not surface paid-help claims without paid behavior/gap evidence."""
    claim = " ".join(
        str(finding.get(key) or "")
        for key in ("finding", "conclusion", "why_it_matters")
    )
    if "付费" not in claim:
        return True
    for ref in finding.get("supporting_evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        item = item_index.get(str(ref.get("evidence_item_id") or "")) or {}
        if str(item.get("subtype") or "") in {
            "sought_paid_help",
            "paid_but_no_result",
            "paid_but_not_used",
        }:
            return True
        evidence = f"{item.get('text') or ''} {item.get('evidence_quote') or ''}"
        if has_explicit_paid_action(evidence) or has_paid_failure(evidence):
            return True
    return False


def _theme_record_ids(theme: dict) -> List[str]:
    ids = theme.get("comment_record_ids") or theme.get("record_ids") or []
    return [rid for rid in ids if isinstance(rid, str) and rid]


def _theme_count(theme: dict) -> int:
    return int(theme.get("comment_count") or len(_theme_record_ids(theme)))


# Neutral defaults; project profiles normally override these.
DEFAULT_NOISE_MARKERS = (
    "哈哈", "支持", "沙发", "第一", "点赞", "路过", "签到",
)
DEFAULT_DECISION_KEYWORDS = ("问题", "困难", "需求", "替代", "付费", "为什么不", "怎么办")
DEFAULT_RISK_TOKENS = ("风险", "坑", "骗", "退款", "后悔")
DEFAULT_DIFFICULTY_TOKENS = ("不会", "难", "搞不定", "做不到", "麻烦", "卡住")
DEFAULT_QUESTION_TOKENS = ("怎么", "能不能", "可以", "吗", "如何", "为什么")


def _noise_markers(profile) -> tuple:
    markers = tuple(getattr(profile, "noise_markers", None) or ())
    return markers or DEFAULT_NOISE_MARKERS


def _is_reportable_theme(theme: dict, noise_markers: Sequence[str] = DEFAULT_NOISE_MARKERS) -> bool:
    """Keep ritual/noise clusters out of executive recommendations."""
    name = str(theme.get("theme_name") or "")
    definition = str(theme.get("theme_definition") or theme.get("definition") or "")
    text = f"{name} {definition}".lower()
    if not name or len(name) < 3:
        return False
    if any(marker in text for marker in noise_markers):
        return False
    return _theme_count(theme) >= 8


def _reportable_themes(
    themes: Sequence[dict], noise_markers: Sequence[str] = DEFAULT_NOISE_MARKERS
) -> List[dict]:
    reportable = [theme for theme in themes if _is_reportable_theme(theme, noise_markers)]
    # Most-supported themes first, so executive sections are not order-dependent.
    reportable.sort(key=_theme_count, reverse=True)
    return reportable


def _theme_summary(theme: dict, profile=None) -> str:
    """Turn a cluster label into a bounded, decision-useful observation."""
    name = str(theme.get("theme_name") or "").strip()
    risk = tuple(getattr(profile, "theme_risk_tokens", None) or ()) or DEFAULT_RISK_TOKENS
    difficulty = tuple(getattr(profile, "theme_difficulty_tokens", None) or ()) or DEFAULT_DIFFICULTY_TOKENS
    question = tuple(getattr(profile, "theme_question_tokens", None) or ()) or DEFAULT_QUESTION_TOKENS
    if any(token in name for token in risk):
        return f"用户反复报告「{name}」相关不适或风险信号；应先确认触发情境与安全边界，而非直接当作需求。"
    if any(token in name for token in difficulty):
        return f"用户反复表示「{name}」；优先验证降低完成门槛的方式（说明、降阶、节奏等）。"
    if any(token in name for token in question):
        return f"用户围绕「{name}」寻求适用范围或做法；先补齐明确说明，再观察重复提问是否下降。"
    return f"评论中反复出现「{name}」，但当前只能确认表达集中，不能据此推导原因、需求强度或付费意愿。"


def _theme_implication(theme: dict, profile=None) -> str:
    implication = str(theme.get("implication") or "").strip()
    if implication and not implication.startswith("围绕"):
        return implication
    return _theme_summary(theme, profile)


def _is_reportable_finding(
    finding: dict, noise_markers: Sequence[str] = DEFAULT_NOISE_MARKERS
) -> bool:
    text = " ".join(
        str(finding.get(key) or "") for key in ("finding", "conclusion", "why_it_matters")
    ).lower()
    return not any(marker in text for marker in noise_markers)


# Cap on findings expanded inline; the rest stay available in research_analysis.json.
MAX_REPORT_FINDINGS = 5


def _finding_score(finding: dict, records: Sequence[SourceRecord]) -> tuple:
    """Rank findings by independent users, then comment volume, then evidence refs."""
    ids = [rid for rid in (finding.get("record_ids") or []) if isinstance(rid, str)]
    refs = finding.get("supporting_evidence_refs") or []
    return (
        _users_for_ids(records, ids),
        len(set(ids)),
        len([ref for ref in refs if isinstance(ref, dict)]),
    )


def _priority_insight(themes: Sequence[dict], profile=None) -> dict:
    """Insight-oriented next step — not interview recruitment copy."""
    candidates = _reportable_themes(themes, _noise_markers(profile))
    if candidates:
        top = max(candidates, key=_theme_count)
        name = str(top.get("theme_name") or "核心问题主题")
        count = _theme_count(top)
        implication = str(
            top.get("implication")
            or top.get("theme_definition")
            or top.get("definition")
            or ""
        ).strip()
        return {
            "action": f"优先围绕「{name}」做内容或产品单点验证（约 {count} 条相关评论）。",
            "why": implication if implication and not implication.startswith("围绕") else _theme_summary(top, profile),
            "confirm": "该问题是否反复出现、用户现有替代方案是什么、何种辅助真正会被尝试",
            "advance": "若同类问题在新样本中复现，且用户愿意试用最小辅助流程，则推进对应单点原型或内容改版。",
            "refute": "若问题靠重看视频或一次答疑即可解决，或无法复现，则暂缓产品化。",
        }
    return {
        "action": "先补齐本视频的开放主题归并，再决定内容/产品单点方向。",
        "why": "当前没有足够集中的主题证据，继续泛化推进容易偏离真实评论结构。",
        "confirm": "是否存在反复出现的具体问题主题，以及其规模与行为证据",
        "advance": "若归并后出现稳定主题且具备行为证据，再进入单点验证。",
        "refute": "若评论以低信息互动为主、无法形成主题，则暂缓产品化，优先优化内容表达。",
    }


def _behavior_groups(item_index: Dict[str, dict]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for item in item_index.values():
        subtype = str(item.get("subtype") or "")
        rid = item.get("record_id")
        if not rid:
            continue
        for label, members in REPORT_BEHAVIOR_GROUPS.items():
            if subtype in members and rid not in grouped[label]:
                grouped[label].append(rid)
                break
    return grouped


def _minimal_opportunities(themes: Sequence[dict], profile=None) -> List[dict]:
    templates = list(getattr(profile, "opportunity_templates", None) or [])
    opportunities: List[dict] = []
    seen_names: set[str] = set()
    for theme in _reportable_themes(themes, _noise_markers(profile)):
        name = str(theme.get("theme_name") or "")
        definition = str(theme.get("theme_definition") or theme.get("definition") or "")
        implication = str(theme.get("implication") or "")
        candidate: Optional[dict] = None
        for tpl in templates:
            keywords = tpl.get("match") or []
            if any(keyword in name for keyword in keywords):
                candidate = {
                    "name": str(tpl.get("name") or f"围绕「{name}」的单点验证"),
                    "problem": str(tpl.get("problem") or _theme_summary(theme, profile)),
                    "experiment": str(tpl.get("experiment") or ""),
                }
                break
        if candidate is None and name:
            candidate = {
                "name": f"围绕「{name}」的单点验证",
                "problem": _theme_summary(theme, profile),
                "experiment": (
                    implication
                    if implication and not implication.startswith("围绕")
                    else "在一支内容中补充针对性说明或降阶提示，对比同类提问与中途放弃表达是否下降。"
                ),
            }
        if candidate and candidate["name"] not in seen_names:
            seen_names.add(candidate["name"])
            opportunities.append(candidate)
        if len(opportunities) >= 3:
            break
    return opportunities


def _qual_stats_section(qual_stats: Optional[dict]) -> List[str]:
    if not qual_stats:
        return []
    lines: List[str] = ["## 评论结构（本视频）", ""]
    intent_labels = qual_stats.get("intent_labels") or None
    signal_labels = qual_stats.get("signal_labels") or None
    intent_counts = qual_stats.get("primary_intent_counts") or {}
    intent_pct = qual_stats.get("primary_intent_percentages") or {}
    if intent_counts:
        lines.extend(
            [
                "### 主要沟通目的",
                "",
                "| 目的 | 条数 | 占比 |",
                "| --- | ---: | ---: |",
            ]
        )
        for key in sorted(intent_counts.keys(), key=lambda k: (-intent_counts.get(k, 0), k)):
            lines.append(
                f"| {label_intent(key, intent_labels)} | {intent_counts.get(key, 0)} | {intent_pct.get(key, 0)}% |"
            )
        lines.append("")

    signal_coverage = qual_stats.get("signal_coverage") or {}
    if signal_coverage:
        lines.extend(
            [
                "### 信息信号覆盖率",
                "",
                "> 同一评论可含多个信号，覆盖率之和可能超过 100%。",
                "",
                "| 信号 | 条数 | 覆盖率 |",
                "| --- | ---: | ---: |",
            ]
        )
        for key, info in sorted(
            signal_coverage.items(),
            key=lambda item: (-int((item[1] or {}).get("count") or 0), item[0]),
        ):
            if int((info or {}).get("count") or 0) <= 0:
                continue
            lines.append(
                f"| {label_signal(key, signal_labels)} | {info.get('count', 0)} | {info.get('coverage_pct', 0)}% |"
            )
        lines.append("")

    video_stats = qual_stats.get("single_video_stats") or {}
    if video_stats:
        lines.extend(
            [
                "### 一次回复能解决吗",
                "",
                "| 情况 | 条数 | 覆盖率 |",
                "| --- | ---: | ---: |",
            ]
        )
        for key, info in sorted(
            video_stats.items(),
            key=lambda item: (-int((item[1] or {}).get("count") or 0), item[0]),
        ):
            if int((info or {}).get("count") or 0) <= 0:
                continue
            lines.append(
                f"| {label_single_video(key)} | {info.get('count', 0)} | {info.get('coverage_pct', 0)}% |"
            )
        lines.append("")
    return lines if len(lines) > 2 else []


def build_readable_report(
    *,
    research: dict,
    records: Sequence[SourceRecord],
    card_rows: Sequence[dict],
    run_id: str = "",
    performance: Optional[dict] = None,
    open_themes: Optional[Sequence[dict]] = None,
    qual_stats: Optional[dict] = None,
    profile: Any = None,
) -> str:
    if profile is None:
        from .project_profiles import DEFAULT_PROFILE_ID, get_profile

        profile = get_profile(DEFAULT_PROFILE_ID)
    noise_markers = _noise_markers(profile)
    summary = research.get("dataset_summary") or {}
    item_index = _index_evidence_items(card_rows)
    # Count analyzed cards from raw dicts (no EvidenceCard materialisation).
    analyzed_count = 0
    for row in card_rows:
        card_raw = row.get("card") or row
        if isinstance(card_raw, dict) and card_raw.get("record_id"):
            analyzed_count += 1
    research_themes = list(research.get("themes") or [])
    open_theme_list = [dict(theme) for theme in (open_themes or []) if isinstance(theme, dict)]
    # The LLM research outline may contain broad labels; decision pages must
    # instead be anchored in the evidence-bearing, action-filtered clusters.
    themes = _reportable_themes(open_theme_list, noise_markers) or _reportable_themes(research_themes, noise_markers)
    coverage_themes = open_theme_list or research_themes
    coverage_label = "开放主题覆盖率" if open_theme_list else "主要主题覆盖率"

    eligible_findings = [
        finding
        for finding in (research.get("unexpected_findings") or [])
        if _finding_has_required_evidence(finding, item_index)
        and _is_reportable_finding(finding, noise_markers)
    ]
    eligible_findings.sort(key=lambda f: _finding_score(f, records), reverse=True)
    findings = eligible_findings[:MAX_REPORT_FINDINGS]
    hidden_findings = max(0, len(eligible_findings) - len(findings))
    model_draft = research.get("model_draft") or {}
    dropped = model_draft.get("dropped_evidence_refs") or []
    aggregate_research_used = any(
        theme.get("cluster_ids") for theme in (model_draft.get("themes") or []) if isinstance(theme, dict)
    )

    problem_type = EvidenceItemType.PROBLEM.value
    behavior_type = EvidenceItemType.BEHAVIOR.value
    gap_type = EvidenceItemType.ACTION_GAP.value
    problem_ids = {
        v["record_id"] for v in item_index.values() if v.get("type") == problem_type and v.get("record_id")
    }
    behavior_ids = {
        v["record_id"] for v in item_index.values() if v.get("type") == behavior_type and v.get("record_id")
    }
    gap_ids = {
        v["record_id"] for v in item_index.values() if v.get("type") == gap_type and v.get("record_id")
    }
    themed_ids = {rid for theme in coverage_themes for rid in _theme_record_ids(theme)}
    usable = int(summary.get("usable_comments", 0) or 0)
    if usable <= 0:
        usable = max(len(records), analyzed_count)
    covered = len(themed_ids)
    coverage = covered / usable if usable else 0.0
    low_information = int(summary.get("low_information_comments", 0) or 0)
    unclustered_valid = max(0, usable - covered - low_information)
    decision_keywords = tuple(
        getattr(profile, "decision_keywords", None) or ()
    ) or DEFAULT_DECISION_KEYWORDS
    top_theme = (
        max(
            themes,
            key=lambda theme: (
                int(any(keyword in str(theme.get("theme_name") or "") for keyword in decision_keywords)),
                _theme_count(theme),
            ),
        )
        if themes
        else {}
    )
    top_theme_name = str(top_theme.get("theme_name") or "尚未形成稳定主题")
    top_theme_count = _theme_count(top_theme) if top_theme else 0
    top_theme_users = int(
        top_theme.get("unique_user_count")
        or (_users_for_ids(records, _theme_record_ids(top_theme)) if top_theme else 0)
    )
    action = _priority_insight(themes, profile)

    summary_text = (
        f"本次分析 {summary.get('total_comments', len(records))} 条评论，涉及 "
        f"{summary.get('unique_users', 0)} 名独立用户。当前最明确的问题是“{top_theme_name}”："
        f"相关主题中有 {top_theme_count} 条评论、{top_theme_users} 名用户提供证据。"
        "现阶段最值得优先验证的不是大而全产品，而是这类用户是否真的无法靠重看视频或一次答疑解决问题。"
        "本次结果也不能证明付费意愿、市场规模、长期留存或医疗效果。"
        f"因此当前优先行动：{action['action']}"
    )

    lines = [
        f"# 评论洞察决策报告{' · ' + run_id if run_id else ''}",
        "",
        "## 1. 一页决策摘要",
        "",
        "### 执行摘要",
        "",
        summary_text,
        "",
        "### 核心数字",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| 评论总数 | {summary.get('total_comments', len(records))} |",
        f"| 已分析评论 | {analyzed_count} |",
        f"| 独立用户数 | {summary.get('unique_users', 0)} |",
        f"| 有具体问题的用户数 | {_users_for_ids(records, list(problem_ids))} |",
        f"| 有真实行为的用户数 | {_users_for_ids(records, list(behavior_ids))} |",
        f"| 有行动差距的用户数 | {_users_for_ids(records, list(gap_ids))} |",
        f"| {coverage_label} | {covered} / {usable}（{coverage:.1%}） |",
        "",
        "## 当前优先行动",
        "",
        f"**{action['action']}**",
        "",
        f"- **为什么优先这个**：{action['why']}",
        f"- **要确认什么**：{action['confirm']}。",
        f"- **什么结果会推进**：{action['advance']}",
        f"- **什么结果会否定**：{action['refute']}",
        "",
        "### 结论边界",
        "",
        f"- 本报告基于 {analyzed_count} / {len(records)} 条评论的证据卡；未覆盖部分不代表没有信号。",
        "- 本报告识别的是评论中的问题与行为信号，不等于需求已经验证。",
        "- 规则推断的个性化/实时反馈标签仅用于候选筛选，不作为事实统计。",
        "- 当前数据不能证明付费意愿、市场规模、长期留存或医疗效果。",
        "",
        "## 2. 最重要发现",
        "",
    ]

    if findings:
        for index, finding in enumerate(findings, 1):
            rids = finding.get("record_ids") or []
            refs = finding.get("supporting_evidence_refs") or []
            quotes = _quote_meta(refs, item_index, limit=2)
            next_step = finding.get("next_step") or "用小样本对照或内容改版验证该发现是否复现。"
            if "访谈" in str(next_step):
                next_step = "用小样本对照或内容改版验证该发现是否复现。"
            lines.extend(
                [
                    f"### 发现 {index}：{finding.get('finding') or '未命名发现'}",
                    "",
                    f"- **【事实】用户在说什么**：{';'.join(quotes) if quotes else '—（无有效 evidence_item_id 引用）'}",
                    f"- **【事实】证据规模**：{len(rids)} 条评论 / {_users_for_ids(records, rids)} 名用户。",
                    f"- **【推断】这意味着什么**：{str(finding.get('conclusion') or finding.get('why_it_matters') or '').strip()}",
                    f"- **【限制】当前不能证明什么**：{finding.get('limitations') or '不能证明该现象具有普遍性，也不能证明付费意愿。'}",
                    f"- **【建议】下一步**：{next_step}",
                    "",
                ]
            )
        if hidden_findings:
            lines.append(
                f"- 另有 {hidden_findings} 条达到证据门槛的发现（按独立用户数与证据量排序后未展开），"
                "详见任务目录 `research_analysis.json`。"
            )
            lines.append("")
    elif themes:
        theme = themes[0]
        rids = _theme_record_ids(theme)
        quotes = _quote_meta(theme.get("representative_evidence_refs") or [], item_index, limit=2)
        if not quotes:
            for quote in (theme.get("representative_quotes") or [])[:2]:
                if quote:
                    quotes.append(f"「{quote}」")
        lines.extend(
            [
                f"### 发现 1：{theme.get('theme_name') or '主要问题'}",
                "",
                f"- **【事实】用户在说什么**：{';'.join(quotes) if quotes else '—（暂无代表原话）'}",
                f"- **【事实】证据规模**：{len(rids)} 条评论 / {_users_for_ids(records, rids)} 名用户。",
                    f"- **【推断】这意味着什么**：{_theme_summary(theme, profile)}",
                "- **【限制】当前不能证明什么**：不能证明所有用户都存在该问题，也不能证明其愿意付费。",
                f"- **【建议】下一步**：{str(theme.get('implication') or '围绕该主题做内容/产品单点验证。').strip()}",
                "",
            ]
        )
    else:
        lines.extend(["- 当前没有达到报告门槛的强发现。", ""])

    lines.extend(_qual_stats_section(qual_stats))

    lines.extend(["## 3. 用户问题结构", ""])
    if themes:
        for theme in themes[:5]:
            rids = _theme_record_ids(theme)
            quotes = _quote_meta(theme.get("representative_evidence_refs") or [], item_index, limit=2)
            if not quotes:
                for quote in (theme.get("representative_quotes") or [])[:2]:
                    if quote:
                        quotes.append(f"「{quote}」")
            lines.extend(
                [
                    f"### {theme.get('theme_name') or theme.get('theme_id')}",
                    "",
                    f"- **事实规模**：{len(rids)} 条评论 / {_users_for_ids(records, rids)} 名用户。",
                    f"- **问题场景**：{theme.get('theme_definition') or theme.get('definition') or '—'}",
                    f"- **代表原话**：{';'.join(quotes) if quotes else '—'}",
                    f"- **产品含义**：{_theme_implication(theme, profile)}",
                    "",
                ]
            )
    elif open_theme_list:
        lines.extend(
            [
                f"- 本视频已归并 {len(open_theme_list)} 个开放主题；详细定义、类型与产品含义见下文「开放主题（归并结果）」。",
                "",
            ]
        )
    else:
        lines.extend(["- 暂无稳定问题主题。可先生成开放主题后再看本段。", ""])

    lines.extend(["## 4. 用户行为与行动差距", ""])
    grouped_behaviors = _behavior_groups(item_index)
    for label, rids in sorted(grouped_behaviors.items(), key=lambda item: -len(item[1])):
        lines.append(f"- **{label}**：{len(rids)} 条 / {_users_for_ids(records, rids)} 名用户")
    if not grouped_behaviors:
        lines.append("- 本批未提取到可归并的行为或行动差距。")
    lines.append("")

    lines.extend(["## 5. 值得验证的机会", ""])
    for opportunity in _minimal_opportunities(themes, profile)[:3]:
        lines.extend(
            [
                f"### {opportunity['name']}",
                "",
                f"- **要解决的单一问题**：{opportunity['problem']}",
                f"- **最小验证**：{opportunity['experiment']}",
                "- **当前边界**：这是待验证机会，不代表需求或付费已成立。",
                "",
            ]
        )
    if not themes:
        lines.extend(["- 当前证据不足以提出产品机会。", ""])

    lines.extend(
        [
            "## 6. 方法与限制",
            "",
            (
                "- 全部 evidence_items 已先由代码按类型、子类型、说话范围、确定性与语义规则聚合，再交给研究 Agent。"
                if aggregate_research_used
                else "- 本任务沿用既有研究结果与开放主题归并；定性结构统计来自本视频评论分析结果。"
            ),
            "- 代表原话优先由 evidence_item_id 回填；开放主题可补充归并时的代表原话。",
            f"- 已归入主题：{covered} 条；仅有低信息互动：{low_information} 条；未聚类但有效：{unclustered_valid} 条。",
            f"- 跑题：{summary.get('off_topic_comments', 0)}；机器生成：{summary.get('machine_generated_comments', 0)}；垃圾内容：{summary.get('spam_comments', 0)}；乱码：{summary.get('garbled_comments', 0)}。",
        ]
    )
    if dropped:
        lines.append(f"- 跳过无效证据引用 {len(dropped)} 条，未补写或猜测原话。")
    lines.extend(
        [
            "- 单一内容评论样本存在选择偏差；自我报告不能视为客观效果。",
            "",
            "## 7. 证据附录",
            "",
            "完整标准 evidence_items 与原评论保存在任务目录 `evidence_cards.jsonl`；正文不重复堆叠 JSON。",
            "",
        ]
    )
    return "\n".join(lines)
