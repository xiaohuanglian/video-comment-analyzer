# -*- coding: utf-8 -*-
"""Export analysis results as CSV and shareable reports."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Dict, List

from .candidate_schemas import CONTACT_STATUS_LABELS
from .labels import (
    INTENT_LABELS,
    PRODUCT_FIT_LABELS,
    SIGNAL_LABELS,
    SINGLE_VIDEO_LABELS,
    TRAINING_EVIDENCE_LABELS,
    label_hypothesis_relation,
    label_intent,
    label_product_fit,
    label_signal,
    label_single_video,
)
from .prompts import HYPOTHESES
from .statistics import candidate_priority, compute_candidate_score
from .storage import (
    _read_json,
    _run_dir,
    load_candidates,
    load_config,
    load_outreach,
    load_progress,
    load_results,
    load_summary,
    save_summary,
)
from .run_locations import export_artifact_paths, export_artifact_targets


def _format_hypothesis_relations(relations: Any) -> str:
    if not relations:
        return ""
    parts: List[str] = []
    for item in relations:
        if not isinstance(item, dict):
            continue
        hid = item.get("hypothesis_id", "")
        rel = item.get("relation", "")
        parts.append(f"{hid}:{label_hypothesis_relation(str(rel))}")
    return "；".join(parts)


def _format_new_signals(signals: Any) -> str:
    if not signals:
        return ""
    parts: List[str] = []
    for item in signals:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("signal_text") or "").strip()
            signal_type = str(item.get("type") or "").strip()
            if text and signal_type:
                parts.append(f"{text}（{signal_type}）")
            elif text:
                parts.append(text)
        else:
            parts.append(str(item))
    return "；".join(part for part in parts if part)


def build_results_csv(run_id: str) -> bytes:
    rows = load_results(run_id)
    if not rows:
        raise ValueError("尚无分析结果可导出")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "record_id",
            "评论",
            "用户",
            "用户主页",
            "平台",
            "视频标题",
            "博主",
            "分类",
            "主要目的",
            "信息信号",
            "训练证据",
            "具体问题",
            "单向视频关系",
            "假设关系",
            "新发现",
            "产品适配",
            "置信度",
            "分析时间",
        ]
    )
    for row in rows:
        source = row.get("source") or {}
        analysis = row.get("analysis") or {}
        writer.writerow(
            [
                row.get("record_id") or analysis.get("record_id") or "",
                source.get("comment_text") or "",
                source.get("username") or source.get("user_id") or "",
                source.get("user_homepage_url") or "",
                source.get("platform") or "",
                source.get("video_title") or "",
                source.get("creator_name") or "",
                source.get("creator_type") or "",
                label_intent(str(analysis.get("primary_intent") or "")),
                "，".join(label_signal(str(s)) for s in (analysis.get("signals") or [])),
                TRAINING_EVIDENCE_LABELS.get(
                    str(analysis.get("actual_training_evidence") or ""), analysis.get("actual_training_evidence") or ""
                ),
                "；".join(str(p) for p in (analysis.get("specific_problems") or [])),
                label_single_video(str(analysis.get("single_video_relation") or "")),
                _format_hypothesis_relations(analysis.get("hypothesis_relations")),
                _format_new_signals(analysis.get("new_signals")),
                label_product_fit(str(analysis.get("product_fit") or "")),
                analysis.get("confidence"),
                row.get("analyzed_at") or "",
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


def _elapsed_seconds(progress: Dict[str, Any]) -> int | None:
    started = progress.get("started_at")
    if not started:
        return None
    try:
        start_dt = datetime.fromisoformat(started)
        end_raw = progress.get("updated_at") if progress.get("status") == "completed" else None
        end_dt = datetime.fromisoformat(end_raw) if end_raw else datetime.now(timezone.utc)
        return max(0, int((end_dt - start_dt).total_seconds()))
    except ValueError:
        return None


def _format_duration(total_seconds: int | None) -> str:
    if total_seconds is None or total_seconds <= 0:
        return "—"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: List[str] = []
    if hours:
        parts.append(f"{hours} 小时")
    if minutes:
        parts.append(f"{minutes} 分钟")
    if not parts and seconds:
        parts.append(f"{seconds} 秒")
    return " ".join(parts) or "少于 1 分钟"


def _pct(count: int, total: int) -> str:
    if not total:
        return "0%"
    return f"{round(count / total * 100, 1)}%"


def _status_label(status: str) -> str:
    return {
        "completed": "已完成",
        "running": "分析中",
        "paused": "已暂停",
        "failed": "失败",
        "ready": "待开始",
        "cancelled": "已取消",
    }.get(status, status or "—")


def _collect_high_priority_rows(rows: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    scored: List[tuple[int, Dict[str, Any]]] = []
    for row in rows:
        analysis = row.get("analysis") or {}
        score = compute_candidate_score(analysis)
        if candidate_priority(score) == "high":
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1].get("record_id") or ""))
    return [row for _, row in scored[:limit]]


def _collect_new_signals(rows: List[Dict[str, Any]], limit: int = 10) -> List[str]:
    items: List[str] = []
    seen: set[str] = set()
    for row in rows:
        analysis = row.get("analysis") or {}
        source = row.get("source") or {}
        comment = (source.get("comment_text") or "")[:60]
        for signal in analysis.get("new_signals") or []:
            if not isinstance(signal, dict):
                continue
            text = str(signal.get("text") or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            quote = str(signal.get("evidence_quote") or text).strip()
            items.append(f"- **{text}** — 「{quote}」{' · 来自：' + comment + '…' if comment else ''}")
            if len(items) >= limit:
                return items
    return items


def build_report_markdown(run_id: str) -> str:
    config = load_config(run_id)
    progress = load_progress(run_id).model_dump()
    summary_path = _run_dir(run_id) / "summary.json"
    summary: Dict[str, Any] = _read_json(summary_path) if summary_path.exists() else {}
    rows = load_results(run_id)
    analyzed = summary.get("total_analyzed") or len(rows)
    total_records = progress.get("total_records") or analyzed

    lines = [
        f"# 评论洞察报告：{config.name}",
        "",
        "## 执行摘要",
        "",
    ]

    if not analyzed:
        lines.extend(
            [
                "> 尚无分析结果。请先完成至少一批评论分析，或导出 CSV 查看明细。",
                "",
                f"- 任务 ID：`{run_id}`",
                f"- 状态：{_status_label(str(progress.get('status') or ''))}",
                f"- 进度：{progress.get('completed', 0)} / {total_records} 条",
            ]
        )
        return "\n".join(lines)

    coverage_note = ""
    if analyzed < total_records:
        coverage_note = f"（样本 {analyzed} 条，占全量 {total_records} 条的 {_pct(analyzed, total_records)}）"

    lines.extend(
        [
            f"本报告基于 **{analyzed} 条**已分析评论{coverage_note}，用于产品假设验证与用户需求洞察。",
            "",
            f"- **核心发现**：{summary.get('trained_users', 0)} 位用户有真实训练证据；"
            f"{summary.get('personalized_needed_count', 0)} 条评论被判断为需个性化判断；"
            f"{summary.get('realtime_needed_count', 0)} 条被判断为需实时观察；"
            f"{summary.get('high_priority_user_count', 0)} 位高优先级潜在用户"
            f"{'（来自 candidates.json）' if summary.get('high_priority_user_count_source') == 'candidates_json' else ''}。",
            f"- **假设倾向**：H2（需实时反馈）支持 {summary.get('hypothesis_counts', {}).get('H2', {}).get('supports', 0)} 条；"
            f"H3（需 Agent 规划）支持 {summary.get('hypothesis_counts', {}).get('H3', {}).get('supports', 0)} 条。",
            "",
            "## 任务概况",
            "",
            "| 项目 | 数值 |",
            "| --- | --- |",
            f"| 任务 ID | `{run_id}` |",
            f"| 分析状态 | {_status_label(str(progress.get('status') or ''))} |",
            f"| 已分析 / 总量 | {progress.get('completed', analyzed)} / {total_records} 条 |",
            f"| 失败 | {progress.get('failed', 0)} 条 |",
            f"| Prompt Tokens | {progress.get('prompt_tokens', 0):,} |",
            f"| 缓存命中 Tokens | {progress.get('prompt_cache_hit_tokens', 0):,} |",
            f"| Completion Tokens | {progress.get('completion_tokens', 0):,} |",
            f"| 实际费用 | {progress.get('actual_cost') or progress.get('estimated_cost', 0):.4f} {config.currency} |",
            f"| 耗时 | {_format_duration(_elapsed_seconds(progress))} |",
            f"| 模型 | {config.model_name} |",
            f"| Prompt 版本 | {config.prompt_version} |",
            "",
            "## 总体指标",
            "",
            "| 指标 | 数值 | 说明 |",
            "| --- | ---: | --- |",
            f"| 有效评论 | {summary.get('valid_comments', 0)} | 排除无效/不明意图 |",
            f"| 独立用户 | {summary.get('unique_users', 0)} | 按 user_id / 主页 / 昵称去重 |",
            f"| 来源视频 | {summary.get('source_video_count', 0)} | 按视频标题/文件去重 |",
            f"| UP 主数 | {summary.get('source_creator_count', 0)} | 按 creator_name 去重 |",
            f"| 来源文件 | {summary.get('source_file_count', 0)} | CSV 文件数 |",
            f"| 已训练用户 | {summary.get('trained_users', 0)} | 有 tried / continued 证据 |",
            f"| 可定位主页 | {summary.get('contactable_homepage_count', 0)} | 可推导 B 站用户空间链接 |",
            f"| 感谢信号 | {summary.get('gratitude_signal_count', 0)} | 含 gratitude 标签 |",
            f"| 需个性化判断 | {summary.get('personalized_needed_count', 0)} | 单向视频不足 |",
            f"| 需实时观察 | {summary.get('realtime_needed_count', 0)} | 需动作质量反馈 |",
            f"| 高产品适配 | {summary.get('product_fit_high_count', 0)} | product_fit = high |",
            f"| 高优先级潜在用户 | {summary.get('high_priority_user_count', 0)} | 用户级，综合评分 ≥ 7 |",
            f"| 高优先级候选评论 | {summary.get('high_priority_candidate_comment_count', 0)} | 评论级，供交叉核对 |",
            "",
            "## 主要沟通目的",
            "",
            "| 目的 | 条数 | 占比 |",
            "| --- | ---: | ---: |",
        ]
    )

    counts = summary.get("primary_intent_counts") or {}
    intents = summary.get("primary_intent_percentages") or {}
    for key in sorted(intents.keys(), key=lambda k: (-counts.get(k, 0), k)):
        lines.append(f"| {label_intent(key)} | {counts.get(key, 0)} | {intents.get(key, 0)}% |")

    lines.extend(["", "## 信息信号覆盖率", "", "> 同一评论可含多个信号，覆盖率之和可能超过 100%。", "", "| 信号 | 条数 | 覆盖率 |", "| --- | ---: | ---: |"])
    for key, info in (summary.get("signal_coverage") or {}).items():
        lines.append(f"| {label_signal(key)} | {info.get('count', 0)} | {info.get('coverage_pct', 0)}% |")

    lines.extend(["", "## 单向视频关系", "", "| 关系 | 条数 | 覆盖率 |", "| --- | ---: | ---: |"])
    for key, info in (summary.get("single_video_stats") or {}).items():
        if info.get("count", 0) <= 0:
            continue
        lines.append(f"| {label_single_video(key)} | {info.get('count', 0)} | {info.get('coverage_pct', 0)}% |")

    fit_counts = summary.get("product_fit_counts") or {}
    if fit_counts:
        lines.extend(["", "## 产品适配分布", "", "| 适配度 | 条数 |", "| --- | ---: |"])
        for key in ("high", "medium", "low", "unclear"):
            if fit_counts.get(key, 0):
                lines.append(f"| {label_product_fit(key)} | {fit_counts.get(key, 0)} |")

    lines.extend(["", "## 假设验证", ""])
    for hid in ("H1", "H2", "H3"):
        detail = (summary.get("hypothesis_details") or {}).get(hid) or {}
        label = detail.get("label") or HYPOTHESES.get(hid, hid)
        rel_counts = detail.get("counts") or {}
        total_h = sum(rel_counts.values()) or 1
        lines.extend(
            [
                f"### {hid} · {label}",
                "",
                "| 关系 | 条数 | 占比 | 独立用户 |",
                "| --- | ---: | ---: | ---: |",
                f"| 支持 | {rel_counts.get('supports', 0)} | {_pct(rel_counts.get('supports', 0), total_h)} | {(detail.get('unique_users') or {}).get('supports', 0)} |",
                f"| 削弱 | {rel_counts.get('weakens', 0)} | {_pct(rel_counts.get('weakens', 0), total_h)} | {(detail.get('unique_users') or {}).get('weakens', 0)} |",
                f"| 信息不足 | {rel_counts.get('insufficient', 0)} | {_pct(rel_counts.get('insufficient', 0), total_h)} | {(detail.get('unique_users') or {}).get('insufficient', 0)} |",
                f"| 无关 | {rel_counts.get('irrelevant', 0)} | {_pct(rel_counts.get('irrelevant', 0), total_h)} | {(detail.get('unique_users') or {}).get('irrelevant', 0)} |",
                "",
            ]
        )
        support_quotes = detail.get("support_quotes") or []
        weaken_quotes = detail.get("weaken_quotes") or []
        if support_quotes:
            lines.append("**支持性原话（节选）**")
            for quote in support_quotes[:5]:
                lines.append(f"- 「{quote}」")
            lines.append("")
        if weaken_quotes:
            lines.append("**削弱性原话（节选）**")
            for quote in weaken_quotes[:5]:
                lines.append(f"- 「{quote}」")
            lines.append("")

    contradictions = summary.get("contradictions") or []
    if contradictions:
        lines.extend(["## 与预期不一致的发现", ""])
        for item in contradictions:
            importance = "（重要反例）" if item.get("importance") == "important" else ""
            lines.append(
                f"- **{item.get('hypothesis_id', '')}**{importance}：削弱 {item.get('weaken_count', 0)} 条 / "
                f"支持 {item.get('support_count', 0)} 条 — {item.get('caution_note', '')}"
            )
            for quote in (item.get("representative_quotes") or item.get("sample_quotes") or [])[:3]:
                lines.append(f"  - 「{quote}」")
        lines.append("")

    realtime = summary.get("realtime_needed_count", 0)
    valid = summary.get("valid_comments") or analyzed or 1
    lines.extend(
        [
            "## 当前数据无法证明的结论",
            "",
            f"- 当前样本中有 {realtime} 条评论被判断为需要实时观察，占有效评论的 {_pct(realtime, valid)}。"
            "该结果支持**部分**用户可能存在实时动作反馈需求，**不能**代表全部居家健身用户。",
            "- 开放主题与高优先级用户名单仅基于已分析评论，**不能**直接推导市场规模或产品必然成功。",
            "- 本工具**不提供**医学诊断；涉及伤病、疼痛、术后恢复等评论需人工审慎解读。",
            "",
        ]
    )

    priority_rows = _collect_high_priority_rows(rows)
    if priority_rows:
        lines.extend(["## 高优先级候选评论（节选）", "", "以下评论综合训练证据、具体问题、求助意愿与产品适配度评分较高，建议优先人工复核。", ""])
        for row in priority_rows:
            source = row.get("source") or {}
            analysis = row.get("analysis") or {}
            user = source.get("username") or source.get("user_id") or "未知用户"
            comment = (source.get("comment_text") or "").replace("\n", " ")
            if len(comment) > 120:
                comment = comment[:120] + "…"
            problems = "；".join(str(p) for p in (analysis.get("specific_problems") or []))
            signals = "，".join(label_signal(str(s)) for s in (analysis.get("signals") or [])[:4])
            lines.append(f"- **{user}** · {label_single_video(str(analysis.get('single_video_relation') or ''))}")
            lines.append(f"  - 评论：「{comment}」")
            if problems:
                lines.append(f"  - 具体问题：{problems}")
            if signals:
                lines.append(f"  - 信号：{signals}")
        lines.append("")

    new_signal_lines = _collect_new_signals(rows)
    if new_signal_lines:
        lines.extend(["## 开放发现（new_signals）", "", "模型认为预设标签未能完整覆盖的用户表达：", ""])
        lines.extend(new_signal_lines)
        lines.append("")

    theme_lines = _collect_theme_section(run_id)
    if theme_lines:
        lines.extend(theme_lines)

    lines.extend(
        [
            "## 使用说明",
            "",
            "- 本报告为自动汇总，**不能替代人工判读**；关键结论请结合 CSV 明细复核。",
            "- 「支持/削弱」均要求模型给出原文证据；信息不足表示相关但无法下结论。",
            f"- 完整明细请查看同目录自动保存的 **分析结果 CSV**（任务 `{run_id}`）。",
            "",
            "---",
            "",
            f"*报告生成于 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · {config.prompt_version}*",
        ]
    )
    return "\n".join(lines)


def _collect_theme_section(run_id: str) -> List[str]:
    """Include clustered open themes when themes.json exists."""
    from .storage import load_themes
    from .theme_schemas import THEME_RELATION_LABELS

    doc = load_themes(run_id)
    themes = getattr(doc, "themes", None) or []
    if not themes:
        return []
    lines: List[str] = ["## 开放主题（归并结果）", "", "以下为主题归并后的结构化发现（来自「生成开放主题」）：", ""]
    for theme in themes:
        name = getattr(theme, "theme_name", "") or "未命名主题"
        ttype = getattr(theme, "theme_type", "") or "—"
        definition = getattr(theme, "definition", "") or ""
        implication = getattr(theme, "implication", "") or ""
        relation = getattr(theme, "relation_to_existing_hypotheses", "") or ""
        rel_label = THEME_RELATION_LABELS.get(relation, relation)
        stats = getattr(theme, "stats", None)
        count_note = ""
        if stats is not None:
            count_note = f" · {getattr(stats, 'comment_count', 0)} 条 / {getattr(stats, 'unique_user_count', 0)} 用户"
        lines.append(f"### {name}（{ttype}）{count_note}")
        lines.append("")
        if definition:
            lines.append(f"- 定义：{definition}")
        if rel_label:
            lines.append(f"- 与假设关系：{rel_label}")
        if implication:
            lines.append(f"- 产品含义：{implication}")
        sample = getattr(theme, "representative_quotes", None) or []
        for quote in sample[:3]:
            lines.append(f"  - 「{quote}」")
        lines.append("")
    return lines


def build_candidates_csv(run_id: str) -> bytes:
    doc = load_candidates(run_id)
    if not doc.candidates:
        raise ValueError("尚无候选用户可导出，请先生成候选列表")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "user_key",
            "用户名",
            "平台",
            "主页",
            "评分",
            "优先级",
            "可联系性",
            "联系状态",
            "联系理由",
            "产品适配",
            "训练证据",
            "求助",
            "具体问题",
            "视频关系",
            "代表评论",
            "评论数",
            "评论链接",
            "产品经理备注",
        ]
    )
    for candidate in doc.candidates:
        writer.writerow(
            [
                candidate.user_key,
                candidate.username,
                candidate.platform,
                candidate.homepage_url,
                candidate.candidate_score,
                candidate.priority,
                candidate.contactability,
                CONTACT_STATUS_LABELS.get(candidate.contact_status, candidate.contact_status),
                candidate.contact_reason,
                label_product_fit(candidate.product_fit),
                TRAINING_EVIDENCE_LABELS.get(candidate.actual_training_evidence, candidate.actual_training_evidence),
                "是" if candidate.help_seeking else "否",
                "；".join(candidate.specific_problems),
                "；".join(label_single_video(r) for r in candidate.single_video_relations),
                " | ".join(candidate.representative_quotes),
                len(candidate.record_ids),
                "；".join(candidate.comment_urls),
                candidate.product_manager_note,
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


def build_outreach_csv(run_id: str) -> bytes:
    doc = load_outreach(run_id)
    if not doc.entries:
        raise ValueError("尚无联系记录可导出，请先生成私信草稿")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "user_key",
            "用户名",
            "联系状态",
            "生成草稿",
            "编辑后内容",
            "模型",
            "费用",
            "生成时间",
            "产品经理备注",
        ]
    )
    for entry in doc.entries:
        content = entry.edited_content or entry.generated_draft
        writer.writerow(
            [
                entry.user_key,
                entry.username,
                CONTACT_STATUS_LABELS.get(entry.contact_status, entry.contact_status),
                entry.generated_draft,
                entry.edited_content,
                entry.model_name,
                entry.cost,
                entry.generated_at,
                entry.product_manager_note,
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


def build_report_json(run_id: str) -> Dict[str, Any]:
    config = load_config(run_id)
    progress = load_progress(run_id).model_dump()
    summary_path = _run_dir(run_id) / "summary.json"
    summary: Dict[str, Any] = _read_json(summary_path) if summary_path.exists() else {}
    return {
        "run_id": run_id,
        "name": config.name,
        "config": {
            "model_name": config.model_name,
            "base_url": config.base_url,
            "prompt_version": config.prompt_version,
            "created_at": config.created_at,
        },
        "progress": progress,
        "summary": summary,
        "elapsed_seconds": _elapsed_seconds(progress),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


def _rel_to_data(path: Path) -> str:
    from . import storage

    try:
        return path.relative_to(storage.DATA_DIR).as_posix()
    except ValueError:
        return str(path)


def auto_export_artifacts(run_id: str) -> Dict[str, str]:
    """Write analysis CSV, report, and optional candidates/outreach beside every CSV parent dir."""
    if not load_results(run_id):
        return {}

    config = load_config(run_id)
    target_sets = export_artifact_targets(config)
    errors: List[str] = []
    saved: Dict[str, str] = {}

    results_bytes: bytes | None = None
    report_text: str | None = None
    candidates_bytes: bytes | None = None
    outreach_bytes: bytes | None = None

    try:
        results_bytes = build_results_csv(run_id)
    except ValueError as exc:
        errors.append(f"results_csv: {exc}")
    try:
        report_text = build_report_markdown(run_id)
    except Exception as exc:
        errors.append(f"report_md: {exc}")
    try:
        if load_candidates(run_id).candidates:
            candidates_bytes = build_candidates_csv(run_id)
    except ValueError:
        candidates_bytes = None
    try:
        if load_outreach(run_id).entries:
            outreach_bytes = build_outreach_csv(run_id)
    except ValueError:
        outreach_bytes = None

    for targets in target_sets:
        if results_bytes is not None:
            try:
                targets["results_csv"].parent.mkdir(parents=True, exist_ok=True)
                targets["results_csv"].write_bytes(results_bytes)
                saved.setdefault("results_csv", _rel_to_data(targets["results_csv"]))
            except OSError as exc:
                errors.append(f"results_csv write: {exc}")
        if report_text is not None:
            try:
                targets["report_md"].parent.mkdir(parents=True, exist_ok=True)
                targets["report_md"].write_text(report_text, encoding="utf-8")
                saved.setdefault("report_md", _rel_to_data(targets["report_md"]))
            except OSError as exc:
                errors.append(f"report_md write: {exc}")
        if candidates_bytes is not None:
            try:
                targets["candidates_csv"].parent.mkdir(parents=True, exist_ok=True)
                targets["candidates_csv"].write_bytes(candidates_bytes)
                saved.setdefault("candidates_csv", _rel_to_data(targets["candidates_csv"]))
            except OSError as exc:
                errors.append(f"candidates_csv write: {exc}")
        if outreach_bytes is not None:
            try:
                targets["outreach_csv"].parent.mkdir(parents=True, exist_ok=True)
                targets["outreach_csv"].write_bytes(outreach_bytes)
                saved.setdefault("outreach_csv", _rel_to_data(targets["outreach_csv"]))
            except OSError as exc:
                errors.append(f"outreach_csv write: {exc}")

    summary = load_summary(run_id)
    if saved:
        summary["export_paths"] = {**(summary.get("export_paths") or {}), **saved}
        summary["export_updated_at"] = datetime.now(timezone.utc).isoformat()
    if errors:
        summary["export_error"] = "; ".join(errors)[:500]
        save_summary(run_id, summary)
        raise OSError(summary["export_error"])
    summary.pop("export_error", None)
    save_summary(run_id, summary)
    return saved


def auto_export_candidates_outreach(run_id: str) -> Dict[str, str]:
    """Re-export candidates/outreach CSVs after they are generated or updated."""
    config = load_config(run_id)
    target_sets = export_artifact_targets(config)
    saved: Dict[str, str] = {}
    errors: List[str] = []

    candidates_bytes: bytes | None = None
    outreach_bytes: bytes | None = None
    try:
        if load_candidates(run_id).candidates:
            candidates_bytes = build_candidates_csv(run_id)
    except ValueError:
        pass
    try:
        if load_outreach(run_id).entries:
            outreach_bytes = build_outreach_csv(run_id)
    except ValueError:
        pass

    for targets in target_sets:
        if candidates_bytes is not None:
            try:
                targets["candidates_csv"].parent.mkdir(parents=True, exist_ok=True)
                targets["candidates_csv"].write_bytes(candidates_bytes)
                saved.setdefault("candidates_csv", _rel_to_data(targets["candidates_csv"]))
            except OSError as exc:
                errors.append(str(exc))
        if outreach_bytes is not None:
            try:
                targets["outreach_csv"].parent.mkdir(parents=True, exist_ok=True)
                targets["outreach_csv"].write_bytes(outreach_bytes)
                saved.setdefault("outreach_csv", _rel_to_data(targets["outreach_csv"]))
            except OSError as exc:
                errors.append(str(exc))

    if saved:
        summary = load_summary(run_id)
        summary["export_paths"] = {**(summary.get("export_paths") or {}), **saved}
        summary["export_updated_at"] = datetime.now(timezone.utc).isoformat()
        if errors:
            summary["export_error"] = "; ".join(errors)[:500]
        else:
            summary.pop("export_error", None)
        save_summary(run_id, summary)
    if errors and not saved:
        raise OSError("; ".join(errors))
    return saved
