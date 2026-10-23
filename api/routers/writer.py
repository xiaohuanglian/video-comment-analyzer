# -*- coding: utf-8 -*-
"""文案生成 API:选题 → 图文稿 / 口播稿,持久化历史。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services.llm import complete

router = APIRouter(prefix="/writer", tags=["writer"])

DRAFTS_DIR = Path(__file__).resolve().parents[2] / "data" / "topics"
DRAFTS_FILE = DRAFTS_DIR / "drafts.json"

PROMPTS = {
    "xhs": (
        "你是小红书图文写手。根据给定选题写一篇可直接发布的图文稿。"
        "要求:标题 20 字以内、有钩子;正文口语化、分段短、适当 emoji;"
        "结构:痛点引入 → 干货/步骤 → 真实感细节 → 结尾互动引导;"
        "全文 400-700 字;末尾给 5-8 个话题标签。"
        "输出 JSON:{\"title\": \"...\", \"body\": \"...\", \"tags\": [\"...\"]}"
        "只输出 JSON,不要解释。"
    ),
    "koubo": (
        "你是短视频口播编剧。根据给定选题写 60-90 秒口播稿。"
        "要求:前 3 秒钩子;全程口语、短句、有节奏;"
        "结构:钩子 → 痛点放大 → 方法/观点 → 一个具体例子 → 行动指令;"
        "全文 250-400 字。"
        "输出 JSON:{\"title\": \"...\", \"body\": \"...\", \"shots\": [\"分镜建议1\", \"...\"]}"
        "只输出 JSON,不要解释。"
    ),
}


SKELETON_STYLES = {
    "checklist": "清单体/方法论:干货步骤清单,每条有具体做法,2000-4000字",
    "review": "个人实测推荐:亲身使用视角,有真实细节和踩坑,4000-7000字",
    "contrarian": "认知颠覆/观点文:反常识论点,递进论证,2000-3500字",
    "story": "故事化/情感共鸣:人物故事驱动,2500-4500字",
}

PROMPTS["skeleton"] = (
    """你是长文骨架写手。根据选题搭建文章骨架(不是成文)。
要求:先给 3-5 个备选标题(痛点明确/数字吸引/结果导向/情绪调动/悬念);
再按指定体裁搭分章节结构,每章写清:本节论点、需要的素材类型、递进关系;
核心论述处标注「此处需作者填真实经历/数据」,绝不编造虚假经历。
输出 JSON:{"titles": ["..."], "structure": [{"chapter": "...", "point": "...", "material": "..."}], "style_note": "..."}
只输出 JSON。"""
)

HUMANIZE_PROMPT = (
    """你是挑剔的中文文字编辑,专门去 AI 味。规则:
1. 保留原文全部事实、数字、观点、不确定度;不新增任何信息
2. 干掉:空泛铺垫、「不仅...更是」「不是...而是」假对比、机械排比(三项以上同构)、「综上所述」「不难发现」「值得注意的是」、假大空升华结尾
3. 保留作者的声音:第一人称、犹豫、口语;不为了短句把连贯文字拆成提纲
4. 没问题的段落原样保留,不为显得有工作量硬改
输出 JSON:{"body": "改写后全文", "changes": ["改动说明1", "..."]}(changes 最多 5 条)。只输出 JSON。"""
)


class WriteRequest(BaseModel):
    topic_title: str
    topic_context: str = ""  # 选题卡里的 signal/tension/angle 拼进来
    format: Literal["xhs", "koubo", "skeleton"] = "xhs"
    style: str = "checklist"  # 仅 skeleton 用:checklist/review/contrarian/story
    personal_style: str = ""  # 口吻;缺省取账号策略档案


class HumanizeRequest(BaseModel):
    text: str


def _load() -> list[dict[str, Any]]:
    if not DRAFTS_FILE.exists():
        return []
    try:
        return json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    DRAFTS_FILE.write_text(json.dumps(items[-300:], ensure_ascii=False, indent=1), encoding="utf-8")


@router.get("/list")
async def list_drafts(limit: int = 60) -> list[dict[str, Any]]:
    return _load()[-limit:][::-1]


@router.delete("/{draft_id}")
async def delete_draft(draft_id: str) -> dict[str, bool]:
    _save([d for d in _load() if d.get("id") != draft_id])
    return {"ok": True}


@router.post("/generate")
async def generate(body: WriteRequest) -> dict[str, Any]:
    if not body.topic_title.strip():
        raise HTTPException(status_code=400, detail="选题不能为空")
    user_msg = f"选题:{body.topic_title}\n"
    if body.topic_context:
        user_msg += f"背景:{body.topic_context}\n"
    if body.format == "skeleton":
        user_msg += f"体裁:{SKELETON_STYLES.get(body.style, SKELETON_STYLES['checklist'])}\n"
    # 口吻:手输优先,缺省取策略档案
    style_text = body.personal_style.strip()
    if not style_text:
        try:
            from api.services.strategy import tone_summary

            style_text = tone_summary() or ""
        except Exception:
            style_text = ""
    if style_text:
        user_msg += f"\n作者口吻(全文带这个味道,不搬其中事实):\n{style_text}\n"
    # 查重基线:最近已写标题,防换汤不换药
    try:
        drafts = json.loads((DRAFTS_FILE).read_text(encoding="utf-8"))
        recent = [str(d.get("title") or "") for d in drafts[-10:]][::-1]
    except Exception:
        recent = []
    if recent:
        user_msg += f"\n(查重:以下是最近已写过的标题,不要重复或换汤不换药:{';'.join(recent)})\n"
    try:
        reply = await complete(
            [
                {"role": "system", "content": PROMPTS[body.format]},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.8,
            feature="writer",
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

    if body.format == "skeleton":
        titles = parsed.get("titles") or []
        structure = parsed.get("structure") or []
        body_text = "\n".join(
            [f"备选标题:\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles)), ""]
            + [
                f"【{c.get('chapter', f'第{i + 1}节')}】{c.get('point', '')}\n  素材:{c.get('material', '')}"
                for i, c in enumerate(structure)
            ]
        )
    else:
        body_text = str(parsed.get("body") or reply)
    draft = {
        "id": uuid.uuid4().hex[:10],
        "ts": time.time(),
        "format": body.format,
        "style": body.style if body.format == "skeleton" else "",
        "topic_title": body.topic_title,
        "title": str(parsed.get("title") or (parsed.get("titles") or [body.topic_title])[0]),
        "body": body_text,
        "tags": parsed.get("tags") or [],
        "shots": parsed.get("shots") or [],
    }
    items = _load()
    items.append(draft)
    _save(items)
    return draft


@router.post("/humanize")
async def humanize(body: HumanizeRequest) -> dict[str, Any]:
    """去 AI 味润色(humanizer-zh 方法学):保留事实与作者声音,只杀模板腔。"""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    if len(text) > 6000:
        raise HTTPException(status_code=400, detail="文本过长(>6000 字),请分段处理")
    try:
        reply = await complete(
            [
                {"role": "system", "content": HUMANIZE_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.4,
            feature="writer.humanize",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 调用失败:{e}") from e
    import re

    m = re.search(r"\{.*\}", reply, re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
            return {
                "body": str(parsed.get("body") or text),
                "changes": parsed.get("changes") or [],
            }
        except json.JSONDecodeError:
            pass
    return {"body": reply, "changes": []}
