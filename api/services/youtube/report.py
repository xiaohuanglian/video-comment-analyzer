# -*- coding: utf-8 -*-
"""YouTube 评论区报告：对标频道版。

和 B 站报告共用 `data/analysis/reports.json`（同 schema），所以在「历史报告」里
和以前的报告并排放，点开是同一种卡片。

区别在分析口径：这批是**别人的**评论区，目的是找可迁移的选题信号与人群判断，
不是给自己评论区做运营复盘。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
REPORT_DIR = DATA_DIR / "analysis"
REPORTS_FILE = REPORT_DIR / "reports.json"

PROMPT = """你是评论区数据分析专家。给你一批 YouTube **对标创作者**的评论统计与高赞摘录。
目标不是复盘自己的账号，而是：
1) 判断这些频道吸引的是什么人（人群特征、水平阶段、动机）；
2) 找出反复出现的真实痛点 / 需求 / 卡点；
3) 提炼可以直接迁移成我方选题的信号；
4) 识别噪音（求带党、纯情绪、卖课同行），别把噪音当需求。

若提供了【既往报告结论】，必须在其基础上融合演进：延续的标(延续)，变化的更新判断，
新发现的标(新增)，不要原样复述。

报告必须包含(用 JSON 输出,不要 Markdown 代码块):
{
 "audience": "这些评论者是谁(2-3 句话,具体到人群特征和水平阶段;区分不同频道的人群差异)",
 "pain_themes": [{"theme": "痛点/需求主题(延续/新增)", "evidence": "引用 1-2 条典型评论(精简)", "heat": "高/中/低"}],
 "reply_opportunities": [{"target": "值得互动的评论类型", "why": "为什么值得回", "example": "典型评论(精简)"}],
 "topic_hints": [{"title": "20字内选题", "signal": "来自什么评论信号", "score": 1-10}],
 "dos": ["接下来最该做的 3 件事(具体、可执行)"],
 "carry_over": "从既往报告延续下来的关键结论(一句话;无既往则空字符串)"
}
只输出 JSON。"""

CompleteFn = Callable[..., Awaitable[str]]

SIGNAL_RULES = [
    ("求方法", ("how do i", "how to", "how can i", "怎么", "如何")),
    ("求工具", ("what tool", "which tool", "tool", "app", "software", "工具")),
    ("求带", ("mentor", "teach me", "dm me", "带带我", "求带")),
    ("反驳/质疑", ("disagree", "wrong", "nonsense", "actually no")),
    ("共鸣/认同", ("so true", "this is me", "exactly", "100%", "needed this")),
]


def _signal(text: str) -> str:
    lowered = (text or "").lower()
    for label, words in SIGNAL_RULES:
        if any(w in lowered for w in words):
            return label
    return "其他"


def build_summary(
    rows: Sequence[Dict[str, Any]],
    *,
    max_videos: int = 8,
    sample_per_video: int = 8,
) -> str:
    """把 YouTube 评论压成给模型看的统计摘要（纯代码，可测试）。"""
    if not rows:
        return "（没有评论）"

    by_channel: Dict[str, List[Dict[str, Any]]] = {}
    by_video: Dict[str, List[Dict[str, Any]]] = {}
    titles: Dict[str, str] = {}
    for r in rows:
        by_channel.setdefault(str(r.get("channel") or ""), []).append(r)
        vid = str(r.get("video_id") or "")
        by_video.setdefault(vid, []).append(r)
        if vid and r.get("video_title"):
            titles[vid] = str(r["video_title"])

    signals: Dict[str, int] = {}
    authors = set()
    replies = 0
    for r in rows:
        signals[_signal(str(r.get("content") or ""))] = signals.get(_signal(str(r.get("content") or "")), 0) + 1
        if r.get("user_id"):
            authors.add(str(r["user_id"]))
        if r.get("parent_comment_id"):
            replies += 1

    lines = [
        f"评论总数:{len(rows)},涉及频道:{len(by_channel)} 个,视频:{len(by_video)} 个,独立作者:{len(authors)},回复:{replies}",
        "频道分布:" + "; ".join(f"{k} {len(v)}" for k, v in sorted(by_channel.items(), key=lambda kv: -len(kv[1]))),
        "粗信号分布:" + "; ".join(f"{k} {v}" for k, v in sorted(signals.items(), key=lambda kv: -kv[1])[:6]),
        "",
        "各频道最高赞评论:",
    ]
    for channel, items in sorted(by_channel.items(), key=lambda kv: -len(kv[1])):
        top = sorted(items, key=lambda r: -int(r.get("like_count") or 0))[:3]
        lines.append(f"\n【{channel}】共 {len(items)} 条")
        for c in top:
            lines.append(f"  - (👍{c.get('like_count', 0)}) {str(c.get('content') or '')[:110]}")

    lines.append("\n重点视频及其高赞评论:")
    ranked = sorted(by_video.items(), key=lambda kv: -len(kv[1]))[:max_videos]
    for vid, items in ranked:
        items = sorted(items, key=lambda r: -int(r.get("like_count") or 0))
        lines.append(f"\n《{titles.get(vid, vid)[:50]}》({len(items)} 条评论)")
        for c in items[:sample_per_video]:
            lines.append(f"  - (👍{c.get('like_count', 0)}) {str(c.get('content') or '')[:120]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 报告存储（与 B 站报告共用 reports.json）
# ---------------------------------------------------------------------------

def load_reports() -> List[Dict[str, Any]]:
    if not REPORTS_FILE.exists():
        return []
    try:
        data = json.loads(REPORTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_reports(items: Sequence[Dict[str, Any]]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_FILE.write_text(json.dumps(list(items), ensure_ascii=False, indent=1), encoding="utf-8")


def append_report(report: Dict[str, Any]) -> None:
    items = load_reports()
    items.append(report)
    save_reports(items)


def previous_digest(n: int = 3) -> str:
    reports = [r for r in load_reports() if str(r.get("scope", "")).startswith("YouTube")]
    reports = reports[-n:]
    if not reports:
        return ""
    parts = []
    for r in reports:
        themes = ";".join(str(t.get("theme") or "")[:20] for t in (r.get("pain_themes") or [])[:5])
        topics = ";".join(str(t.get("title") or "")[:16] for t in (r.get("topic_hints") or [])[:4])
        parts.append(f"[{r.get('scope')}] 人群:{str(r.get('audience') or '')[:60]} 痛点:{themes} 选题:{topics}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


async def analyze(
    rows: Sequence[Dict[str, Any]],
    *,
    scope: str,
    keywords: str = "",
    max_videos: int = 8,
    sample_per_video: int = 8,
    complete_fn: Optional[CompleteFn] = None,
) -> Dict[str, Any]:
    if not rows:
        raise ValueError("没有可分析的评论")
    if complete_fn is None:
        from api.services.llm import complete as complete_fn  # type: ignore[assignment]

    summary = build_summary(rows, max_videos=max_videos, sample_per_video=sample_per_video)
    user = f"数据范围：{scope}\n采集关键词：{keywords or '（未填）'}\n\n{summary}"
    digest = previous_digest()
    if digest:
        user += f"\n\n【既往报告结论】\n{digest}"

    reply = await complete_fn(
        [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
        feature="youtube.comment_report",
    )
    parsed = _extract_json(reply)

    channels: Dict[str, int] = {}
    videos: Dict[str, int] = {}
    titles: Dict[str, str] = {}
    for r in rows:
        channels[str(r.get("channel") or "")] = channels.get(str(r.get("channel") or ""), 0) + 1
        vid = str(r.get("video_id") or "")
        videos[vid] = videos.get(vid, 0) + 1
        if vid and r.get("video_title"):
            titles[vid] = str(r["video_title"])

    report: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:10],
        "ts": time.time(),
        "scope": scope,
        "keywords": keywords,
        "total_comments": len(rows),
        "total_videos": len(videos),
        "channels": dict(sorted(channels.items(), key=lambda kv: -kv[1])),
        "top_videos": [
            {"title": titles.get(vid, vid)[:80], "comments": n}
            for vid, n in sorted(videos.items(), key=lambda kv: -kv[1])[:10]
        ],
        "audience": str(parsed.get("audience") or ""),
        "pain_themes": parsed.get("pain_themes") or [],
        "reply_opportunities": parsed.get("reply_opportunities") or [],
        "topic_hints": parsed.get("topic_hints") or [],
        "dos": parsed.get("dos") or [],
        "carry_over": str(parsed.get("carry_over") or ""),
    }
    if not parsed:
        report["raw"] = reply[:4000]
    append_report(report)
    return report
