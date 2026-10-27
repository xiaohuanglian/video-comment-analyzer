# -*- coding: utf-8 -*-
"""采集数据分析:一键出本轮洞察报告(人群/痛点/选题线索/回复机会)。"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services.llm import complete
from api.services.outreach.reply_automation import (
    BULK_COMMENT_DIR,
    COMMENT_DIR,
    classify_comment,
    read_collected,
)

router = APIRouter(prefix="/comments", tags=["comments"])

REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "analysis"
REPORTS_FILE = REPORT_DIR / "reports.json"  # 历史报告存档(追加,不覆盖)

ANALYZE_PROMPT = """你是评论区数据分析专家。给你一批 B 站评论的统计摘要和高赞评论摘录,你要产出一份运营洞察报告。

若提供了【既往报告结论】,本次分析必须在其基础上融合演进:
- 仍然成立的痛点:延续并补充新证据
- 发生变化的:更新判断,说明变化
- 新发现的:标注「新增」
- 不要把既往结论原样复述一遍

报告必须包含(用 JSON 输出,不要 Markdown 代码块):
{
 "audience": "这批评论者是谁(2-3 句话,具体到人群特征和水平阶段)",
 "pain_themes": [{"theme": "痛点/需求主题(延续既往的在主题后标(延续),新发现标(新增))", "evidence": "引用 1-2 条典型评论(精简)", "heat": "高/中/低"}],
 "reply_opportunities": [{"target": "适合回复的评论类型", "why": "为什么值得回", "example": "典型评论(精简)"}],
 "topic_hints": [{"title": "20字内选题", "signal": "来自什么评论信号", "score": 1-10}],
 "dos": ["接下来最该做的 3 件事(具体、可执行)"],
 "carry_over": "从既往报告延续下来的关键结论(一句话;无既往则空字符串)"
}
只输出 JSON。"""


class AnalyzeRequest(BaseModel):
    date: Optional[str] = None  # 如 2026-10-21;不填则分析全量
    keywords: str = ""  # 本次采集用的关键词(存档用,方便回看)
    sample_per_video: int = 12
    max_videos: int = 8


def _load_rows(date: Optional[str]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str]:
    """按日期读两个采集目录(手动批量 data/comments + 自动周期 data/automation/comments),
    comment_id 去重合并;无日期则全量合并。"""
    dirs = (BULK_COMMENT_DIR, COMMENT_DIR)
    if date:
        rows: list[dict[str, Any]] = []
        video_map: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for d in dirs:
            c = d / f"comments_{date}.jsonl"
            if c.exists():
                for line in c.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cid = str(row.get("comment_id") or "")
                    if cid:
                        if cid in seen:
                            continue
                        seen.add(cid)
                    rows.append(row)
            v = d / f"contents_{date}.jsonl"
            if v.exists():
                for line in v.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    video_map.setdefault(str(item.get("video_id")), item)
        return rows, video_map, date
    rows_a, vm_a, _ = read_collected(BULK_COMMENT_DIR)
    rows_b, vm_b, _ = read_collected(COMMENT_DIR)
    seen = set()
    merged: list[dict[str, Any]] = []
    for r in rows_a + rows_b:
        cid = str(r.get("comment_id") or "")
        if cid:
            if cid in seen:
                continue
            seen.add(cid)
        merged.append(r)
    vm = {**vm_a, **vm_b}
    return merged, vm, "全量"


def _build_summary(rows: list[dict[str, Any]], video_map: dict[str, dict[str, Any]], req: AnalyzeRequest) -> str:
    by_vid: Counter[str] = Counter(str(r.get("video_id") or "") for r in rows)
    signals: Counter[str] = Counter()
    target_count = 0
    for r in rows:
        status, signal = classify_comment(str(r.get("content") or "").strip())
        if status == "excluded":
            signals["(排除类)"] += 1
        else:
            signals[signal] += 1
            target_count += 1

    lines = [
        f"评论总数:{len(rows)},涉及视频:{len(by_vid)} 个",
        f"信号分布(目标 {target_count} 条):"
        + "; ".join(f"{k} {v}" for k, v in signals.most_common(10)),
        "",
        "重点视频及其高赞评论:",
    ]
    for vid, n in by_vid.most_common(req.max_videos):
        v = video_map.get(vid, {})
        comments = [r for r in rows if str(r.get("video_id") or "") == vid]
        comments.sort(key=lambda r: int(str(r.get("like_count") or 0) or 0), reverse=True)
        lines.append(f"\n《{str(v.get('title') or vid)[:50]}》({n} 条评论)")
        for c in comments[: req.sample_per_video]:
            lines.append(f"  - (👍{c.get('like_count', 0)}) {str(c.get('content') or '')[:120]}")
    return "\n".join(lines)


def _load_reports() -> list[dict[str, Any]]:
    if not REPORTS_FILE.exists():
        return []
    try:
        return json.loads(REPORTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_reports(items: list[dict[str, Any]]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def _previous_digest(n: int = 3) -> str:
    """最近几份报告的结论摘要,單给 LLM 做融合演进。"""
    reports = _load_reports()[-n:]
    if not reports:
        return ""
    parts = []
    for r in reports:
        themes = ";".join(str(t.get("theme") or "")[:20] for t in (r.get("pain_themes") or [])[:5])
        topics = ";".join(str(t.get("title") or "")[:16] for t in (r.get("topic_hints") or [])[:4])
        parts.append(f"[{r.get('scope')} {time.strftime('%m-%d', time.localtime(r.get('ts', 0)))}] 人群:{str(r.get('audience') or '')[:60]} 痛点:{themes} 选题:{topics}")
    return "\n".join(parts)


@router.get("/reports")
async def list_reports() -> list[dict[str, Any]]:
    """历史报告列表(新→旧,含摘要不含全文)。"""
    return [
        {
            "id": r.get("id"),
            "ts": r.get("ts"),
            "scope": r.get("scope"),
            "total_comments": r.get("total_comments"),
            "total_videos": r.get("total_videos"),
            "audience": str(r.get("audience") or "")[:80],
            "theme_count": len(r.get("pain_themes") or []),
            "topic_count": len(r.get("topic_hints") or []),
            "keywords": r.get("keywords"),
        }
        for r in _load_reports()[::-1]
    ]


@router.get("/reports/{report_id}")
async def get_report(report_id: str) -> dict[str, Any]:
    for r in _load_reports():
        if r.get("id") == report_id:
            return r
    raise HTTPException(status_code=404, detail="报告不存在")


@router.delete("/reports/{report_id}")
async def delete_report(report_id: str) -> dict[str, bool]:
    _save_reports([r for r in _load_reports() if r.get("id") != report_id])
    return {"ok": True}


@router.post("/analyze")
async def analyze(body: AnalyzeRequest) -> dict[str, Any]:
    rows, video_map, scope = _load_rows(body.date)
    if not rows:
        raise HTTPException(status_code=400, detail=f"{scope} 没有评论数据,先去「采集」页爬一批")

    summary = _build_summary(rows, video_map, body)
    digest = _previous_digest()
    if digest:
        summary += f"\n\n【既往报告结论(本次要融合演进,不要复述)】\n{digest}"
    try:
        reply = await complete(
            [
                {"role": "system", "content": ANALYZE_PROMPT},
                {"role": "user", "content": summary},
            ],
            temperature=0.5,
            timeout=180,
            feature="comments.analyze",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 调用失败:{e}") from e

    import re

    m = re.search(r"\{.*\}", reply, re.S)
    parsed: dict[str, Any] = {}
    if m:
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            parsed = {}

    by_vid = Counter(str(r.get("video_id") or "") for r in rows)
    report = {
        "id": uuid.uuid4().hex[:10],
        "ts": time.time(),
        "scope": scope,
        "keywords": body.keywords or "",
        "total_comments": len(rows),
        "total_videos": len(by_vid),
        "top_videos": [
            {"title": str(video_map.get(vid, {}).get("title") or vid)[:60], "comments": n}
            for vid, n in by_vid.most_common(8)
        ],
        "audience": parsed.get("audience", ""),
        "pain_themes": parsed.get("pain_themes", []),
        "reply_opportunities": parsed.get("reply_opportunities", []),
        "topic_hints": parsed.get("topic_hints", []),
        "dos": parsed.get("dos", []),
        "carry_over": str(parsed.get("carry_over") or ""),
        "raw": "" if parsed else reply[:500],
    }
    reports = _load_reports()
    reports.append(report)
    _save_reports(reports)
    return report
