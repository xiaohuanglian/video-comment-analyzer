# -*- coding: utf-8 -*-
"""Content plan: turn comment insights into ranked content topics + AI drafts.

Two layers:
1. Code-owned topic extraction — every topic carries real demand counts and
   traceable evidence refs (never model-invented numbers).
2. Optional LLM drafting — writes title/angle/outline/draft per topic using the
   project profile's persona, and is explicitly *not* auto-published.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from .llm_analyzer import LlmUsage, build_openai_client, estimate_cost, parse_usage
from .project_profiles import ProjectProfile, resolve_profile
from .storage import (
    load_config,
    load_research_analysis,
    load_semantic_review,
    load_themes,
)

CONTENT_PLAN_VERSION = "content_plan_v1"

CONTENT_SYSTEM_PROMPT = """你是资深内容策略师。你会拿到一个主题的真实用户需求与证据，产出可在社交/搜索平台发布的内容方案。

严格规则：
- 只用输入中给出的证据，不得编造数据、案例或疗效。
- 标题要贴合用户真实提问的措辞（利于搜索），但不做标题党、不夸大。
- 内容必须真正回答该问题，先给价值，不硬广、不导流。
- 涉及健康/医疗/金融等高风险领域时，不做诊断或收益承诺。
- 只输出单行紧凑 JSON，禁止额外解释。"""


def _build_content_user_message(topic: dict, profile: ProjectProfile) -> str:
    payload = {
        "persona": profile.content_persona or "专业、真诚、以解决问题为导向。",
        "platforms": profile.content_platforms or ["短视频", "图文", "长文", "工具页"],
        "forbidden_claims": profile.forbidden_claims,
        "research_goal": profile.research_goal,
        "target_audience": profile.target_audience,
        "topic": {
            "topic_id": topic.get("topic_id"),
            "theme_name": topic.get("theme_name"),
            "theme_definition": topic.get("theme_definition"),
            "source_question": topic.get("source_question"),
            "demand_users": topic.get("demand_users"),
            "demand_comments": topic.get("demand_comments"),
            "example_quotes": (topic.get("example_quotes") or [])[:5],
        },
        "output_schema": {
            "topic_id": "",
            "title": "推荐标题（贴合用户提问措辞）",
            "content_angle": "这条内容要切入的角度/给谁看/解决什么",
            "keywords": ["搜索关键词/话题标签"],
            "outline": ["要点1", "要点2", "要点3"],
            "draft_format": "短视频脚本|图文|长文",
            "draft": "一版可直接编辑的内容草稿（短视频给分镜脚本）",
            "limitations": "这版内容不能声称什么",
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class ContentTopic(BaseModel):
    topic_id: str
    rank: int = 0
    title: str = ""
    source_question: str = ""
    theme_name: str = ""
    theme_definition: str = ""
    content_angle: str = ""
    target_platforms: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    outline: List[str] = Field(default_factory=list)
    draft: str = ""
    draft_format: str = "短视频脚本"
    demand_users: int = 0
    demand_comments: int = 0
    example_quotes: List[str] = Field(default_factory=list)
    evidence_refs: List[dict] = Field(default_factory=list)
    limitations: str = ""
    generated: bool = False


class ContentPlanDocument(BaseModel):
    version: str = CONTENT_PLAN_VERSION
    run_id: str = ""
    profile_id: str = ""
    profile_name: str = ""
    generator: str = "code"
    model_name: str = ""
    created_at: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    currency: str = "CNY"
    summary: str = ""
    topics: List[ContentTopic] = Field(default_factory=list)


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}")
_STOPWORDS = {
    "的", "了", "吗", "呢", "吧", "啊", "呀", "我", "你", "他", "她", "它",
    "我们", "你们", "他们", "这个", "那个", "怎么", "是否", "一个个", "一个",
}


def _keywords_from(text: str, limit: int = 6) -> List[str]:
    """Extract search-friendly keywords (jieba when available)."""
    if not text:
        return []
    try:
        import jieba

        tokens = jieba.lcut(text)
    except Exception:  # noqa: BLE001 — jieba optional/failure fallback
        tokens = _TOKEN_RE.findall(text)
    seen: List[str] = []
    for token in tokens:
        token = str(token).strip()
        if len(token) < 2 or token in _STOPWORDS:
            continue
        if token not in seen:
            seen.append(token)
        if len(seen) >= limit:
            break
    return seen


def _open_theme_rows(run_id: str) -> List[dict]:
    review = load_semantic_review(run_id)
    rows = review.get("open_themes") or []
    return [row for row in rows if isinstance(row, dict)]


def _theme_candidates(run_id: str) -> List[dict]:
    """Merge open themes / themes document / research themes into a flat list."""
    candidates: List[dict] = []

    for row in _open_theme_rows(run_id):
        candidates.append(
            {
                "theme_name": str(row.get("theme_name") or row.get("name") or "").strip(),
                "theme_definition": str(row.get("definition") or row.get("theme_definition") or "").strip(),
                "implication": str(row.get("implication") or "").strip(),
                "record_ids": list(row.get("record_ids") or row.get("comment_record_ids") or []),
                "comment_count": int(row.get("comment_count") or 0),
                "unique_user_count": int(row.get("unique_user_count") or 0),
                "quotes": list(row.get("representative_quotes") or [])[:5],
                "evidence_refs": list(row.get("representative_evidence_refs") or []),
            }
        )

    if not candidates:
        doc = load_themes(run_id)
        for theme in getattr(doc, "themes", []) or []:
            stats = getattr(theme, "stats", None)
            candidates.append(
                {
                    "theme_name": str(getattr(theme, "theme_name", "") or "").strip(),
                    "theme_definition": str(getattr(theme, "definition", "") or "").strip(),
                    "implication": str(getattr(theme, "implication", "") or "").strip(),
                    "record_ids": list(getattr(theme, "record_ids", []) or []),
                    "comment_count": int(getattr(stats, "comment_count", 0) or 0),
                    "unique_user_count": int(getattr(stats, "unique_user_count", 0) or 0),
                    "quotes": list(getattr(theme, "representative_quotes", []) or [])[:5],
                    "evidence_refs": [],
                }
            )

    if not candidates:
        research = load_research_analysis(run_id)
        for theme in research.get("themes") or []:
            if not isinstance(theme, dict):
                continue
            ids = theme.get("comment_record_ids") or theme.get("record_ids") or []
            candidates.append(
                {
                    "theme_name": str(theme.get("theme_name") or "").strip(),
                    "theme_definition": str(
                        theme.get("theme_definition") or theme.get("definition") or ""
                    ).strip(),
                    "implication": str(theme.get("implication") or "").strip(),
                    "record_ids": list(ids),
                    "comment_count": int(theme.get("comment_count") or len(ids)),
                    "unique_user_count": int(theme.get("unique_user_count") or 0),
                    "quotes": list(theme.get("representative_quotes") or [])[:5],
                    "evidence_refs": list(theme.get("representative_evidence_refs") or []),
                }
            )
    return candidates


def build_content_topics(
    run_id: str,
    *,
    profile: Optional[ProjectProfile] = None,
    max_topics: int = 12,
) -> List[ContentTopic]:
    """Deterministic, code-counted topics ranked by real demand."""
    profile = profile or resolve_profile(load_config(run_id))
    noise = [m.lower() for m in (profile.noise_markers or [])]

    rows = _theme_candidates(run_id)
    scored: List[dict] = []
    for row in rows:
        name = row["theme_name"]
        if not name or len(name) < 2:
            continue
        text = f"{name} {row['theme_definition']}".lower()
        count = row["comment_count"] or len(row["record_ids"])
        if any(marker and marker in text for marker in noise):
            continue
        if count <= 0:
            continue
        scored.append(row)

    scored.sort(
        key=lambda r: (r["unique_user_count"], r["comment_count"] or len(r["record_ids"])),
        reverse=True,
    )

    topics: List[ContentTopic] = []
    for index, row in enumerate(scored[: max(1, max_topics)], start=1):
        quotes = [q for q in row["quotes"] if isinstance(q, str) and q.strip()][:5]
        source_question = quotes[0] if quotes else row["theme_definition"]
        topics.append(
            ContentTopic(
                topic_id=f"T{index}",
                rank=index,
                title=row["theme_name"],
                source_question=source_question,
                theme_name=row["theme_name"],
                theme_definition=row["theme_definition"],
                content_angle=row["implication"] or row["theme_definition"],
                target_platforms=list(profile.content_platforms or ["短视频", "图文", "长文", "工具页"]),
                keywords=_keywords_from(f"{row['theme_name']} {row['theme_definition']}"),
                demand_users=row["unique_user_count"],
                demand_comments=row["comment_count"] or len(row["record_ids"]),
                example_quotes=quotes,
                evidence_refs=[
                    ref for ref in row["evidence_refs"] if isinstance(ref, dict)
                ][:8],
            )
        )
    return topics


def _mock_draft(topic: ContentTopic, profile: ProjectProfile) -> dict:
    angle = topic.content_angle or topic.theme_definition or topic.theme_name
    return {
        "topic_id": topic.topic_id,
        "title": f"{topic.theme_name}｜{topic.source_question[:24]}".strip("｜"),
        "content_angle": angle,
        "keywords": topic.keywords[:5],
        "outline": [
            f"用户真实问题：{topic.source_question[:40]}",
            f"给出可执行答案（对应主题：{topic.theme_name}）",
            "一句话总结 + 引导下一步（不硬广）",
        ],
        "draft_format": (topic.target_platforms[0] if topic.target_platforms else "短视频脚本"),
        "draft": (
            f"【开头 3 秒】你是不是也遇到过：{topic.source_question[:30]}？\n"
            f"【正文】围绕「{topic.theme_name}」给出 2-3 个具体做法。\n"
            f"【结尾】如果你也有类似问题，评论区告诉我具体场景。\n"
            f"（草稿由 mock 生成，仅用于流程验证。）"
        ),
        "limitations": "该内容仅基于评论信号，不能承诺具体效果。",
    }


def _parse_drafts(content: str) -> List[dict]:
    text = (content or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        for key in ("topics", "items", "drafts", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def generate_content_drafts(
    topics: List[ContentTopic],
    *,
    config=None,
    api_key: str = "",
    profile: Optional[ProjectProfile] = None,
    use_mock: bool = False,
    max_topics: int = 5,
) -> tuple[int, int, int, float]:
    """Fill title/angle/outline/draft for the top topics. Returns usage stats."""
    profile = profile or resolve_profile(config)
    targets = topics[: max(0, max_topics)]
    if not targets:
        return 0, 0, 0, 0.0

    if use_mock or not api_key or config is None:
        for topic in targets:
            draft = _mock_draft(topic, profile)
            topic.title = draft["title"]
            topic.content_angle = draft["content_angle"]
            topic.keywords = draft["keywords"]
            topic.outline = draft["outline"]
            topic.draft_format = draft["draft_format"]
            topic.draft = draft["draft"]
            topic.limitations = draft["limitations"]
            topic.generated = True
        return 0, 0, 0, 0.0

    client = build_openai_client(config.base_url, api_key)
    usage = LlmUsage()
    total_cost = 0.0
    for topic in targets:
        messages = [
            {"role": "system", "content": CONTENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_content_user_message(topic.model_dump(), profile),
            },
        ]
        completion = client.chat.completions.create(
            model=config.model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        content = completion.choices[0].message.content or ""
        parsed = _parse_drafts(content)
        draft = parsed[0] if parsed else {}
        if draft:
            topic.title = str(draft.get("title") or topic.title)
            topic.content_angle = str(draft.get("content_angle") or topic.content_angle)
            keywords = draft.get("keywords")
            if isinstance(keywords, list):
                topic.keywords = [str(k) for k in keywords][:8]
            outline = draft.get("outline")
            if isinstance(outline, list):
                topic.outline = [str(o) for o in outline][:8]
            topic.draft_format = str(draft.get("draft_format") or topic.draft_format)
            topic.draft = str(draft.get("draft") or "")
            topic.limitations = str(draft.get("limitations") or topic.limitations)
            topic.generated = True
        step = parse_usage(completion)
        usage.prompt_tokens += step.prompt_tokens
        usage.completion_tokens += step.completion_tokens
        usage.prompt_cache_hit_tokens += step.prompt_cache_hit_tokens
        total_cost += estimate_cost(
            step.prompt_tokens,
            step.completion_tokens,
            input_price=config.input_price,
            output_price=config.output_price,
        )
    return (
        usage.prompt_tokens,
        usage.completion_tokens,
        usage.prompt_cache_hit_tokens,
        total_cost,
    )


def build_content_plan(
    run_id: str,
    *,
    use_mock: bool = False,
    api_key: str = "",
    max_topics: int = 12,
    draft_topics: int = 5,
) -> ContentPlanDocument:
    config = load_config(run_id)
    profile = resolve_profile(config)
    topics = build_content_topics(run_id, profile=profile, max_topics=max_topics)

    prompt_tokens = completion_tokens = cache_hit = 0
    cost = 0.0
    generator = "code"
    if topics and draft_topics > 0:
        prompt_tokens, completion_tokens, cache_hit, cost = generate_content_drafts(
            topics,
            config=config,
            api_key=api_key,
            profile=profile,
            use_mock=use_mock or not api_key,
            max_topics=draft_topics,
        )
        generator = "code+llm(mock)" if (use_mock or not api_key) else "code+llm"

    total_users = sum(t.demand_users for t in topics)
    summary = (
        f"共提取 {len(topics)} 个内容选题；覆盖信号合计 {total_users} 名用户。"
        "选题来自真实评论需求（代码统计），草稿由 AI 生成，需人工审核后发布。"
    )
    return ContentPlanDocument(
        run_id=run_id,
        profile_id=profile.profile_id,
        profile_name=profile.name,
        generator=generator,
        model_name=config.model_name if generator != "code" else "",
        created_at=datetime.now(timezone.utc).isoformat(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost=cost,
        currency=config.currency,
        summary=summary,
        topics=topics,
    )


def content_plan_markdown(doc: ContentPlanDocument) -> str:
    lines = [
        f"# 内容选题与生成 · {doc.profile_name or doc.run_id}",
        "",
        f"- 生成方式：{doc.generator}",
        f"- 选题数：{len(doc.topics)}",
        f"- {doc.summary}",
        "",
        "> 说明：数据来自评论信号（代码统计），草稿由 AI 生成，**需人工审核后再发布**；请遵守平台规则，不做硬广与虚假承诺。",
        "",
    ]
    for topic in doc.topics:
        lines.append(f"## {topic.rank}. {topic.title}")
        lines.append("")
        lines.append(f"- **用户真实问题**：{topic.source_question or '—'}")
        lines.append(f"- **需求规模**：{topic.demand_users} 名用户 / {topic.demand_comments} 条评论")
        if topic.keywords:
            lines.append(f"- **关键词/话题**：{'、'.join(topic.keywords)}")
        if topic.content_angle:
            lines.append(f"- **内容角度**：{topic.content_angle}")
        if topic.outline:
            lines.append("- **要点**：")
            lines.extend([f"  - {item}" for item in topic.outline])
        if topic.example_quotes:
            lines.append("- **原话引用**：")
            lines.extend([f"  - 「{quote}」" for quote in topic.example_quotes])
        if topic.draft:
            lines.append("")
            lines.append(f"**草稿（{topic.draft_format}）**：")
            lines.append("")
            lines.append("```")
            lines.append(topic.draft)
            lines.append("```")
        if topic.limitations:
            lines.append(f"- **限制**：{topic.limitations}")
        lines.append("")
    return "\n".join(lines)