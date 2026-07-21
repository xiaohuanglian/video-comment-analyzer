# -*- coding: utf-8 -*-
"""Build 50-item blind A/B review pack (CSV + HTML). Does NOT fill human scores."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from api.services.insight.ab_blind_pack import select_blind_sample_ids, TARGET_TOTAL
from api.services.insight.storage import load_evidence_cards, load_results

DEFAULT_LEGACY_RUN = "戴夫健身_2"
DEFAULT_EVIDENCE_RUN = "ab_evidence_戴夫健身_2_100"
DEFAULT_LIMIT = 100
DEFAULT_SEED = 20260720


def _encode_source(label: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), label.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:12]).decode("ascii").rstrip("=")


def _slim_legacy(analysis: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "primary_intent",
        "specific_problems",
        "user_actions",
        "hypothesis_relations",
        "product_fit",
        "new_signals",
        "evidence_quotes",
        "summary",
        "help_seeking",
        "invalid_or_unclear_reason",
    )
    out = {k: analysis.get(k) for k in keys if k in analysis}
    return out or analysis


def _slim_evidence(card: Dict[str, Any]) -> Dict[str, Any]:
    """Prefer evidence_items_v1 fields; fall back to B1–B3 parallel arrays."""
    if card.get("evidence_items") is not None:
        keys = (
            "record_status",
            "evidence_level",
            "primary_expression",
            "evidence_items",
            "status_reason",
            "downgrade_reason",
        )
        out = {k: card.get(k) for k in keys if k in card}
        return out or card
    keys = (
        "record_status",
        "evidence_level",
        "validity",
        "invalid_reason",
        "status_reason",
        "primary_expression",
        "secondary_expressions",
        "expression_signals",
        "explicit_facts",
        "problem_or_need",
        "training_behavior",
        "content_engagement",
        "action_gap",
        "actual_behavior",
        "current_solution",
        "impact_or_cost",
        "user_context",
        "quantitative_evidence",
        "possible_new_signal",
        "research_relevance",
        "confidence",
    )
    return {k: card.get(k) for k in keys if k in card}


def _index_legacy(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        rid = row.get("record_id") or (row.get("source") or {}).get("internal_record_id")
        if rid:
            out[rid] = row
    return out


def _index_evidence(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        rid = row.get("record_id") or (row.get("card") or {}).get("record_id")
        if rid:
            out[rid] = row
    return out


def _source_fields(legacy_row: Dict[str, Any], evidence_row: Dict[str, Any]) -> Dict[str, str]:
    source = legacy_row.get("source") or evidence_row.get("source") or {}
    return {
        "comment_text": source.get("comment_text") or "",
        "parent_comment": source.get("parent_comment") or "",
        "creator_reply": source.get("creator_reply") or source.get("author_reply") or "",
        "video_title": source.get("video_title") or "",
    }


def build_rows(
    samples: Sequence[Dict[str, str]],
    legacy_by_id: Dict[str, Dict[str, Any]],
    evidence_by_id: Dict[str, Dict[str, Any]],
    *,
    seed: int,
    secret: str,
) -> List[Dict[str, Any]]:
    rng = random.Random(seed + 17)
    rows: List[Dict[str, Any]] = []
    for sample in samples:
        rid = sample["record_id"]
        legacy_row = legacy_by_id[rid]
        evidence_row = evidence_by_id[rid]
        fields = _source_fields(legacy_row, evidence_row)
        a_json = _slim_legacy(legacy_row.get("analysis") or {})
        b_json = _slim_evidence(evidence_row.get("card") or {})
        if rng.random() < 0.5:
            opt1, opt2 = a_json, b_json
            src1, src2 = "A_legacy", "B_evidence"
        else:
            opt1, opt2 = b_json, a_json
            src1, src2 = "B_evidence", "A_legacy"
        rows.append(
            {
                "record_id": rid,
                "comment_text": fields["comment_text"],
                "parent_comment": fields["parent_comment"],
                "creator_reply": fields["creator_reply"],
                "video_title": fields["video_title"],
                "option_1_json": json.dumps(opt1, ensure_ascii=False),
                "option_2_json": json.dumps(opt2, ensure_ascii=False),
                "option_1_source_encrypted": _encode_source(src1, secret),
                "option_2_source_encrypted": _encode_source(src2, secret),
                "sample_group": sample["sample_group"],
                "_option_1_source": src1,
                "_option_2_source": src2,
            }
        )
    return rows


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    fieldnames = [
        "record_id",
        "comment_text",
        "parent_comment",
        "creator_reply",
        "video_title",
        "option_1_json",
        "option_2_json",
        "option_1_source_encrypted",
        "option_2_source_encrypted",
        "sample_group",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def write_key_map(path: Path, rows: Sequence[Dict[str, Any]], secret: str, notes: Dict[str, Any]) -> None:
    """Sealed mapping for post-review scoring only — do not open during blind review."""
    payload = {
        "warning": "盲评完成前请勿打开。用于复原方案甲/乙对应 A/B。",
        "secret_hint": hashlib.sha256(secret.encode()).hexdigest()[:16],
        "encode": {
            "A_legacy": _encode_source("A_legacy", secret),
            "B_evidence": _encode_source("B_evidence", secret),
        },
        "composition": notes,
        "items": [
            {
                "record_id": r["record_id"],
                "sample_group": r["sample_group"],
                "option_1_source": r["_option_1_source"],
                "option_2_source": r["_option_2_source"],
            }
            for r in rows
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_html(path: Path, rows: Sequence[Dict[str, Any]], notes: Dict[str, Any]) -> None:
    items_js = json.dumps(
        [
            {
                "record_id": r["record_id"],
                "comment_text": r["comment_text"],
                "parent_comment": r["parent_comment"],
                "creator_reply": r["creator_reply"],
                "video_title": r["video_title"],
                "option_1_json": r["option_1_json"],
                "option_2_json": r["option_2_json"],
                "sample_group": r["sample_group"],
            }
            for r in rows
        ],
        ensure_ascii=False,
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8"/>
<title>A/B 盲评包（50条）</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f6f7f9; color: #1a1a1a; }}
header {{ padding: 16px 20px; background: #fff; border-bottom: 1px solid #e5e7eb; position: sticky; top: 0; z-index: 2; }}
h1 {{ margin: 0 0 6px; font-size: 18px; }}
.meta {{ font-size: 13px; color: #555; }}
.actions {{ margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }}
button {{ padding: 8px 12px; border: 1px solid #ccc; background: #fff; border-radius: 6px; cursor: pointer; }}
button.primary {{ background: #111; color: #fff; border-color: #111; }}
main {{ padding: 16px 20px 80px; max-width: 1200px; margin: 0 auto; }}
.card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
.card h2 {{ margin: 0 0 8px; font-size: 15px; }}
.context p {{ margin: 4px 0; font-size: 14px; line-height: 1.5; white-space: pre-wrap; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} }}
.panel {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; background: #fafafa; }}
.panel h3 {{ margin: 0 0 8px; font-size: 14px; }}
pre {{ white-space: pre-wrap; word-break: break-word; font-size: 12px; margin: 0; max-height: 280px; overflow: auto; }}
.scores {{ margin-top: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
label {{ display: block; font-size: 12px; margin: 6px 0 2px; color: #444; }}
select, textarea, input[type=text] {{ width: 100%; box-sizing: border-box; padding: 6px; border: 1px solid #ccc; border-radius: 4px; }}
textarea {{ min-height: 56px; }}
.winner {{ margin-top: 10px; }}
.warn {{ color: #9a3412; font-size: 13px; }}
</style>
</head>
<body>
<header>
  <h1>评论洞察 A/B 盲评（方案甲 / 方案乙）</h1>
  <div class="meta">样本数：{notes.get("total", len(rows))} · 构成：invalid {notes.get("actual", {}).get("invalid")} / other {notes.get("actual", {}).get("other")} / B新增问题 {notes.get("actual", {}).get("b_new_problem")} / 假设冲突 {notes.get("actual", {}).get("hypothesis_conflict")} / backfill {len(notes.get("backfill") or [])} · seed={notes.get("seed")}</div>
  <p class="warn">请勿猜测哪边是新/旧方案。评分完成后点「导出结果」。本页不联网、不调模型。</p>
  <div class="actions">
    <button class="primary" onclick="exportCSV()">导出评分 CSV</button>
    <button onclick="exportJSON()">导出评分 JSON</button>
    <button onclick="saveLocal()">暂存到本地浏览器</button>
    <button onclick="loadLocal()">从本地恢复</button>
  </div>
</header>
<main id="root"></main>
<script>
const ITEMS = {items_js};
const SCORE_DIMS = [
  ["accuracy", "事实准确性 1-5"],
  ["completeness", "信息完整性 1-5"],
  ["over_inference", "过度推断程度 1-5（5=几乎无过度推断）"],
  ["traceability", "证据可追溯性 1-5"],
  ["research_value", "对产品研究的价值 1-5"],
];
const BOOL_DIMS = [
  ["missed_important", "是否漏掉重要信息"],
  ["fabricated", "是否虚构信息"],
  ["wrong_invalid", "是否错误判为无效"],
];

function emptyScore() {{
  const o = {{}};
  for (const [k] of SCORE_DIMS) o[k] = "";
  for (const [k] of BOOL_DIMS) o[k] = "";
  return o;
}}

function loadState() {{
  try {{ return JSON.parse(localStorage.getItem("ab_blind_review_state") || "{{}}"); }}
  catch (e) {{ return {{}}; }}
}}
let STATE = loadState();

function ensureState(id) {{
  if (!STATE[id]) {{
    STATE[id] = {{
      option_1: emptyScore(),
      option_2: emptyScore(),
      overall_winner: "",
      reviewer_note: "",
    }};
  }}
  return STATE[id];
}}

function render() {{
  const root = document.getElementById("root");
  root.innerHTML = "";
  ITEMS.forEach((item, idx) => {{
    const st = ensureState(item.record_id);
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <h2>#${{idx+1}} · ${{item.sample_group}}</h2>
      <div class="context">
        <p><strong>视频</strong>：${{escapeHtml(item.video_title || "（无）")}}</p>
        <p><strong>原评论</strong>：${{escapeHtml(item.comment_text || "")}}</p>
        <p><strong>父评论</strong>：${{escapeHtml(item.parent_comment || "（无）")}}</p>
        <p><strong>博主回复</strong>：${{escapeHtml(item.creator_reply || "（无）")}}</p>
      </div>
      <div class="grid">
        <div class="panel"><h3>方案甲</h3><pre>${{escapeHtml(pretty(item.option_1_json))}}</pre></div>
        <div class="panel"><h3>方案乙</h3><pre>${{escapeHtml(pretty(item.option_2_json))}}</pre></div>
      </div>
      <div class="scores" id="scores-${{idx}}"></div>
      <div class="winner">
        <label>总体优胜</label>
        <select data-id="${{item.record_id}}" data-field="overall_winner">
          <option value="">（未选）</option>
          <option value="option_1">方案甲</option>
          <option value="option_2">方案乙</option>
          <option value="tie">持平</option>
        </select>
        <label>备注 reviewer_note</label>
        <textarea data-id="${{item.record_id}}" data-field="reviewer_note"></textarea>
      </div>
    `;
    root.appendChild(card);
    const scores = card.querySelector(`#scores-${{idx}}`);
    scores.appendChild(scorePanel(item.record_id, "option_1", "方案甲评分", st.option_1));
    scores.appendChild(scorePanel(item.record_id, "option_2", "方案乙评分", st.option_2));
    const win = card.querySelector('select[data-field="overall_winner"]');
    win.value = st.overall_winner || "";
    win.addEventListener("change", onField);
    const note = card.querySelector('textarea[data-field="reviewer_note"]');
    note.value = st.reviewer_note || "";
    note.addEventListener("input", onField);
  }});
}}

function scorePanel(id, side, title, values) {{
  const div = document.createElement("div");
  div.className = "panel";
  let html = `<h3>${{title}}</h3>`;
  for (const [k, label] of SCORE_DIMS) {{
    html += `<label>${{label}}</label><select data-id="${{id}}" data-side="${{side}}" data-field="${{k}}">`;
    html += `<option value="">（未选）</option>`;
    for (let i=1;i<=5;i++) html += `<option value="${{i}}">${{i}}</option>`;
    html += `</select>`;
  }}
  for (const [k, label] of BOOL_DIMS) {{
    html += `<label>${{label}}</label><select data-id="${{id}}" data-side="${{side}}" data-field="${{k}}">
      <option value="">（未选）</option><option value="yes">是</option><option value="no">否</option>
    </select>`;
  }}
  div.innerHTML = html;
  div.querySelectorAll("select").forEach(el => {{
    const field = el.getAttribute("data-field");
    el.value = values[field] || "";
    el.addEventListener("change", onField);
  }});
  return div;
}}

function onField(ev) {{
  const el = ev.target;
  const id = el.getAttribute("data-id");
  const st = ensureState(id);
  const side = el.getAttribute("data-side");
  const field = el.getAttribute("data-field");
  if (side) st[side][field] = el.value;
  else st[field] = el.value;
}}

function pretty(raw) {{
  try {{ return JSON.stringify(JSON.parse(raw), null, 2); }}
  catch (e) {{ return raw; }}
}}
function escapeHtml(s) {{
  return String(s).replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[c]));
}}
function saveLocal() {{
  localStorage.setItem("ab_blind_review_state", JSON.stringify(STATE));
  alert("已暂存到本机浏览器 localStorage");
}}
function loadLocal() {{
  STATE = loadState();
  render();
  alert("已恢复");
}}
function collectRows() {{
  return ITEMS.map(item => {{
    const st = ensureState(item.record_id);
    const row = {{
      record_id: item.record_id,
      sample_group: item.sample_group,
      overall_winner: st.overall_winner,
      reviewer_note: st.reviewer_note,
    }};
    for (const side of ["option_1", "option_2"]) {{
      for (const [k] of SCORE_DIMS) row[`${{side}}_${{k}}`] = st[side][k];
      for (const [k] of BOOL_DIMS) row[`${{side}}_${{k}}`] = st[side][k];
    }}
    return row;
  }});
}}
function exportJSON() {{
  const blob = new Blob([JSON.stringify(collectRows(), null, 2)], {{type: "application/json"}});
  download(blob, "ab_review_results.json");
}}
function exportCSV() {{
  const rows = collectRows();
  if (!rows.length) return;
  const keys = Object.keys(rows[0]);
  const lines = [keys.join(",")].concat(rows.map(r => keys.map(k => csvEscape(r[k])).join(",")));
  download(new Blob([lines.join("\\n")], {{type: "text/csv"}}), "ab_review_results.csv");
}}
function csvEscape(v) {{
  const s = String(v ?? "");
  if (/[",\\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
  return s;
}}
function download(blob, name) {{
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}}
render();
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_composition_md(path: Path, notes: Dict[str, Any], validity_counts: Counter, expr_counts: Counter) -> None:
    lines = [
        "# A/B 盲评样本构成说明",
        "",
        f"- 随机种子：`{notes.get('seed')}`",
        f"- 总样本：`{notes.get('total')}`",
        "",
        "## 池规模",
        "",
        "```json",
        json.dumps(notes.get("pools"), ensure_ascii=False, indent=2),
        "```",
        "",
        "## 实际抽取",
        "",
        "```json",
        json.dumps(notes.get("actual"), ensure_ascii=False, indent=2),
        "```",
        "",
        "## B 组 validity / primary_expression 全量分布（生成时）",
        "",
        f"- validity: `{dict(validity_counts)}`",
        f"- primary_expression: `{dict(expr_counts)}`",
        "",
        "## 使用方式",
        "",
        "1. 打开 `ab_blind_review_50.html` 完盲评（不要打开 `ab_blind_key.json`）。",
        "2. 导出评分到 `ab_review_results.csv`。",
        "3. 人工验收完成后再对照 key 复原甲/乙与 A/B 对应关系，填写 `ab_review_summary.md`。",
        "",
        "> Cursor / 自动化不得代填人工评分。",
        "",
    ]
    if notes.get("backfill"):
        lines.extend(
            [
                "## 补足说明",
                "",
                f"某类不足时用相邻类别补足 `{len(notes['backfill'])}` 条，record_id 见 composition/backfill。",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_results_template(path: Path) -> None:
    if path.exists():
        return
    headers = [
        "record_id",
        "sample_group",
        "overall_winner",
        "option_1_accuracy",
        "option_1_completeness",
        "option_1_over_inference",
        "option_1_traceability",
        "option_1_research_value",
        "option_1_missed_important",
        "option_1_fabricated",
        "option_1_wrong_invalid",
        "option_2_accuracy",
        "option_2_completeness",
        "option_2_over_inference",
        "option_2_traceability",
        "option_2_research_value",
        "option_2_missed_important",
        "option_2_fabricated",
        "option_2_wrong_invalid",
        "reviewer_note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()


def write_summary_placeholder(path: Path) -> None:
    if path.exists() and "待人工盲评" not in path.read_text(encoding="utf-8"):
        return
    path.write_text(
        """# A/B 盲评结果摘要

> 状态：**待人工盲评**。本文件不得由自动化代填分数。

## 待填指标

- A/B 各维度平均分
- invalid 误伤率
- other 可细分率
- B 新增问题准确率
- 假设证据准确率
- 典型错误 / 优秀案例
- 最终迁移建议（通过 / 不通过）

完成评分并导出 `ab_review_results.csv` 后，再更新本摘要。
""",
        encoding="utf-8",
    )


def build_pack(
    *,
    legacy_run_id: str,
    evidence_run_id: str,
    limit: int,
    out_dir: Path,
    seed: int,
    secret: str,
) -> Dict[str, Any]:
    legacy_rows = load_results(legacy_run_id, limit=limit)
    evidence_rows = load_evidence_cards(evidence_run_id, limit=limit)
    if not legacy_rows:
        raise FileNotFoundError(f"缺少 A 组结果: {legacy_run_id}")
    if not evidence_rows:
        raise FileNotFoundError(f"缺少 B 组证据卡: {evidence_run_id}")

    from api.services.insight.storage import load_research_analysis

    research = load_research_analysis(evidence_run_id) or {}
    legacy_by_id = _index_legacy(legacy_rows)
    evidence_by_id = _index_evidence(evidence_rows)
    samples, notes = select_blind_sample_ids(
        legacy_by_id, evidence_by_id, research, seed=seed, target_total=TARGET_TOTAL
    )
    rows = build_rows(samples, legacy_by_id, evidence_by_id, seed=seed, secret=secret)

    validity_counts: Counter = Counter()
    expr_counts: Counter = Counter()
    for row in evidence_rows:
        card = row.get("card") or {}
        validity_counts[str(card.get("validity") or "")] += 1
        expr_counts[str(card.get("primary_expression") or "")] += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "ab_blind_review_50.csv"
    html_path = out_dir / "ab_blind_review_50.html"
    key_path = out_dir / "ab_blind_key.json"
    comp_path = out_dir / "ab_sample_composition.md"
    results_path = out_dir / "ab_review_results.csv"
    summary_path = out_dir / "ab_review_summary.md"

    write_csv(csv_path, rows)
    write_html(html_path, rows, notes)
    write_key_map(key_path, rows, secret, notes)
    write_composition_md(comp_path, notes, validity_counts, expr_counts)
    write_results_template(results_path)
    write_summary_placeholder(summary_path)

    return {
        "out_dir": str(out_dir),
        "csv": str(csv_path),
        "html": str(html_path),
        "notes": notes,
        "total": len(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build A/B blind review pack")
    parser.add_argument("--legacy-run", default=DEFAULT_LEGACY_RUN)
    parser.add_argument("--evidence-run", default=DEFAULT_EVIDENCE_RUN)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--secret", default="kineo-ab-blind-20260720")
    parser.add_argument("--out-dir", default=str(APP_DIR / "data" / ".insight" / "ab_review"))
    args = parser.parse_args()
    result = build_pack(
        legacy_run_id=args.legacy_run,
        evidence_run_id=args.evidence_run,
        limit=args.limit,
        out_dir=Path(args.out_dir),
        seed=args.seed,
        secret=args.secret,
    )
    print(json.dumps({k: result[k] for k in ("out_dir", "csv", "html", "total", "notes")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
