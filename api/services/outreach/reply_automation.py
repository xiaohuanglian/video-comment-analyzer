# -*- coding: utf-8 -*-
"""B 站评论区回复自动化引擎。

流程：定时采集 → 产品需要人群筛选 → LLM 起草 → 风格 lint → 人工批准（UI）→ 受控发送。

红线（不变）：机器只采集、筛选、起草；**发送必须经人工批准**，批准动作只发生在 UI。
状态持久化在 data/automation/bili_reply.json，Web 服务重启后自动续跑。

筛选规则来源（2026-10-12/13 与用户共同定稿）：
- 目标 = 产品需要人群：问工具/怎么做（看得到学不会）、新手自述（想动手缺路径）
- 排除：使用渠道类（GPT/Claude 怎么用上）、变现类、个案报错（需验证）、
  求 skill/知识库等 UP 主私有资源（漏斗礼让）、指向 UP 本人创作的导演式提问、
  AI 水评、垃圾广告
- 新鲜度：A 档 ≤48h 优先，B 档 ≤7 天，超龄跳过
- 节流：同视频每天最多 1 条候选，单周期上限可配
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .reply_style import check_reply_style

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STORE_PATH = PROJECT_ROOT / "data" / "automation" / "bili_reply.json"
COMMENT_DIR = PROJECT_ROOT / "data" / "automation" / "comments"
COOKIE_PATH = PROJECT_ROOT / "data" / "automation" / "bili_cookie.json"
BILI_PROFILE_DIR = PROJECT_ROOT / "browser_data" / "cdp_bili_user_data_dir"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "keywords": ["AI视频", "AI教程", "AI实测", "可灵", "提示词", "AI修图"],
    "collect_interval_hours": 6,
    "max_notes_per_keyword": 20,  # B 站搜索按页 20 条，代码里低于 20 会被抬到 20
    "max_comments_per_video": 100,
    "collect_timeout_minutes": 100,
    "freshness_a_hours": 48,
    "freshness_b_hours": 168,
    "max_new_candidates_per_cycle": 8,
    "max_per_video_per_day": 1,
    "daily_send_limit": 10,
    "send_interval_seconds": 180,
    "send_jitter_seconds": 240,
    "send_window_start": "09:00",
    "send_window_end": "22:00",
    "auto_draft": True,
    "llm_screen": True,
    "llm_screen_threshold": 6,
}

# ---------------------------------------------------------------------------
# 筛选规则（与 docs/回复待审清单 及记分卡标准一致）
# ---------------------------------------------------------------------------

_RE_SPAM = re.compile(r"成品号|出售|低价出|代充|加[vV薇微]|微信号|带赚|稳赚|项目私|求关注|免费(分享|领取)|私我|滴滴")
# 使用渠道类（用户规则：不碰）
_RE_ACCESS = re.compile(
    r"用上|怎么用gpt|怎么用claude|如何用gpt|注册|翻墙|科学上网|镜像|账号|会员|充值|买.{0,4}号|"
    r"支付|报销|订阅|低价pro|直充|封了|封号|中转"
)
# 变现类（无标准答案）
_RE_MONETIZE = re.compile(r"变现|赚钱|副业|盈利|接单|商单|怎么赚|搞钱|风口|回本")
# 个案报错/调试（需个案验证，规则排除）
_RE_DEBUG = re.compile(
    r"报错|错误|崩了|闪退|无法|检测不到|安装失败|装不上|黑屏|白屏|内存不足|跑不动|"
    r"加载器|工作流.{0,6}(失败|不行)|一直(卡|转|等)"
)
# 求 UP 主私有资源（漏斗礼让：自动化一律不碰，人工可加）
_RE_RESOURCE_BEG = re.compile(
    r"求skill|求知识库|求资源|求资料|球球skill|三连.{0,10}求|已?三连.{0,8}(求|蹲)|"
    r"求(提示词|模板|打包|整合包|参数文档|操作手册)|蹲一波|求发|求分享|需要.{0,4}(skill|知识库|资料)"
)
# 导演式提问（问 UP 本人的做法/素材/参数——只有 UP 能答；不拦「您好/请您」这类礼貌用语）
_RE_DIRECTOR = re.compile(r"您的|你的|你(这|那)个|up你|楼主你|老师你|k神|ksr桑")
# AI 水评（B 站流行的 AI 生成总结式评论）
_RE_AI_WATER = re.compile(r"值得琢磨|值得深思|这道选择题|也挺直观|从某种角度|某种意义|确实也")
# 感叹/纯情绪（无提问内容）
_RE_EXCLAIM = re.compile(
    r"^(好的|谢谢|感谢|厉害|绝了|哇|牛|冲|收藏了|mark|马克|支持|好看|太|确实|哈哈|笑死|"
    r"打卡|前排|来了|222|hhh|666|顶|赞)[!！。～~\s]*$|^\d+$"
)

# 反问/抒情/赞叹(纯修辞,无观点内容;「还要什么自行车」等习语常见于实质观点中,不再拦)
_RE_RHETORIC = re.compile(r"没人(夸|说|提|注意)|我从没觉得|多愁善感|破防|泪目|哭死")
# A 档：看得到学不会（问工具/怎么做）
_RE_HOWTO = re.compile(
    r"什么(软件|工具|app|模型|程序|网站)|哪个(软件|工具|app|平台)|"
    r"怎么(做|弄|用|生成|实现|做到|衔接|设置|入门|开始|学)|如何(做|用|实现|生成|入门)|"
    r"用什么|求(教|指导|推荐)|怎么做同款|怎么才能"
)
# B 档：想动手缺路径（新手自述，需带提问感）
_RE_NEWBIE = re.compile(r"新手|小白|零基础|入坑|萌新|手残|想学|想试|我也想|入门")
_RE_QUESTION_CUE = re.compile(r"？|\?|吗|呢|什么|怎么|哪|求|请教|能不能|有没有")
# 求助动词（弱疑问必须同时命中，否则视为现后讨论）
_RE_SEEKING = re.compile(
    r"想学|想做|想试|想用|想了解|想知道|好奇|请教|请问|求教|求助|打算|想上手|想入|"
    r"能不能|可不可以|有没有办法|怎么才能|能实现|能做"
)
# C 档：AI 相关实体（观点/讨论评论的召回判据；边界防误伤 said/hair 等）
_RE_AI_ENTITY = re.compile(
    r"(?<![a-zA-Z])[aA][iI](?![a-zA-Z])|人工智能|大模型|llm|智能体|agent|生成式|"
    r"gpt|claude|gemini|opus|astra|deepseek|sora|veo|"
    r"可灵|即梦|seedance|千问|qwen|豆包|智谱|nano banana|"
    r"提示词|数字人|ai视频|ai动画|ai修图|ai绘图|ai画|ai配音|ai生成",
    re.IGNORECASE,
)


# 营销号昵称(卖号/代充/接单工作室——评论再像样也不值得回)
_RE_SPAM_NICK = re.compile(r"订阅|可开票|低价|代充|出号|回收|接单|工作室|招商|代理")


def classify_comment(text: str) -> tuple[str, str]:
    """返回 (状态, 信号标签)。状态：target_a / target_b / excluded。"""
    text = (text or "").strip()
    if len(text) < 8:
        return "excluded", "太短"
    for pat, label in (
        (_RE_SPAM, "垃圾广告"),
        (_RE_ACCESS, "使用渠道类"),
        (_RE_MONETIZE, "变现类"),
        (_RE_DEBUG, "个案报错"),
        (_RE_RESOURCE_BEG, "求UP私有资源"),
        (_RE_DIRECTOR, "导演式提问"),
        (_RE_RHETORIC, "反问/抒情"),
        (_RE_AI_WATER, "AI水评"),
        (_RE_EXCLAIM, "纯感叹"),
    ):
        if pat.search(text):
            return "excluded", label
    if _RE_HOWTO.search(text):
        return "target_a", "问工具/怎么做"
    if _RE_NEWBIE.search(text) and _RE_QUESTION_CUE.search(text):
        return "target_b", "新手求路径"
    if (
        _RE_QUESTION_CUE.search(text)
        and _RE_SEEKING.search(text)
        and re.search(r"提示词|skill|软件|工具|模型|视频|动画|修图|配音", text)
    ):
        # 弱疑问 + 明确求助意图 + 实体词，交给人工闸门细看
        # (实体表已去掉 数学/学习/笔记——离域提问由 LLM 精筛判 lane=skip 拦下)
        return "target_b", "想动手求路径"
    if len(text) >= 12 and _RE_AI_ENTITY.search(text):
        # C 档:AI 相关且有实质内容的观点/体验/讨论——不求助也值得互动接话
        return "target_c", "AI相关观点/讨论"
    return "excluded", "无提问"


# ---------------------------------------------------------------------------
# 状态存储
# ---------------------------------------------------------------------------

class AutomationStore:
    """自动化状态：config + 候选队列 + 已处理评论 + 统计。JSON 持久化。"""

    def __init__(self, path: Path = STORE_PATH):
        self.path = path
        self.lock = asyncio.Lock()
        self._state: dict[str, Any] = self._load()

    # ---- 持久化 ----
    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        else:
            data = {}
        state = {
            "config": {**DEFAULT_CONFIG, **(data.get("config") or {})},
            "items": data.get("items") or [],
            "processed_comment_ids": set(data.get("processed_comment_ids") or []),
            "stats": data.get("stats")
            or {
                "cycles": 0,
                "collected_videos": 0,
                "collected_comments": 0,
                "excluded": 0,
                "candidates_total": 0,
                "sent_total": 0,
            },
            "cycle": data.get("cycle")
            or {"running": False, "last_run_at": "", "last_summary": "", "last_error": ""},
            "sender": data.get("sender")
            or {"last_send_at": "", "next_allowed_at": "", "today": "", "sent_today": 0, "last_error": "", "last_error_at": ""},
        }
        return state

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "config": self._state["config"],
            "items": self._state["items"],
            "processed_comment_ids": sorted(self._state["processed_comment_ids"]),
            "stats": self._state["stats"],
            "cycle": self._state["cycle"],
            "sender": self._state["sender"],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ---- 访问 ----
    @property
    def config(self) -> dict[str, Any]:
        return self._state["config"]

    @property
    def items(self) -> list[dict[str, Any]]:
        return self._state["items"]

    def update_config(self, partial: dict[str, Any]) -> dict[str, Any]:
        cfg = self._state["config"]
        for key in ("keywords",):
            if key in partial:
                val = partial[key]
                if isinstance(val, str):
                    val = [k.strip() for k in re.split(r"[，,]", val) if k.strip()]
                cfg[key] = [str(k) for k in (val or [])][:20]
        for key in (
            "collect_interval_hours", "max_notes_per_keyword", "max_comments_per_video",
            "collect_timeout_minutes", "freshness_a_hours", "freshness_b_hours",
            "max_new_candidates_per_cycle", "max_per_video_per_day", "daily_send_limit",
            "send_interval_seconds", "send_jitter_seconds", "llm_screen_threshold",
        ):
            if key in partial:
                try:
                    cfg[key] = max(1, int(partial[key]))
                except (TypeError, ValueError):
                    continue
        for key in ("send_window_start", "send_window_end"):
            if key in partial:
                val = str(partial[key] or "").strip()
                if re.fullmatch(r"\d{1,2}:\d{2}", val):
                    cfg[key] = val
        for key in ("enabled", "auto_draft", "llm_screen"):
            if key in partial:
                cfg[key] = bool(partial[key])
        self.save()
        return cfg

    # ---- 候选 ----
    def add_items(self, new_items: list[dict[str, Any]]) -> int:
        added = 0
        for it in new_items:
            self._state["processed_comment_ids"].add(it["comment_id"])
            self._state["items"].append(it)
            added += 1
        self._state["stats"]["candidates_total"] += added
        self.save()
        return added

    def find(self, item_id: str) -> Optional[dict[str, Any]]:
        for it in self._state["items"]:
            if it["id"] == item_id:
                return it
        return None

    def by_status(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        out = [it for it in self._state["items"] if it["status"] == status]
        return out[-limit:]

    def bulk_reject_rules_screened(self) -> int:
        """拒绝全部「非 LLM 精筛」的待审条目(旧规则筛遗留),返回数量。"""
        n = 0
        for it in list(self._state["items"]):
            if it.get("status") == "pending_review" and it.get("screened_by") != "llm":
                if self.decide(it["id"], "reject"):
                    n += 1
        return n

    def bulk_approve_llm_screened(self) -> tuple[int, int]:
        """批量批准全部 LLM 精筛且已有草稿的待审条目。返回 (批准数, 跳过数[无草稿])。"""
        approved = skipped = 0
        for it in list(self._state["items"]):
            if it.get("status") != "pending_review" or it.get("screened_by") != "llm":
                continue
            if not (it.get("draft") or "").strip():
                skipped += 1
                continue
            if self.decide(it["id"], "approve"):
                approved += 1
        return approved, skipped

    def decide(self, item_id: str, action: str, draft: str = "") -> Optional[dict[str, Any]]:
        it = self.find(item_id)
        if not it or it["status"] != "pending_review":
            return None
        if action == "approve":
            final = (draft or it.get("draft") or "").strip()
            if not final:
                return None
            it["draft"] = final
            it["lint_warnings"] = check_reply_style(final)
            it["status"] = "approved"
            it["decided_at"] = datetime.now().isoformat(timespec="seconds")
        elif action == "reject":
            it["status"] = "rejected"
            it["decided_at"] = datetime.now().isoformat(timespec="seconds")
        else:
            return None
        self.save()
        return it

    def retract(self, item_id: str) -> Optional[dict[str, Any]]:
        """已批准的条目撤回到待审（可改草稿后重新批准）。"""
        it = self.find(item_id)
        if not it or it["status"] != "approved":
            return None
        it["status"] = "pending_review"
        it["decided_at"] = ""
        self.save()
        return it

    def update_draft(self, item_id: str, draft: str, source: str = "manual") -> Optional[dict[str, Any]]:
        it = self.find(item_id)
        if not it or it["status"] not in ("pending_review",):
            return None
        it["draft"] = (draft or "").strip()
        it["lint_warnings"] = check_reply_style(it["draft"])
        it["draft_source"] = source
        self.save()
        return it

    def next_approved(self) -> Optional[dict[str, Any]]:
        for it in self._state["items"]:
            if it["status"] == "approved":
                return it
        return None

    # ---- 发送侧 ----
    def sender_state(self) -> dict[str, Any]:
        return self._state["sender"]

    def _roll_daily(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        s = self._state["sender"]
        if s.get("today") != today:
            s["today"] = today
            s["sent_today"] = 0

    def can_send_now(self, now: Optional[datetime] = None) -> tuple[bool, str]:
        now = now or datetime.now()
        self._roll_daily()
        s = self._state["sender"]
        if not self._state["config"]["enabled"]:
            return False, "自动化未启用"
        start = _hm(self._state["config"]["send_window_start"], 9 * 60)
        end = _hm(self._state["config"]["send_window_end"], 22 * 60)
        cur = now.hour * 60 + now.minute
        if not (start <= cur < end):
            return False, f"发送窗口外（{self._state['config']['send_window_start']}-{self._state['config']['send_window_end']}）"
        if s.get("sent_today", 0) >= self._state["config"]["daily_send_limit"]:
            return False, "今日已达发送上限"
        nxt = s.get("next_allowed_at") or ""
        if nxt:
            try:
                if datetime.fromisoformat(nxt) > now:
                    return False, "节奏等待中"
            except ValueError:
                pass
        return True, ""

    def mark_sending(self, item: dict[str, Any]) -> None:
        item["status"] = "sending"
        self.save()

    def mark_sent(self, item: dict[str, Any], reply_id: str) -> None:
        item["status"] = "sent"
        item["sent_at"] = datetime.now().isoformat(timespec="seconds")
        item["reply_id"] = str(reply_id or "")
        self._state["stats"]["sent_total"] += 1
        s = self._state["sender"]
        s["last_send_at"] = item["sent_at"]
        interval = self._state["config"]["send_interval_seconds"]
        jitter = self._state["config"]["send_jitter_seconds"]
        s["next_allowed_at"] = (
            datetime.now() + timedelta(seconds=interval + random.uniform(0, jitter))
        ).isoformat(timespec="seconds")
        self._roll_daily()
        s["sent_today"] = s.get("sent_today", 0) + 1
        self.save()

    def mark_failed(self, item: dict[str, Any], error: str, retry_status: str = "approved") -> None:
        # 永久性错误不重试：等级不足/该评论不可回复/需绑手机——重试也不会成功
        permanent = re.search(r"等级不足|不可回复|绑定手机|评论不存在|已被删除", str(error))
        item["send_error"] = str(error)[:300]
        item["attempts"] = int(item.get("attempts") or 0) + 1
        if permanent or item["attempts"] >= 3:
            item["status"] = "failed"
        else:
            item["status"] = retry_status
        # 失败后退避 10 分钟再试，避免连续撞风控
        self._state["sender"]["next_allowed_at"] = (
            datetime.now() + timedelta(minutes=10)
        ).isoformat(timespec="seconds")
        self.save()


def _hm(value: str, default: int) -> int:
    try:
        hh, mm = str(value).split(":", 1)
        return max(0, min(23, int(hh))) * 60 + max(0, min(59, int(mm)))
    except (ValueError, AttributeError):
        return default


# ---------------------------------------------------------------------------
# 候选构建（纯函数，可测）
# ---------------------------------------------------------------------------

def _lk(row: dict[str, Any]) -> int:
    try:
        return int(str(row.get("like_count") or 0) or 0)
    except (TypeError, ValueError):
        return 0


def build_candidates(
    comment_rows: list[dict[str, Any]],
    video_map: dict[str, dict[str, Any]],
    config: dict[str, Any],
    processed_ids: set[str],
    now: Optional[datetime] = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """从采集行里筛出候选。返回 (候选列表, 漏斗统计)。"""
    now = now or datetime.now()
    funnel = {"comments": 0, "excluded": 0, "stale": 0, "dedup": 0, "candidates": 0}
    quota_left = max(1, int(config.get("max_new_candidates_per_cycle", 8)))
    video_today: dict[str, str] = {}
    today = now.strftime("%Y-%m-%d")
    for it in config.get("_items_today", []):  # 由调用方注入：今天已入队的视频
        video_today[str(it.get("video_id"))] = today

    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in sorted(comment_rows, key=_lk, reverse=True):
        funnel["comments"] += 1
        cid = str(row.get("comment_id") or "")
        if not cid or cid in seen:
            funnel["dedup"] += 1
            continue
        seen.add(cid)
        if cid in processed_ids:
            funnel["dedup"] += 1
            continue
        nickname = str(row.get("nickname") or "")
        if _RE_SPAM_NICK.search(nickname):
            funnel["excluded"] += 1
            continue  # 营销号昵称:卖订阅/代充/接单,评论再像样也不回
        text = str(row.get("content") or "").strip()
        status, signal = classify_comment(text)
        if status == "excluded":
            funnel["excluded"] += 1
            continue
        lane = "help" if status in ("target_a", "target_b") else "engage"
        try:
            ts = int(row.get("create_time") or 0)
        except (TypeError, ValueError):
            ts = 0
        if not ts:
            funnel["stale"] += 1
            continue
        age_hours = max(0.0, (now.timestamp() - ts) / 3600)
        if age_hours > float(config.get("freshness_b_hours", 168)):
            funnel["stale"] += 1
            continue
        tier = "A" if age_hours <= float(config.get("freshness_a_hours", 48)) else "B"
        vid = str(row.get("video_id") or "")
        if vid in video_today and video_today[vid] == today:
            continue  # 同视频每天最多 1 条
        if quota_left <= 0:
            break
        video = video_map.get(vid, {})
        picked.append(
            {
                "id": f"c_{cid}",
                "comment_id": cid,
                "video_id": vid,
                "video_title": str(video.get("title") or "")[:80],
                "video_url": str(video.get("video_url") or ""),
                "commenter": str(row.get("nickname") or ""),
                "comment_text": text[:500],
                "like_count": _lk(row),
                "age_hours": round(age_hours, 1),
                "signal": signal,
                "tier": tier,
                "lane": lane,
                "worth": 0,
                "intent": "",
                "match_reason": signal,
                "screened_by": "rules",
                "draft": "",
                "lint_warnings": [],
                "draft_source": "",
                "status": "pending_review",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "decided_at": "",
                "sent_at": "",
                "send_error": "",
                "reply_id": "",
                "attempts": 0,
                "note": "",
            }
        )
        video_today[vid] = today
        quota_left -= 1
        funnel["candidates"] += 1
    return picked, funnel


# ---------------------------------------------------------------------------
# LLM 语义精筛(规则粗筛管召回,这里管精度:对齐账号定位,只留值得回复的人)
# ---------------------------------------------------------------------------

_DEFAULT_NICHE = "用 AI 做视频/动画/图片内容的实战教程,只讲能落地的做法"
_DEFAULT_AUDIENCE = "想自己动手用 AI 做内容(视频/动画/图)的新手和创作者"

LLM_SCREEN_PROMPT = """你是B站评论区「值得回复的人」的精筛助手。回复名额有限,只留给值得回复的人。

我们是谁:{niche}
目标受众:{audience}

值得回复的人分两类(lane):
- help(帮助型):被困在我们能答的域里——AI 内容创作(视频/动画/图片/配音)的做法、路径、工具选型。特征:具体问题、真实被困、我们能给全答案。备考/学术研究/生活问题等离域求助不是 help。
- engage(互动型):对 AI 话题发表真实观点/看法/体验的评论——惊叹、怀疑、预测、吐槽、经验分享、讨论。特征:有内容可接话,我们自然回应能延续对话、攒账号信用。看热闹式纯情绪("太强了""泪目")没内容可接,不是 engage。

一律不选(skip):纯水(666/哈哈哈/打卡)、AI生成水评、纯礼貌夸up、引战抬杠、和我们域无关的求助、购买渠道/账号充值/变现赚钱/个案报错调试、求UP主私有资源。

评论信号分型(选最贴近的一个,填进 intent):
求工具/求推荐 | 求做法/路径 | 痛点吐槽求解决 | 对比纠结 | 观点/预测 | 经验分享 | 吐槽/怀疑 | 讨论闲聊 | 求UP主专属 | 离域求助

打分 worth(0-10 整数):
- help:具体问题×真实被困×我们能给全答案,三者越齐分越高
- engage:观点有内容×能自然接话,能延续对话的吐槽/预测/体验分享高分,纯情绪低分

输入给你评论原文和所在视频标题。只输出一个 JSON 对象,不要输出其他文字:
{{"lane": "help|engage|skip", "intent": "信号类型", "worth": 0-10, "reason": "一句话理由,给人工审核看,说清为什么值得或不值得"}}
"""


class LlmScreenUnavailable(RuntimeError):
    """LLM 精筛整体不可用(未配置/网关不通),调用方应降级为纯规则模式。"""


def _screen_brief() -> str:
    """账号定位注入精筛 prompt(策略档案优先,无档案用默认定位)。"""
    try:
        from api.services import strategy as _strategy

        s = _strategy.load() or {}
    except Exception:  # noqa: BLE001
        s = {}
    niche = str(s.get("niche") or "").strip() or _DEFAULT_NICHE
    audience = str(s.get("target_audience") or "").strip() or _DEFAULT_AUDIENCE
    return LLM_SCREEN_PROMPT.format(niche=niche, audience=audience)


def _extract_screen_json(reply: str) -> Optional[dict[str, Any]]:
    text = (reply or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def llm_screen_candidates(
    picked: list[dict[str, Any]],
    threshold: int = 6,
    complete_fn: Optional[Any] = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """对粗筛候选逐条 LLM 语义评分,只留值得回复的。

    返回 (保留列表[worth 降序], 统计 {screened, kept, llm_failed})。
    条目更新字段:worth / intent / match_reason / screened_by。
    未配置网关或首条即网络失败 → 抛 LlmScreenUnavailable(整体降级);
    单条回复解析失败 → 按规则结果保留并标记。
    """
    if complete_fn is None:
        from api.services.llm import complete as complete_fn  # type: ignore[no-redef]
    system_prompt = _screen_brief()
    stats = {"screened": 0, "kept": 0, "llm_failed": 0}
    kept: list[dict[str, Any]] = []
    first = True
    for item in picked:
        user_msg = json.dumps(
            {"视频标题": item.get("video_title", ""), "评论原文": item.get("comment_text", "")},
            ensure_ascii=False,
        )
        try:
            reply = await complete_fn(
                [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}],
                temperature=0.1,
                timeout=60,
                feature="automation.screen",
            )
            data = _extract_screen_json(reply)
            if not data:
                raise ValueError("模型未返回合规 JSON")
        except RuntimeError:
            # 未配置等基础设施错误 → 整体降级
            raise LlmScreenUnavailable("LLM 网关未配置") from None
        except Exception as e:  # noqa: BLE001
            if first:
                # 首条就失败大概率网关不通,不再逐条空等超时
                raise LlmScreenUnavailable(str(e)[:100]) from e
            stats["llm_failed"] += 1
            item["screened_by"] = "rules"
            item["match_reason"] = f"{item.get('signal', '')}(LLM判读失败,按规则保留)"
            kept.append(item)
            first = False
            continue
        first = False
        stats["screened"] += 1
        try:
            worth = max(0, min(10, int(data.get("worth") or 0)))
        except (TypeError, ValueError):
            worth = 0
        lane = str(data.get("lane") or "skip").strip().lower()
        if lane not in ("help", "engage"):
            lane = "skip"
        item["lane"] = lane
        item["worth"] = worth
        item["intent"] = str(data.get("intent") or "")[:20]
        item["screened_by"] = "llm"
        item["match_reason"] = str(data.get("reason") or "")[:120] or item.get("signal", "")
        if lane in ("help", "engage") and worth >= threshold:
            stats["kept"] += 1
            kept.append(item)
    # 帮助型优先于互动型,同 lane 内按分数、赞数降序
    kept.sort(
        key=lambda x: (
            0 if x.get("lane") == "help" else 1,
            -(x.get("worth") or 0),
            -(x.get("like_count") or 0),
        )
    )
    return kept, stats


async def _refine_candidates(
    picked: list[dict[str, Any]], cfg: dict[str, Any], max_candidates: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """LLM 精筛包装:不可用则降级规则模式(候选全保留、标记 screened_by=rules)。"""
    if not picked:
        return picked, {"mode": "none", "screened": 0, "kept": 0, "llm_failed": 0}
    if not cfg.get("llm_screen", True):
        return picked, {"mode": "rules", "note": "llm_screen 已关闭", "screened": 0, "kept": len(picked), "llm_failed": 0}
    try:
        threshold = max(1, min(10, int(cfg.get("llm_screen_threshold", 6))))
        kept, stats = await llm_screen_candidates(picked, threshold=threshold)
        return kept[: max(1, int(max_candidates))], {"mode": "llm", **stats}
    except LlmScreenUnavailable as e:
        note = f"LLM精筛不可用({str(e)[:80]}),已按规则模式入队"
        for it in picked:
            it["match_reason"] = f"{it.get('signal', '')}(精筛降级)"
        return picked, {"mode": "rules", "note": note, "screened": 0, "kept": len(picked), "llm_failed": 0}


# ---------------------------------------------------------------------------
# LLM 起草
# ---------------------------------------------------------------------------

BILI_AUTO_SYSTEM_PROMPT = """为B站评论区一位具体用户起草公开回复（只输出正文，40-160中文字）。
对方是被AI内容吸引、想自己动手做但缺路径的用户。回复的目标：把答案直接给全，给对方带来便利。

写法：
- 开头直接回应他问的事，步骤、工具、参数给全；不指路、不让对方自己去翻去找
- 平等口吻，像朋友帮忙，不像老师教学生；东西难找就归因于入口设计，不说对方
- 白话打底，写完事情就停，不追加"希望有帮助"式尾巴

硬禁令：
- 不出现任何产品名、下载、链接、App、网址、关注我、私信我
- 不用破折号；冒号只能用来引直接原话
- 禁"不是…而是…"翻案句式；禁居高临下（其实很简单/再找找看/别急着放弃）
- 禁黑话（赋能/闭环/底层逻辑/码住/建议收藏/值得关注）
- 不编造不确定的事实；没有十足把握就不提自己的主页或作品"""

BILI_ENGAGE_SYSTEM_PROMPT = """为B站评论区一位具体用户起草公开回复（只输出正文，30-120中文字）。
对方发表了对 AI 的看法/体验/吐槽，不是在求助。目标：自然接话，像评论区里一个懂行的路人，延续对话、攒账号信用。

写法：
- 先接住对方的具体观点再回应：认可哪点、补充一点，或有不一致就温和说出来
- 带一句自己的实际经验或反例，具体到工具/参数/场景，不空对空
- 平等口吻，对观点不对人，不说教不纠正人
- 结尾可自然抛回一个小问题或补充，让对话能继续

硬禁令：
- 不出现任何产品名、下载、链接、App、网址、关注我、私信我
- 不用破折号；冒号只能用来引直接原话
- 禁"不是…而是…"翻案句式；禁居高临下（其实很简单/再找找看/别急着放弃）
- 禁黑话（赋能/闭环/底层逻辑/码住/建议收藏/值得关注）
- 不编造事实；没把握的经验不说"""


def _system_prompt_for(item: dict[str, Any]) -> str:
    return (
        BILI_ENGAGE_SYSTEM_PROMPT
        if item.get("lane") == "engage"
        else BILI_AUTO_SYSTEM_PROMPT
    )


def _llm_user_message(item: dict[str, Any]) -> str:
    return "起草评论区回复：\n" + json.dumps(
        {
            "回复类型": "帮助型(给全答案)" if item.get("lane", "help") == "help" else "互动型(自然接话)",
            "对方评论": item["comment_text"],
            "视频标题": item["video_title"],
            "信号": item.get("intent") or item["signal"],
            "入选理由": item.get("match_reason", ""),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def draft_with_llm(item: dict[str, Any]) -> str:
    """用服务端已保存的模型配置起草；未配置返回空串（留给人工起草）。"""
    from api.services.growth.model_settings import load_model_settings
    from api.services.insight.llm_analyzer import build_openai_client

    settings = load_model_settings()
    if not (settings.get("api_key") or "").strip():
        return ""
    client = build_openai_client(settings.get("base_url", ""), settings["api_key"], feature="reply_draft")

    # 注入账号策略档案口吻(与硬禁令冲突时以硬禁令为准);按 lane 选话术
    system_prompt = _system_prompt_for(item)
    try:
        from api.services.strategy import tone_summary

        tone = tone_summary()
        if tone:
            system_prompt += f"\n\n作者口吻参考(与上方硬禁令冲突时,以硬禁令为准):\n{tone}"
    except Exception:
        pass

    def _call() -> str:
        last_finish = ""
        for max_tokens in (2000, 6000):
            completion = client.chat.completions.create(
                model=settings.get("model_name") or "deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": _llm_user_message(item)},
                ],
                temperature=0.7,
                # 推理型模型会先在 reasoning_content 里消耗 token，
                # 上限太小会导致正文尚未生成就被 length 截断（content=None）
                max_tokens=max_tokens,
            )
            content = (completion.choices[0].message.content or "").strip()
            last_finish = completion.choices[0].finish_reason or ""
            if content:
                return content
        if last_finish == "length":
            raise RuntimeError("推理 token 耗尽仍未出正文")
        return ""

    try:
        return await asyncio.to_thread(_call)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 采集子进程 + 数据读取
# ---------------------------------------------------------------------------

def build_collect_command(config: dict[str, Any]) -> list[str]:
    keywords = ",".join(config.get("keywords") or [])
    return [
        "uv", "run", "python", "main.py",
        "--platform", "bili",
        "--lt", "qrcode",
        "--type", "search",
        "--keywords", keywords,
        "--crawler_max_notes_count", str(config.get("max_notes_per_keyword", 20)),
        "--max_comments_count_singlenotes", str(config.get("max_comments_per_video", 100)),
        "--get_comment", "true",
        "--get_sub_comment", "false",
        "--save_data_option", "jsonl",
        "--save_data_path", str(COMMENT_DIR.relative_to(PROJECT_ROOT)),
        "--headless", "false",
    ]


def read_collected(comment_dir: Path = COMMENT_DIR) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """读自动化目录下全部 contents/comments jsonl（跨周期追加，靠 comment_id 去重）。"""
    video_map: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    if not comment_dir.exists():
        return rows, video_map
    for path in sorted(comment_dir.glob("contents_*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    v = json.loads(line)
                    video_map[str(v.get("video_id"))] = v
        except (json.JSONDecodeError, OSError):
            continue
    for path in sorted(comment_dir.glob("comments_*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            continue
    return rows, video_map


BULK_COMMENT_DIR = PROJECT_ROOT / "data" / "comments"


async def screen_collected(
    store: AutomationStore,
    max_candidates: int = 50,
    auto_draft: bool = True,
    source_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """从手动批量采集的数据(data/comments)里筛目标用户并起草。

    与 run_cycle 的区别:不自己跑采集器,只消费已经爬回来的存量数据。
    流程:读存量 jsonl → 同一套筛选规则 → LLM 起草 → 入队待批准。
    """
    if store._state["cycle"].get("running"):
        return {"ok": False, "error": "有任务正在运行,稍后再试"}
    store._state["cycle"]["running"] = True
    store._state["cycle"]["last_error"] = ""
    store.save()
    try:
        rows, video_map = read_collected(source_dir or BULK_COMMENT_DIR)
        if not rows:
            return {"ok": False, "error": f"{(source_dir or BULK_COMMENT_DIR)} 下没有采集数据,先用「评论采集」面板爬一批"}
        cfg = dict(store.config)
        # 粗筛放大 3 倍(封顶 36)给 LLM 精筛挑选,最终仍按 max_candidates 截断
        cfg["max_new_candidates_per_cycle"] = max(1, min(int(max_candidates) * 3, 36))
        today = datetime.now().strftime("%Y-%m-%d")
        cfg["_items_today"] = [
            it for it in store.items if str(it.get("created_at", "")).startswith(today)
        ]
        picked, funnel = build_candidates(
            rows, video_map, cfg, store._state["processed_comment_ids"]
        )
        picked, screen_stats = await _refine_candidates(picked, cfg, max_candidates)
        picked = picked[: max(1, int(max_candidates))]

        drafted = 0
        if auto_draft:
            for item in picked:
                draft = await draft_with_llm(item)
                if draft:
                    item["draft"] = draft
                    item["lint_warnings"] = check_reply_style(draft)
                    item["draft_source"] = "llm"
                    drafted += 1

        added = store.add_items(picked)
        summary = {
            "ok": True,
            "source": str(source_dir or BULK_COMMENT_DIR),
            "videos": len(video_map),
            "comments": len(rows),
            "funnel": funnel,
            "llm_screen": screen_stats,
            "new_candidates": added,
            "llm_drafted": drafted,
        }
        store._state["cycle"]["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        store._state["cycle"]["last_summary"] = json.dumps(summary, ensure_ascii=False)
        store.save()
        return summary
    except Exception as exc:  # noqa: BLE001
        store._state["cycle"]["last_error"] = str(exc)[:300]
        store.save()
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        store._state["cycle"]["running"] = False
        store.save()


async def run_cycle(store: AutomationStore) -> dict[str, Any]:
    """跑一个完整周期：采集 → 读取 → 筛选 → 起草 → 入队。"""
    if store._state["cycle"].get("running"):
        return {"ok": False, "error": "已有采集周期在运行"}
    store._state["cycle"]["running"] = True
    store._state["cycle"]["last_error"] = ""
    store.save()
    try:
        cmd = build_collect_command(store.config)
        env = {**os.environ, "CDP_CONNECT_EXISTING": "0", "PYTHONUNBUFFERED": "1"}
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        timeout = int(store.config.get("collect_timeout_minutes", 100)) * 60
        try:
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"采集超时（>{timeout // 60}分钟），已终止")

        rows, video_map = read_collected()
        cfg = dict(store.config)
        cfg["_items_today"] = [it for it in store.items if it["created_at"].startswith(datetime.now().strftime("%Y-%m-%d"))]
        picked, funnel = build_candidates(rows, video_map, cfg, store._state["processed_comment_ids"])
        quota = int(store.config.get("max_new_candidates_per_cycle", 8))
        picked, screen_stats = await _refine_candidates(picked, cfg, quota)
        picked = picked[:quota]

        drafted = 0
        if store.config.get("auto_draft", True):
            for item in picked:
                draft = await draft_with_llm(item)
                if draft:
                    item["draft"] = draft
                    item["lint_warnings"] = check_reply_style(draft)
                    item["draft_source"] = "llm"
                    drafted += 1

        added = store.add_items(picked)
        stats = store._state["stats"]
        stats["cycles"] += 1
        stats["collected_videos"] = len(video_map)
        stats["collected_comments"] = len(rows)
        stats["excluded"] += funnel["excluded"]
        summary = {
            "ok": True,
            "videos": len(video_map),
            "comments": len(rows),
            "funnel": funnel,
            "llm_screen": screen_stats,
            "new_candidates": added,
            "llm_drafted": drafted,
        }
        store._state["cycle"]["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        store._state["cycle"]["last_summary"] = json.dumps(summary, ensure_ascii=False)
        store.save()

        # 数据飞轮：采集后自动刷新受众洞察（画像×生命周期×AVS → 机会库，幂等）
        # 失败不影响回复主流程；可用 config.audience_refresh=false 关闭
        if store.config.get("audience_refresh", True):
            try:
                from api.services.growth import audience as _audience

                summary["audience_refresh"] = _audience.refresh_default(
                    product_id=str(store.config.get("audience_product_id", "youvibe"))
                )
            except Exception as exc:  # noqa: BLE001
                summary["audience_refresh"] = {"ok": False, "error": str(exc)[:200]}
            store._state["cycle"]["last_summary"] = json.dumps(summary, ensure_ascii=False)
            store.save()
        return summary
    except Exception as exc:  # noqa: BLE001
        store._state["cycle"]["last_error"] = str(exc)[:300]
        store.save()
        return {"ok": False, "error": str(exc)[:300]}
    finally:
        store._state["cycle"]["running"] = False
        store.save()


# ---------------------------------------------------------------------------
# B 站 Cookie（发送用）
# ---------------------------------------------------------------------------

def _cached_cookie() -> str:
    """返回未过期的缓存 Cookie，无则空串。"""
    if COOKIE_PATH.exists():
        try:
            data = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(data.get("fetched_at", ""))
            if datetime.now() - fetched < timedelta(hours=20) and data.get("cookie"):
                return data["cookie"]
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    return ""


async def ensure_bili_cookie(max_age_hours: float = 20.0) -> str:
    """取缓存的 B 站 Cookie；过期或缺失时从 cdp_bili 档案刷新。"""
    cached = _cached_cookie()
    if cached:
        return cached
    return await refresh_bili_cookie()


def _find_chromium_executable() -> Optional[str]:
    """解析浏览器二进制。优先系统 Chrome/Edge（与 tools.browser_launcher 的采集器
    同一选择，同一 profile 必须始终用同一二进制打开，否则 Cookie 加密密钥
    不匹配会导致登录态被作废——2026-10-13 的真实教训），否则回退
    ms-playwright 缓存里的 Chrome for Testing。"""
    for path in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ):
        if Path(path).is_file():
            return path
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not cache.exists():
        return None
    candidates: list[tuple[str, str]] = []
    for chromium_dir in cache.glob("chromium-*"):
        for app in chromium_dir.glob("chrome-mac*/"):
            for rel in (
                "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                "Chromium.app/Contents/MacOS/Chromium",
            ):
                binary = app / rel
                if binary.exists():
                    candidates.append((chromium_dir.name, str(binary)))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


async def login_bili_qrcode(wait_seconds: int = 180) -> dict[str, Any]:
    """打开可见的 B 站档案浏览器让用户扫码登录;成功后刷新 Cookie 落盘。

    与 refresh_bili_cookie 同用 BILI_PROFILE_DIR 持久档案:扫码后登录态留在档案里,
    后续 headless 刷新都能读到。超时/未扫码抛错。
    """
    import time as _time

    from playwright.async_api import async_playwright

    launch_kwargs: dict[str, Any] = {
        "user_data_dir": str(BILI_PROFILE_DIR),
        "headless": False,  # 必须可见:用户要扫二维码
        "args": ["--no-first-run", "--no-default-browser-check"],
    }
    executable = _find_chromium_executable()
    if executable:
        launch_kwargs["executable_path"] = executable
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(**launch_kwargs)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://www.bilibili.com", wait_until="domcontentloaded", timeout=30000)
            deadline = _time.monotonic() + max(60, int(wait_seconds))
            logged_in = False
            while _time.monotonic() < deadline:
                cookies = await context.cookies("https://www.bilibili.com")
                if any(c.get("name") == "bili_jct" and c.get("value") for c in cookies):
                    logged_in = True
                    break
                await asyncio.sleep(2)
        finally:
            await context.close()
    if not logged_in:
        raise RuntimeError("等待扫码超时,登录未完成(可重试)")
    cookie = await refresh_bili_cookie()  # 复用:headless 读档案+落盘+账号信息
    return {"ok": True, "account": cached_account_info()}


async def refresh_bili_cookie() -> str:
    """启动 cdp_bili 档案浏览器抓一次 Cookie（含 bili_jct 才算有效），顺带记录登录账号信息（防扫错号）。"""
    from playwright.async_api import async_playwright

    launch_kwargs: dict[str, Any] = {
        "user_data_dir": str(BILI_PROFILE_DIR),
        "headless": True,
        "args": ["--no-first-run", "--no-default-browser-check"],
    }
    executable = _find_chromium_executable()
    if executable:
        launch_kwargs["executable_path"] = executable
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(**launch_kwargs)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://www.bilibili.com", wait_until="domcontentloaded", timeout=30000)
            cookies = await context.cookies("https://www.bilibili.com")
        finally:
            await context.close()
    pairs = [f"{c['name']}={c['value']}" for c in cookies if c.get("name") and c.get("value")]
    cookie = "; ".join(pairs)
    if "bili_jct=" not in cookie:
        raise RuntimeError("B 站登录态失效（Cookie 缺少 bili_jct）：请先手动跑一次 B 站采集扫码登录")
    # 顺带取登录账号信息（昵称/等级），监工台展示，防止扫错号
    account = await asyncio.to_thread(_fetch_account_info, cookie)
    COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_PATH.write_text(
        json.dumps(
            {
                "cookie": cookie,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
                "account": account,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return cookie


def _fetch_account_info(cookie: str) -> dict[str, Any]:
    """用 Cookie 调 nav 接口取当前登录账号昵称与等级。"""
    try:
        import httpx

        resp = httpx.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
            timeout=10.0,
        )
        data = resp.json().get("data") or {}
        level = ((data.get("level_info") or {}).get("current_level")) or 0
        return {"uname": str(data.get("uname") or ""), "mid": data.get("mid") or 0, "level": int(level)}
    except Exception:  # noqa: BLE001
        return {"uname": "", "mid": 0, "level": 0}


def cached_account_info() -> dict[str, Any]:
    if COOKIE_PATH.exists():
        try:
            data = json.loads(COOKIE_PATH.read_text(encoding="utf-8"))
            return data.get("account") or {"uname": "", "mid": 0, "level": 0}
        except (json.JSONDecodeError, OSError):
            pass
    return {"uname": "", "mid": 0, "level": 0}


# ---------------------------------------------------------------------------
# 发送循环
# ---------------------------------------------------------------------------

async def _sender_tick(store: AutomationStore) -> str:
    # 登录窗口开启期间暂停发送:档案浏览器被占用,headless 刷新会撞锁
    if (store._state["sender"].get("login_flow") or {}).get("running"):
        return "扫码登录窗口开启中,发送暂停"
    ok, reason = store.can_send_now()
    if not ok:
        return reason or "等待中"
    item = store.next_approved()
    if not item:
        return "无已批准待发条目"
    # Cookie 刷新需要独占 cdp_bili 档案，采集周期进行中不动浏览器，只发已缓存的
    cookie_cached = _cached_cookie()
    if not cookie_cached and store._state["cycle"].get("running"):
        return "采集进行中，Cookie 刷新延后"
    try:
        cookie = cookie_cached or await refresh_bili_cookie()
    except Exception as exc:  # noqa: BLE001
        # 错误必须可见：记录到 sender 状态，监工台展示，不再静默吞掉
        store._state["sender"]["last_error"] = str(exc)[:200]
        store._state["sender"]["last_error_at"] = datetime.now().isoformat(timespec="seconds")
        store.save()
        return f"发送阻塞：{str(exc)[:120]}"
    store.mark_sending(item)
    try:
        from .reply_sender import send_bilibili_reply

        reply_id = await asyncio.to_thread(
            send_bilibili_reply,
            content_id=item["video_id"],
            comment_id=item["comment_id"],
            message=item["draft"],
            cookie=cookie,
        )
        store.mark_sent(item, reply_id)
        store._state["sender"]["last_error"] = ""
        store.save()
        return f"已发送 → {item['commenter']}（《{item['video_title'][:20]}》）"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        store.mark_failed(item, msg)
        if "bili_jct" in msg or "Cookie" in msg:
            try:
                COOKIE_PATH.unlink()
            except OSError:
                pass
        return f"发送失败：{msg[:120]}"


# ---------------------------------------------------------------------------
# 后台任务
# ---------------------------------------------------------------------------

_store: Optional[AutomationStore] = None
_tasks: list[asyncio.Task] = []


def get_store() -> AutomationStore:
    global _store
    if _store is None:
        _store = AutomationStore()
    return _store


async def automation_loop() -> None:
    store = get_store()
    while True:
        try:
            cfg = store.config
            # auto_collect:自动化自己定时扫描采集(默认关)。
            # 2026-10-20 用户定调:先手动批量采集,再从存量数据里筛,效率更高。
            if cfg.get("enabled") and cfg.get("auto_collect", False) and not store._state["cycle"].get("running"):
                last = store._state["cycle"].get("last_run_at", "")
                due = True
                if last:
                    try:
                        elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
                        due = elapsed >= float(cfg.get("collect_interval_hours", 6)) * 3600
                    except ValueError:
                        due = True
                if due:
                    await run_cycle(store)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(60)


async def sender_loop() -> None:
    store = get_store()
    while True:
        try:
            if store.config.get("enabled"):
                await _sender_tick(store)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(20)


def start_background_tasks() -> None:
    if _tasks:
        return
    _tasks.append(asyncio.create_task(automation_loop()))
    _tasks.append(asyncio.create_task(sender_loop()))
