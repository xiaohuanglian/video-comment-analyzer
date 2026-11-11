# -*- coding: utf-8 -*-
"""「发根评论」还是「回具体评论」——按评论区状态做动作路由。

## 为什么要这个模块

回复一条评论，触达是**确定的**：平台会给被回复的人发通知，他大概率会看到。
但这条回复躺在楼中楼里，对这个视频的其他观众基本不可见——楼中楼是单独一页
接口，早期采集没翻，468 个视频里只有 158 个采到过任何子回复。指望回复获得
公域曝光，靠的是"偶尔有人点开楼中楼"。

发一条根评论（直接评在视频下）没有通知，全看赞数排序，赢家通吃：64,966 条
根评论里，前 1% 吃掉 84.2% 的全部点赞，45.7% 一条赞都没有、中位数只有 1。
所以它不是「回复」的替代品，而是另一种动作：

- `reply`：有具体痛点的人 → 回复，确定触达 1 人
- `hot_comment`：评论区冷清、或现有热评还没建立起优势 → 发根评论，争公域曝光
- 两者不互斥：视频有新流量 **且** 评论区有人在问事时，两条都做是对的

## 竞争强度为什么必须按播放档归一

固定赞数门槛是错的。本机语料（`data/comments` + `data/automation/comments`
合并、按 comment_id 去重后 64,966 条根评论 / 468 个视频）按播放档统计
「该视频根评论最高赞」的中位数（2026-11-11 重算，
`scripts/hot_comment_stats.py` 可复现）：

    播放 <1k     n=137  中位 0      （评论区基本没人）
    1k-5k        n= 85  中位 1
    5k-2w        n= 69  中位 8
    2w-5w        n= 49  中位 58
    5w-20w       n= 48  中位 238
    20w-100w     n= 53  中位 438
    >100w        n= 27  中位 1783

（上表是全部视频；写进 `PLAY_TIERS` 的用的是「采样 ≥5 条」那部分的中位，
略高一点——样本少的视频 top1 系统性偏低，如 >100w 档采足后是 2380。）

同一句「30 个赞」，在 2 千播放的视频里已经是压死人的热评，在 20 万播放的
视频里连前二十都进不去。因此判据一律是 `top1 / 同档中位` 的比值。

## 采样少到看不见的时候不要猜

`top1` 是「我们采到的那批根评论里的最大值」，不是平台真热评。实测抽查（对比
`/x-v2-reply/main?mode=3` 的真热序）表明：采到 5 条以上时 top1 基本等于真值
（21 个样本的中位比值 1.00），但**只采到 0–4 条时 6 个里错 4 个**——其中
`117480458555570` 采到 0 条被判「空位」，实际真热评 71 赞。因此当采集条数
少于 `hot_comment_min_sample`（默认 5）而平台又报告有评论时，判
`unknown_coverage`，宁可不动（保守回落到回复）。

注意这一条**不是**按覆盖率过滤的大视频：468 个视频里有 214 个采样不足 5 条，
但采得多的那些 top1 是准的，按覆盖率一刀切会把爆款档样本砍到失真。

## 不要用「发布 24 小时内」当热评窗口

实测评论相对发布时间的到达分布（n=97,435）：6h 内 3.7%、24h 内 9.0%、
48h 内 13.6%、7 天内 25.4%，中位 753 小时。B 站评论区的讨论发生在视频发布
很久之后，热评窗口不是「发布后一天」，而是「这个视频现在还有人看」。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

#: (播放量上限（不含）, 档位标签, 该档「根评论最高赞」的实测中位数)
#: 数字来自 2026-11-11 对本机语料（data/comments + data/automation/comments，
#: 按 comment_id 去重）的统计，只取采样 ≥5 条的视频算中位（采样太少时 top1
#: 会低估，见下）。**去重是必须的**：采集会在中途切排序再采一遍，同一批评论
#: 跨文件重复落盘，不去重会让中位数失真。
#: 改之前请重跑 `scripts/hot_comment_stats.py`。
#:
#: 为什么把 >20w 拆成两档：合成一档时 20 万播放（中位 431）和 1300 万播放
#: （中位 1698）被平均成 577，结果 600 万播放的视频 top1 只有 210 赞也被判
#: 「差不多该占住了」。粗分档会把信号抹平。
PLAY_TIERS: tuple[tuple[Optional[int], str, int], ...] = (
    (1_000, "冷启动(<1k)", 0),
    (5_000, "小流量(1k-5k)", 2),
    (20_000, "中流量(5k-2w)", 9),
    (50_000, "中高流量(2w-5w)", 75),
    (200_000, "高流量(5w-20w)", 252),
    (1_000_000, "大流量(20w-100w)", 431),
    (None, "爆款(>100w)", 2380),
)

_WAN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*[wW万]\s*\+?\s*$")


def parse_play_count(value: Any) -> int:
    """把各平台五花八门的播放量解析成整数。

    B 站给的是字符串（`'5305'`），小红书/抖音会给人读写法（`'10万+'`、`'1.2w'`）。
    解析不出来一律 0——0 在判定里等价于「没有播放量数据」，会走退化分支，
    不会假装成大视频。
    """
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        try:
            return max(0, int(value))
        except (ValueError, OverflowError):
            return 0
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text:
        return 0
    m = _WAN.match(text)
    if m:
        try:
            return max(0, int(float(m.group(1)) * 10_000))
        except ValueError:
            return 0
    m = re.match(r"^\s*([0-9]+)", text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    return 0


def tier_for_play(play: int) -> tuple[str, int]:
    """返回 (档位标签, 该档 top1 赞中位数)。"""
    for limit, label, median in PLAY_TIERS:
        if limit is None or play < limit:
            return label, median
    return PLAY_TIERS[-1][1], PLAY_TIERS[-1][2]


def _likes(row: dict[str, Any]) -> int:
    try:
        return int(str(row.get("like_count") or 0) or 0)
    except (TypeError, ValueError):
        return 0


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


#: 路由取值。`both` 不是单个条目能表达的（它需要同时有根评论与回复两个条目），
#: 由调用方在汇总后回填。
ROUTES = ("hot_comment", "reply", "both", "skip")


def assess_video_competition(
    *,
    video: dict[str, Any],
    root_rows: list[dict[str, Any]],
    config: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """判断一个视频的评论区现在值不值得发根评论。

    `root_rows` 是该视频已采集到的**根评论**（不含楼中楼）。它是"我们看到的"
    而不是平台的完整评论区。实测（对比 `reply/main?mode=3` 的真热序）发现：
    采到 5 条以上时 top1 基本等于真值，采到 0–4 条时会严重低估——所以采样太
    少时不能拿 top1 当判据，改为 `unknown_coverage` 保守不动。

    返回字典（含 `competition` 与 `route`），route 取值见 `ROUTES`。
    """
    cfg = config or {}
    now = now or datetime.now()
    vid = str(video.get("video_id") or "")
    play = parse_play_count(video.get("video_play_count"))
    tier_label, tier_median = tier_for_play(play)

    sorted_rows = sorted(root_rows, key=_likes, reverse=True)
    top1 = _likes(sorted_rows[0]) if sorted_rows else 0
    # 平台报告的评论数通常比我们采到的全，取两者较大值当规模
    reported = _int(str(video.get("video_comment") or 0) or 0, 0)
    comment_count = max(reported, len(root_rows))
    ratio = (top1 / tier_median) if tier_median > 0 else (float(top1) if top1 else 0.0)

    min_play = _int(cfg.get("hot_comment_min_play", 1000), 1000)
    cold_comments = _int(cfg.get("hot_comment_cold_comments", 10), 10)
    crowd_mult = _float(cfg.get("hot_comment_crowd_multiple", 2.0), 2.0)
    crowd_floor = _int(cfg.get("hot_comment_crowd_floor", 50), 50)
    open_ratio = _float(cfg.get("hot_comment_open_ratio", 0.5), 0.5)
    min_sample = _int(cfg.get("hot_comment_min_sample", 5), 5)

    base = {
        "video_id": vid,
        "play": play,
        "tier": tier_label,
        "tier_median": tier_median,
        "top1_like": top1,
        "comment_count": comment_count,
        "sampled": len(root_rows),
        "ratio": round(ratio, 3),
        "hot_texts": [str(r.get("content") or "")[:120] for r in sorted_rows[:3] if str(r.get("content") or "").strip()],
    }

    if play < min_play:
        return {
            **base,
            "competition": "too_small",
            "route": "skip",
            "reason": f"播放 {play} 不足 {min_play}，评论区几乎没人看，发根评论没有收益",
        }

    # 采样太少：top1 不可信（实测 0–4 条时六成判断是错的），宁可不动
    if len(root_rows) < min_sample and reported >= cold_comments:
        return {
            **base,
            "competition": "unknown_coverage",
            "route": "reply",
            "reason": (
                f"只采到 {len(root_rows)} 条根评论（平台报告 {reported} 条），"
                f"看不到真实热评，不拿残缺数据赌根评论"
            ),
        }

    # 冷清：评论区规模小 + 现有热评也没赞 → 一条像样的根评论就能占住
    if comment_count < cold_comments and top1 < cold_comments:
        return {
            **base,
            "competition": "cold",
            "route": "hot_comment",
            "reason": f"评论区冷清（{comment_count} 条评论、最高赞 {top1}），发根评论最容易占位",
        }

    # 被占住：现有热评远超同档中位，再发一条大概率沉底
    crowd_line = max(int(tier_median * crowd_mult), crowd_floor)
    if top1 >= crowd_line:
        return {
            **base,
            "competition": "crowded",
            "route": "reply",
            "reason": f"已有 {top1} 赞的热评（同档中位 {tier_median}），抢不过，改为回复具体的人",
        }

    # 还有空位：现有热评明显低于同档中位
    open_line = max(int(tier_median * open_ratio), 5)
    if top1 <= open_line:
        return {
            **base,
            "competition": "open",
            "route": "hot_comment",
            "reason": f"热评只有 {top1} 赞（同档中位 {tier_median}），还有空位",
        }

    return {
        **base,
        "competition": "contested",
        "route": "reply",
        "reason": f"热评 {top1} 赞（同档中位 {tier_median}）已经有分量，稳的做法是回复具体的人",
    }


def mark_video_routes(items: list[dict[str, Any]]) -> dict[str, int]:
    """给一批候选回填 `video_route`，标出哪些视频「两条都做」。

    `action` 是**这一条**要做什么（发送器靠它决定 root/parent），`video_route`
    是**这个视频**的策略结论：同一视频既有根评论又有回复时，两边的
    `video_route` 都写 `both`，前端据此告诉人「这个视频值得两头都做」。

    返回 {route: 数量} 供漏斗展示。
    """
    by_video: dict[str, set[str]] = {}
    for it in items:
        vid = str(it.get("video_id") or "")
        if not vid:
            continue
        by_video.setdefault(vid, set()).add(str(it.get("action") or "reply"))
    counts: dict[str, int] = {}
    for it in items:
        vid = str(it.get("video_id") or "")
        actions = by_video.get(vid, set())
        route = "both" if len(actions) > 1 else ("hot_comment" if "hot_comment" in actions else "reply")
        it["video_route"] = route
        counts[route] = counts.get(route, 0) + 1
    return counts


def build_hot_candidates(
    comment_rows: list[dict[str, Any]],
    video_map: dict[str, dict[str, Any]],
    config: dict[str, Any],
    *,
    platform: str = "bili",
    now: Optional[datetime] = None,
    skip_videos: Optional[set[str]] = None,
    busy_videos: Optional[dict[str, str]] = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """把「值得发根评论」的视频变成候选条目（一条根评论一个条目）。

    与 `build_candidates`（按评论找人）互补：这里按**视频**找空位，一个视频
    最多出一条根评论草稿。根评论没有目标评论，`comment_id` 记 `"0"`——
    发送时这个值会变成 B 站接口的 `root`/`parent`。
    """
    cfg = config or {}
    now = now or datetime.now()
    funnel = {
        "videos": 0,
        "too_small": 0,
        "crowded": 0,
        "contested": 0,
        "unknown_coverage": 0,
        "cooldown": 0,
        "hot_candidates": 0,
    }
    if not cfg.get("hot_comment_enabled", True):
        return [], funnel

    skip_videos = {str(v) for v in (skip_videos or set())}
    #: 近期已有根评论/正在发的视频 → 换下一个，别在同一个视频下连着刷
    busy_videos = dict(busy_videos or {})
    max_age_h = _float(cfg.get("freshness_b_hours", 168), 168.0)
    quota_left = max(1, _int(cfg.get("hot_comment_max_per_cycle", 2), 2))

    by_video: dict[str, list[dict[str, Any]]] = {}
    for row in comment_rows:
        if str(row.get("parent_comment_id") or "0") not in ("0", ""):
            continue  # 楼中楼不参与根评论竞争统计
        by_video.setdefault(str(row.get("video_id") or ""), []).append(row)

    picked: list[dict[str, Any]] = []
    # 大视频优先：播放量高说明还有人看，同样一条根评论的潜在曝光更大
    ordered = sorted(
        video_map.values(),
        key=lambda v: parse_play_count(v.get("video_play_count")),
        reverse=True,
    )
    for video in ordered:
        if quota_left <= 0:
            break
        vid = str(video.get("video_id") or "")
        if not vid or vid in skip_videos:
            continue
        funnel["videos"] += 1
        if vid in busy_videos:
            funnel["cooldown"] += 1
            continue
        assess = assess_video_competition(video=video, root_rows=by_video.get(vid, []), config=cfg, now=now)
        if assess["route"] != "hot_comment":
            key = "too_small" if assess["competition"] == "too_small" else (
                "unknown_coverage" if assess["competition"] == "unknown_coverage" else (
                    "crowded" if assess["competition"] == "crowded" else "contested"
                )
            )
            funnel[key] += 1
            continue
        try:
            ts = int(video.get("create_time") or 0)
        except (TypeError, ValueError):
            ts = 0
        age_hours = max(0.0, (now.timestamp() - ts) / 3600) if ts else 0.0
        if ts and age_hours > max_age_h:
            funnel["cooldown"] += 1
            continue
        picked.append(
            {
                "id": f"h_{vid}",
                "action": "hot_comment",
                # 根评论没有目标评论：发送时 root/parent 都用 "0"
                "comment_id": "0",
                "video_id": vid,
                "video_title": str(video.get("title") or "")[:80],
                "video_url": str(video.get("video_url") or ""),
                # 根评论的「打开原帖」入口就是视频本身
                "comment_url": str(video.get("video_url") or ""),
                "platform": platform,
                "commenter": "",
                "commenter_id": "",
                "comment_text": "",
                "like_count": int(assess["top1_like"]),
                "age_hours": round(age_hours, 1),
                "signal": f"热评空位({assess['competition']})",
                "tier": "A" if ts and age_hours <= _float(cfg.get("freshness_a_hours", 48), 48.0) else "B",
                # 根评论是「表态」不是「答问题」，起草走 engage 那套口吻
                "lane": "engage",
                "worth": 0,
                "intent": "",
                "match_reason": str(assess["reason"]),
                "screened_by": "rules",
                "persona": "",
                # 已采到的热评原文交给起草做「别重复别人说过的话」的语境
                "sub_replies": assess["hot_texts"][:3],
                "sub_reply_count": len(assess["hot_texts"][:3]),
                "competition": str(assess["competition"]),
                "video_route": "hot_comment",
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
                "note": "根评论（直接评在视频下，不是楼中楼回复）",
            }
        )
        busy_videos[vid] = "picked"
        quota_left -= 1
        funnel["hot_candidates"] += 1
    return picked, funnel
