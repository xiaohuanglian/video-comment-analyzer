# -*- coding: utf-8 -*-
"""选题中心 API:从已采集评论里,用评论信号六分类法挖选题。

方法学借鉴 Beav builtin-skills/xhs-comment-insight:
追问/反驳/补充/情绪/行动意图/作者互动 → 收敛成 1 个可写的小选题。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services.llm import complete
from api.services.outreach.reply_automation import BULK_COMMENT_DIR, read_collected

router = APIRouter(prefix="/topics", tags=["topics"])

TOPICS_DIR = Path(__file__).resolve().parents[2] / "data" / "topics"
TOPICS_FILE = TOPICS_DIR / "topics.json"

SIX_SIGNAL_PROMPT = """你是选题挖掘助手。给你 1 条视频的背景和它评论区的摘录,你要从评论里找「读者真正还想知道什么」,收敛成 1 个足够小、能写成一篇图文的选题。

评论信号分六类:
- 追问:用户问"在哪、怎么、为什么、能不能" → 教程、解释、避坑
- 反驳:用户不同意、纠正、质疑 → 观点澄清、争议讨论
- 补充:用户提供案例、事实、资源 → 案例拆解、信息增量
- 情绪:用户表达焦虑、想要、羡慕、害怕 → 共鸣、痛点安抚
- 行动意图:求链接、求模板、求方法、求名单 → 工具清单、步骤
- 作者互动:作者回复承诺、澄清 → 后续承接、FAQ

要求:
- 选题必须来自评论区信号,不是原视频内容摘要
- 切口要小:具体问题、具体场景、具体人群,不要"大家都在问什么"这种大题
- 只输出一个 JSON 对象,不要 Markdown、不要解释:
{"title": "20字以内的选题标题", "signal": "触发选题的评论信号(举例:高赞评论在追问…)", "target_reader": "具体读者", "core_tension": "评论区暴露的矛盾", "angle": "从什么角度写", "material_entry": "素材来源:评论信号+原视频背景", "viral_score": 1-10的整数(爆款潜力:情绪强度+争议性+时效), "evergreen_score": 1-10的整数(长青价值:三个月后还有没有人搜这个问题)}
- 如果用户消息里附了「已有选题清单」,新选题不得与其中的重复或只是换说法;确实没有新角度时,在 title 开头加「(微创新)」并说明差异。
"""

BOOST_PROMPT = """你是视频策划。用户已定一个选题,并给你一批「同方向视频」的评论区摘录(观众夸了什么、骂了什么、还有什么没满足)。
你的任务:整合这些视频的优点、弥补它们的缺点,产出一份「最强视频」打造方案。

输出 JSON(不要 Markdown、不要解释):
{
 "strengths_to_keep": ["竞争对手被夸的点,值得保留的做法", "..."],
 "weaknesses_to_fix": ["评论区暴露的抱怨/未满足需求,我们必须弥补的", "..."],
 "differentiation": "我们的差异化角度(一句话)",
 "outline": [{"chapter": "章节名", "goal": "这一段要达成什么", "borrow": "借鉴了哪个优点", "fix": "弥补了哪个缺点"}],
 "style_advice": "如何融入用户的个人风格"
}
"""

BOOST_VIDEO_PROMPT = """你是顶级视频策划。用户已定一个选题,这个选题做的人不多、但做的人都拿到了成绩。现在给你一批「同类参考」素材——可能包括国内 B 站视频(标题/简介/高赞评论)和国外 YouTube 视频(标题/简介/字幕正文/高赞评论)。

你的任务:博采众长,输出一份可直接开拍的「最强视频」方案。核心原则:
- 吸收每个参考里被验证有效的做法(观众明确夸的、高播放视频的结构)
- 丢掉被观众抱怨的部分(听不懂、没重点、没后续)
- 国外参考里的先进观点/技术/结构,要「翻译」成国内观众能接受的表达,不要照搬腔调
- 若提供了个人风格,全文要带着这个人的味道

输出 JSON(不要 Markdown、不要解释):
{
 "reference_review": [{"source": "参考名", "take": "从它身上学什么/避开什么"}],
 "titles": ["3-5 个备选标题"],
 "script": "完整口播稿正文(钩子→展开→落点,口语化,可直接照读)",
 "why_strong": "这份方案强在哪(3 句以内)"
}
"""


class GenerateRequest(BaseModel):
    video_id: Optional[str] = None  # 不指定则从带评论的视频里挑一个评论多的
    max_comments: int = 40


def _load() -> list[dict[str, Any]]:
    if not TOPICS_FILE.exists():
        return []
    try:
        return json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    TOPICS_FILE.write_text(json.dumps(items[-300:], ensure_ascii=False, indent=1), encoding="utf-8")


def _extract_json(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


@router.get("/list")
async def list_topics(limit: int = 60) -> list[dict[str, Any]]:
    return _load()[-limit:][::-1]


@router.delete("/{topic_id}")
async def delete_topic(topic_id: str) -> dict[str, bool]:
    items = _load()
    _save([t for t in items if t.get("id") != topic_id])
    return {"ok": True}


@router.post("/generate")
async def generate(body: GenerateRequest) -> dict[str, Any]:
    rows, video_map = read_collected(BULK_COMMENT_DIR)
    if not rows:
        raise HTTPException(status_code=400, detail="data/comments 下没有采集数据,先去「采集」页爬一批")

    # 选定目标视频
    if body.video_id:
        vid = body.video_id
    else:
        count_by_video: dict[str, int] = {}
        for r in rows:
            v = str(r.get("video_id") or "")
            count_by_video[v] = count_by_video.get(v, 0) + 1
        if not count_by_video:
            raise HTTPException(status_code=400, detail="采集数据里没有评论")
        vid = max(count_by_video, key=lambda v: count_by_video[v])

    video = video_map.get(vid, {})
    comments = [r for r in rows if str(r.get("video_id") or "") == vid]
    comments.sort(key=lambda r: int(str(r.get("like_count") or 0) or 0), reverse=True)
    excerpt = comments[: max(5, body.max_comments)]
    if not excerpt:
        raise HTTPException(status_code=400, detail=f"视频 {vid} 没有评论")

    comment_text = "\n".join(
        f"- (👍{r.get('like_count', 0)}) {str(r.get('content') or '')[:200]}" for r in excerpt
    )
    existing_titles = [t.get("title", "") for t in _load()[-30:]]
    user_msg = (
        f"原视频标题:{video.get('title') or vid}\n"
        f"原视频简介:{str(video.get('desc') or '')[:300]}\n\n"
        f"评论区摘录(共 {len(comments)} 条,以下是高赞前 {len(excerpt)} 条):\n{comment_text}"
    )
    if existing_titles:
        user_msg += "\n\n已有选题清单(不得重复):\n" + "\n".join(f"- {t}" for t in existing_titles if t)

    try:
        reply = await complete(
            [
                {"role": "system", "content": SIX_SIGNAL_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.6,
            feature="topics.signal",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 调用失败:{e}") from e

    parsed = _extract_json(reply)
    if not parsed or not parsed.get("title"):
        raise HTTPException(status_code=502, detail=f"模型未返回合规 JSON:{reply[:200]}")

    topic = {
        "id": uuid.uuid4().hex[:10],
        "viral_score": int(parsed.get("viral_score") or 0),
        "evergreen_score": int(parsed.get("evergreen_score") or 0),
        "ts": time.time(),
        "video_id": vid,
        "video_title": str(video.get("title") or "")[:80],
        "video_url": str(video.get("video_url") or ""),
        "comment_count": len(comments),
        "title": str(parsed.get("title") or "")[:40],
        "signal": str(parsed.get("signal") or ""),
        "target_reader": str(parsed.get("target_reader") or ""),
        "core_tension": str(parsed.get("core_tension") or ""),
        "angle": str(parsed.get("angle") or ""),
        "material_entry": str(parsed.get("material_entry") or ""),
    }
    items = _load()
    items.append(topic)
    _save(items)
    return topic


PLAN_PROMPT = """你是选题参谋。用户要开一场「选题规划会」——你出主意、用户拍板。严格按以下流程:

1. 先用人话向用户摆盘面(2-4 句):现在选题库覆盖了哪些应用域、哪些还空着、最近已写过什么要避开。
2. 若用户给了种子想法,把每个想法塑成可直接创作的选题(≤25字),标 source=user_seed,并记 origin_note(用户原话精髓)。
3. 依据【真实评论信号】补缺口:从下面给的评论摘录里找真实痛点作为选题依据(标 source=comment_signal,origin_note 引用原评论精髓);用户想法没覆盖的应用域按账号定位补提议(标 source=ai_suggest)。
4. 选题网格要求:应用域铺开(任一域不得超过总量40%)、问题类型多样;每条必须带 application_domain 和 problem_type。
   应用域候选(按账号定位选 5-7 个真实的,可自造更贴切的):{domains_hint}
   问题类型固定:识别(是什么)/盲区(没注意到的)/决策(怎么选)/替代(用什么替代)/反例(反过来的例子)/后果(会怎样)
5. 与【已写标题】和【已有选题】重复或换汤不换药的,不要出;确实相近但角度不同的,在 origin_note 里写明差异。

输出 JSON(不要 Markdown、不要解释):
{
 "board_summary": "盘面摘要(人话,含哪里空着)",
 "topics": [{"title": "≤25字选题", "source": "user_seed|comment_signal|ai_suggest", "application_domain": "应用域", "problem_type": "识别|盲区|决策|替代|反例|后果", "origin_note": "来源:用户想法精髓/评论引用/AI理由", "why": "一句为什么值得写"}]
}
选题数量:8-12 条,种子想法优先全保留。"""


class PlanRequest(BaseModel):
    seed_ideas: str = ""
    max_topics: int = 12


class BatchTopicsRequest(BaseModel):
    topics: list[dict[str, Any]] = []


class BatchDeleteRequest(BaseModel):
    ids: list[str] = []


def _domain_hint() -> str:
    from api.services.strategy import load as load_strategy

    s = load_strategy()
    if s.get("niche"):
        return f"账号定位是「{s['niche']}」,受众「{s.get('target_audience', '')}」,请据此推应用域"
    return "按 youvibe(AI 内容创作工具,目标:想用 AI 做视频/动画/网页的创作者与新手)推应用域"


def _comment_evidence(n: int = 60) -> str:
    """从已采集库里抽高赞评论当真痛点验证源。"""
    rows, video_map = read_collected(BULK_COMMENT_DIR)
    if not rows:
        return "(暂无采集评论,跳过评论验证,靠定位与用户想法)"
    rows.sort(key=lambda r: int(str(r.get("like_count") or 0) or 0), reverse=True)
    lines = []
    for r in rows[:n]:
        v = video_map.get(str(r.get("video_id") or "")) or {}
        title = str(v.get("title") or "")[:24]
        lines.append(f"- (👍{r.get('like_count', 0)}《{title}》){str(r.get('content') or '')[:90]}")
    return "\n".join(lines)


def _drafted_titles() -> list[str]:
    drafts_file = TOPICS_DIR / "drafts.json"
    if not drafts_file.exists():
        return []
    try:
        return [str(d.get("title") or "") for d in json.loads(drafts_file.read_text(encoding="utf-8"))[-10:]][
            ::-1
        ]
    except Exception:
        return []


@router.get("/board")
async def board() -> dict[str, Any]:
    """选题盘面:应用域×问题类型计数 + 查重基线。"""
    items = _load()
    grid: dict[str, dict[str, int]] = {}
    domains: list[str] = []
    types = ["识别", "盲区", "决策", "替代", "反例", "后果"]
    status_count = {"planned": 0, "drafted": 0, "published": 0}
    for t in items:
        d = str(t.get("application_domain") or "未标域")
        p = str(t.get("problem_type") or "未标类")
        grid.setdefault(d, {})[p] = grid.setdefault(d, {}).get(p, 0) + 1
        if d not in domains and d != "未标域":
            domains.append(d)
        st = str(t.get("status") or "planned")
        status_count[st] = status_count.get(st, 0) + 1
    return {
        "total": len(items),
        "domains": domains,
        "problem_types": types,
        "grid": grid,
        "status": status_count,
        "recent_drafts": _drafted_titles(),
        "has_strategy": _domain_hint().startswith("账号定位"),
    }


@router.post("/plan")
async def plan(body: PlanRequest) -> dict[str, Any]:
    """开一场选题规划会:盘面+种子想法+评论验证 → 待拍板选题网格。"""
    items = _load()
    existing = [str(t.get("title") or "") for t in items[-40:]]
    drafted = _drafted_titles()
    b = await board()
    grid_text = " ".join(
        f"{d}:{sum(p.values())}条({','.join(f'{k}{v}' for k, v in p.items())})"
        for d, p in b["grid"].items()
    ) or "(库还空着)"

    user_msg = (
        f"【账号定位】{_domain_hint()}\n\n"
        f"【现有选题盘面】{grid_text};未标应用域 {b['total'] - sum(sum(p.values()) for p in b['grid'].values() if True)} 条\n"
        f"【已有选题(避重复)】{'、'.join(existing) or '无'}\n"
        f"【最近已写标题(避重复)】{'、'.join(drafted) or '无'}\n\n"
    )
    if body.seed_ideas.strip():
        user_msg += f"【用户的种子想法(优先塑成选题)】\n{body.seed_ideas.strip()[:2000]}\n\n"
    user_msg += f"【真实评论信号(高赞摘录,作为真痛点验证源)】\n{_comment_evidence()}"

    try:
        reply = await complete(
            [
                {"role": "system", "content": PLAN_PROMPT.replace("{domains_hint}", _domain_hint())},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.7,
            timeout=180,
            feature="topics.plan",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 调用失败:{e}") from e

    parsed = _extract_json(reply)
    if not parsed or not parsed.get("topics"):
        raise HTTPException(status_code=502, detail=f"模型未返回合规 JSON:{reply[:200]}")
    topics_out = []
    for t in parsed["topics"][: body.max_topics]:
        if not t.get("title"):
            continue
        topics_out.append(
            {
                "title": str(t["title"])[:30],
                "source": str(t.get("source") or "ai_suggest"),
                "application_domain": str(t.get("application_domain") or "未标域"),
                "problem_type": str(t.get("problem_type") or "未标类"),
                "origin_note": str(t.get("origin_note") or "")[:200],
                "why": str(t.get("why") or "")[:100],
            }
        )
    return {"board_summary": str(parsed.get("board_summary") or ""), "topics": topics_out}


@router.post("/batch")
async def batch_add(body: BatchTopicsRequest) -> dict[str, Any]:
    """整批入库(带元数据,重复跳过),入库后剪。"""
    if not body.topics:
        raise HTTPException(status_code=400, detail="没有选题可入库")
    items = _load()
    existing = {str(t.get("title") or "") for t in items}
    inserted = 0
    skipped = []
    for t in body.topics:
        title = str(t.get("title") or "").strip()[:30]
        if not title or title in existing:
            skipped.append(title)
            continue
        existing.add(title)
        items.append(
            {
                "id": uuid.uuid4().hex[:10],
                "ts": time.time(),
                "title": title,
                "source": str(t.get("source") or "ai_suggest"),
                "application_domain": str(t.get("application_domain") or ""),
                "problem_type": str(t.get("problem_type") or ""),
                "origin_note": str(t.get("origin_note") or "")[:200],
                "status": "planned",
            }
        )
        inserted += 1
    _save(items)
    return {"inserted": inserted, "skipped": skipped, "total": len(items)}


@router.post("/batch-delete")
async def batch_delete(body: BatchDeleteRequest) -> dict[str, Any]:
    ids = set(body.ids)
    items = _load()
    _save([t for t in items if t.get("id") not in ids])
    return {"ok": True, "total": len(_load())}


class BoostRequest(BaseModel):
    topic_title: str
    personal_style: str = ""  # 用户的个人风格描述
    max_videos: int = 5


@router.post("/boost")
async def boost(body: BoostRequest) -> dict[str, Any]:
    """「最强视频」:在已采集数据里找同方向视频,整合其优点、弥补其缺点。"""
    if not body.topic_title.strip():
        raise HTTPException(status_code=400, detail="选题不能为空")
    rows, video_map = read_collected(BULK_COMMENT_DIR)
    if not rows:
        raise HTTPException(status_code=400, detail="data/comments 下没有采集数据,先去「采集」页爬一批")

    # 粗匹配:标题与选题有共同关键词的视频
    terms = [t for t in re.split(r"[^\w\u4e00-\u9fff]+", body.topic_title) if len(t) >= 2]
    scored: list[tuple[int, str]] = []
    for vid, v in video_map.items():
        title = str(v.get("title") or "")
        hits = sum(1 for t in terms if t in title)
        if hits:
            scored.append((hits, vid))
    scored.sort(reverse=True)
    picked = scored[: body.max_videos] or sorted(
        ((sum(1 for r in rows if str(r.get("video_id") or "") == vid), vid) for vid in video_map),
        reverse=True,
    )[:3]

    blocks: list[str] = []
    for _, vid in picked:
        v = video_map.get(vid, {})
        comments = [r for r in rows if str(r.get("video_id") or "") == vid]
        comments.sort(key=lambda r: int(str(r.get("like_count") or 0) or 0), reverse=True)
        top = "\n".join(
            f"  - (👍{c.get('like_count', 0)}) {str(c.get('content') or '')[:150]}"
            for c in comments[:15]
        )
        blocks.append(f"视频《{v.get('title') or vid}》\n简介:{str(v.get('desc') or '')[:200]}\n高赞评论:\n{top}")

    user_msg = f"已定选题:{body.topic_title}\n\n同方向视频及其评论区:\n" + "\n\n".join(blocks)
    if body.personal_style:
        user_msg += f"\n\n我的个人风格:{body.personal_style}"

    try:
        reply = await complete(
            [{"role": "system", "content": BOOST_PROMPT}, {"role": "user", "content": user_msg}],
            temperature=0.6,
            feature="topics.boost",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 调用失败:{e}") from e

    parsed = _extract_json(reply)
    if not parsed:
        raise HTTPException(status_code=502, detail=f"模型未返回合规 JSON:{reply[:200]}")
    return {
        "topic_title": body.topic_title,
        "analyzed_videos": [video_map.get(vid, {}).get("title", vid) for _, vid in picked],
        "strengths_to_keep": parsed.get("strengths_to_keep") or [],
        "weaknesses_to_fix": parsed.get("weaknesses_to_fix") or [],
        "differentiation": str(parsed.get("differentiation") or ""),
        "outline": parsed.get("outline") or [],
        "style_advice": str(parsed.get("style_advice") or ""),
    }


class BoostVideoRequest(BaseModel):
    topic_title: str
    competitor_links: list[str] = []
    personal_style: str = ""
    max_bili: int = 4
    auto_search: bool = True  # 自动去 YouTube 搜国外参考


@router.post("/boost-video")
async def boost_video(body: BoostVideoRequest) -> dict[str, Any]:
    """「最强视频」v2:给定选题 + 可选对手链接(B站/YouTube),
    博采国内外众长,产出可直接开拍的完整口播稿。"""
    if not body.topic_title.strip():
        raise HTTPException(status_code=400, detail="选题不能为空")

    from api.services.boost import fetch_link_material, match_collected_videos

    # 1) 自有 B 站采集数据里的同方向视频
    rows, video_map = read_collected(BULK_COMMENT_DIR)
    bili_refs = match_collected_videos(body.topic_title, video_map, rows, body.max_bili)

    # 2) 用户给的对手链接 + 自动 YouTube 搜索(国外先进内容)
    from api.services.boost import search_youtube

    links = [u.strip() for u in body.competitor_links[:6] if u.strip()]
    auto_found: list[dict[str, Any]] = []
    if body.auto_search:
        # LLM 把中文选题翻成英文搜索词,再去 YouTube 找高播放参考
        try:
            en = await complete(
                [
                    {
                        "role": "system",
                        "content": "把用户给的中文选题翻成 1 个最适合在 YouTube 上搜索同类优质视频的英文搜索词组(3-8 个单词)。只输出英文词组,不要解释。",
                    },
                    {"role": "user", "content": body.topic_title},
                ],
                temperature=0.3,
                timeout=30,
                feature="topics.translate",
            )
        except Exception:
            en = ""
        if en:
            candidates = await search_youtube(en.strip(), n=6)
            # 播放量前 2 名抓全量素材(字幕+评论),其余的只留标题进参考
            for c in candidates[:2]:
                links.append(c["url"])
                auto_found.append(c)

    link_materials = []
    for url in links:
        link_materials.append(await fetch_link_material(url))

    if not bili_refs and not any(m.get("subtitle") or m.get("comments") for m in link_materials):
        raise HTTPException(
            status_code=400,
            detail="没有找到可参考的同类内容:已采集库无匹配,外部链接也没抓到素材。可以先去「采集」页爬一批,或贴上 YouTube/B 站链接",
        )

    # 3) 拼素材文本
    blocks: list[str] = []
    for r in bili_refs:
        comments = "\n".join(f"  - (👍{c['likes']}) {c['text']}" for c in r["top_comments"])
        blocks.append(f"【B站】《{r['title']}》\n简介:{r['desc']}\n高赞评论:\n{comments}")
    for m in link_materials:
        if m.get("error"):
            blocks.append(f"【链接】{m.get('url')}:抓取失败 {m['error']}")
            continue
        if m.get("platform") == "youtube":
            comments = "\n".join(f"  - (👍{c['likes']}) {c['text']}" for c in m.get("comments", []))
            sub = (m.get("subtitle") or "")[:4000]
            blocks.append(
                f"【YouTube】《{m.get('title')}》by {m.get('channel')}\n"
                f"简介:{(m.get('description') or '')[:400]}\n"
                f"字幕正文(节选):\n{sub}\n高赞评论:\n{comments}"
            )
        elif m.get("platform") == "bili":
            blocks.append(f"【B站链接】{m.get('url')}({m.get('note', '')})")

    user_msg = f"已定选题:{body.topic_title}\n\n同类参考素材:\n" + "\n\n".join(blocks)
    style_text = body.personal_style.strip()
    if not style_text:
        try:
            from api.services.strategy import tone_summary

            style_text = tone_summary() or ""
        except Exception:
            style_text = ""
    if style_text:
        user_msg += f"\n\n我的个人风格:{style_text}"

    try:
        reply = await complete(
            [{"role": "system", "content": BOOST_VIDEO_PROMPT}, {"role": "user", "content": user_msg}],
            temperature=0.7,
            timeout=180,
            feature="topics.boost_video",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 调用失败:{e}") from e

    parsed = _extract_json(reply)
    if not parsed or not parsed.get("script"):
        raise HTTPException(status_code=502, detail=f"模型未返回合规 JSON:{reply[:200]}")

    return {
        "topic_title": body.topic_title,
        "bili_refs": [r["title"] for r in bili_refs],
        "auto_found": [
            {"title": c["title"], "channel": c["channel"], "view_count": c["view_count"], "url": c["url"]}
            for c in auto_found
        ],
        "link_refs": [
            {"url": m.get("url"), "title": m.get("title") or "", "ok": not m.get("error")}
            for m in link_materials
        ],
        "reference_review": parsed.get("reference_review") or [],
        "titles": parsed.get("titles") or [],
        "script": str(parsed.get("script") or ""),
        "why_strong": str(parsed.get("why_strong") or ""),
    }
