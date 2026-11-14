# -*- coding: utf-8 -*-
"""评论区回复自动化引擎（B 站 + 小红书双通道）。

流程：定时采集 → 产品需要人群筛选 → LLM 起草 → 风格 lint → 人工批准（UI）→ 受控发送。

红线（不变）：机器只采集、筛选、起草；**发送必须经人工批准**，批准动作只发生在 UI。
状态按平台分库持久化：data/automation/bili_reply.json 与 xhs_reply.json，Web 服务重启后自动续跑。
小红书通道（2026-11 截流工作台）：竞品笔记清单(detail)/关键词(search) 采集 → 同一套筛选 →
起草后经**出站硬校验**（链接/联系方式/引流话术一律拦）→ 人批 → CDP 浏览器仿人工发送；
发送撞风控即**停损暂停**整条通道（默认 24h），被平台处理就停，不调参硬撞。

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
import logging
import os
import random
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from api.services import notify as notify_mod

# 路径常量、平台默认值、筛选规则与出站硬校验已拆到 automation_rules.py。
# 这里原样转出，保持 `from ...reply_automation import X` 的既有写法可用。
from .automation_rules import (  # noqa: F401
    _RE_ACCESS,
    _RE_AI_DECO,
    _RE_AI_ENTITY,
    _RE_AI_WATER,
    _RE_DEBUG,
    _RE_DIRECTOR,
    _RE_EXCLAIM,
    _RE_HOWTO,
    _RE_NEWBIE,
    _RE_OUTBOUND_CONTACT,
    _RE_OUTBOUND_CTA,
    _RE_OUTBOUND_LINK,
    _RE_QUESTION_CUE,
    _RE_RESOURCE_BEG,
    _RE_RHETORIC,
    _RE_SEEKING,
    _RE_SPAM,
    _RE_SPAM_NICK,
    BILI_PROFILE_DIR,
    COMMENT_DIR,
    COOKIE_PATH,
    DEFAULT_CONFIG,
    DY_COMMENT_DIR,
    DY_CONFIG_OVERRIDES,
    PLATFORMS,
    PROJECT_ROOT,
    STORE_PATH,
    XHS_COMMENT_DIR,
    XHS_CONFIG_OVERRIDES,
    classify_comment,
    comment_dir_for,
    dy_draft_violations,
    store_path_for,
    xhs_draft_violations,
)
from .reply_style import check_reply_style, similarity_verdict

# ---------------------------------------------------------------------------
# 状态存储
# ---------------------------------------------------------------------------

class AutomationStore:
    """自动化状态：config + 候选队列 + 已处理评论 + 统计。JSON 持久化。"""

    def __init__(self, path: Path = STORE_PATH, platform: str = "bili"):
        self.path = path
        self.platform = platform if platform in PLATFORMS else "bili"
        # 进程内可重入锁：保护 _state 的读改写与落盘（原先是 asyncio.Lock，
        # 但从未被 await 使用——等于没有锁）。发送循环跑在 to_thread 里时，
        # threading.Lock 才是对的。
        import threading

        self.lock = threading.RLock()
        #: 待落盘的累计计数增量。计数器不能用「合并两份快照取 max」来救——
        #: 两个实例各读到 0、各 +1，max 只会留下 1。这里记录「我加了多少」，
        #: 落盘时在文件锁内叠加到磁盘最新值上，语义才正确。
        self._pending_deltas: dict[str, float] = {}
        self._state: dict[str, Any] = self._load()

    # ---- 持久化 ----
    def _load(self) -> dict[str, Any]:
        # 2026-11-11 审计修复：原先解析失败一律当 {}，下一次 save() 就把
        # items / processed_comment_ids 全部抹掉——已回复用户名单丢失后，
        # 同一批人会被重新回复一遍（这是最不能接受的一类数据损坏）。
        # 现在：文件损坏 → 把坏文件改名留存并抛 JsonStoreCorruption，
        # 由上层明确感知；只有文件真的不存在才走空状态。
        from api.services.json_store import read_json

        data = read_json(self.path, default={}, expect=dict)
        # xhs/dy 通道在通用默认值之上叠加收紧项；已保存的用户配置始终最优先
        base_config = dict(DEFAULT_CONFIG)
        if self.platform == "xhs":
            base_config.update(XHS_CONFIG_OVERRIDES)
        elif self.platform == "dy":
            base_config.update(DY_CONFIG_OVERRIDES)
        state = {
            "config": {**base_config, **(data.get("config") or {})},
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
        """原子写 + 锁内合并。

        两处加固（2026-11-11）：
        - 用**按文件路径共享**的锁（`json_store.lock_for`），而不是实例锁——
          两个实例（CLI + Web、或测试里的多实例）各持一把锁等于没锁。
        - 锁内先重读磁盘，把「别的实例新增的 items / 我这边不认识的
          processed_comment_ids / sent_total 等累计计数」并回来，再落盘。
          否则后写的那份旧快照会把先写的成果整体覆盖。
        """
        from api.services.json_store import atomic_write_text, lock_for, read_json

        with lock_for(self.path):
            try:
                on_disk = read_json(self.path, default={}, expect=dict)
            except Exception:  # noqa: BLE001 - 盘上已损坏时不要连累本次写入
                on_disk = {}

            with self.lock:
                mine = {
                    "config": self._state["config"],
                    "items": self._state["items"],
                    "processed_comment_ids": sorted(self._state["processed_comment_ids"]),
                    "stats": self._state["stats"],
                    "cycle": self._state["cycle"],
                    "sender": self._state["sender"],
                }

            payload = dict(mine)
            if on_disk:
                disk_items = on_disk.get("items") or []
                if isinstance(disk_items, list):
                    known = {str(it.get("id")) for it in mine["items"] if isinstance(it, dict)}
                    merged = list(mine["items"])
                    for it in disk_items:
                        if isinstance(it, dict) and str(it.get("id")) not in known:
                            merged.append(it)
                    payload["items"] = merged
                payload["processed_comment_ids"] = sorted(
                    set(mine["processed_comment_ids"])
                    | {str(c) for c in (on_disk.get("processed_comment_ids") or [])}
                )
                disk_stats = on_disk.get("stats") or {}
                if isinstance(disk_stats, dict):
                    stats = dict(mine["stats"])
                    with self.lock:
                        deltas = dict(self._pending_deltas)
                    for key, delta in deltas.items():
                        base = disk_stats.get(key)
                        if isinstance(base, (int, float)) and isinstance(stats.get(key), (int, float)):
                            stats[key] = base + delta
                        elif isinstance(base, (int, float)):
                            stats[key] = base
                    payload["stats"] = stats
                disk_config = on_disk.get("config") or {}
                if isinstance(disk_config, dict):
                    payload["config"] = {**disk_config, **mine["config"]}

            try:
                text = json.dumps(payload, ensure_ascii=False, indent=1)
            except (TypeError, ValueError) as exc:  # 状态里混入不可序列化对象
                raise RuntimeError(f"自动化状态无法序列化，未写入：{exc}") from exc
            atomic_write_text(self.path, text)

            # 内存与磁盘对齐，避免下次又拿旧快照去覆盖
            with self.lock:
                self._state["items"] = payload["items"]
                self._state["processed_comment_ids"] = set(payload["processed_comment_ids"])
                self._state["stats"] = payload["stats"]
                self._pending_deltas.clear()

    def bump_stat(self, key: str, delta: float = 1) -> None:
        """累计计数自增（跨实例安全）。计数一律走这里，别直接 `+= 1`。"""
        with self.lock:
            current = self._state["stats"].get(key, 0)
            self._state["stats"][key] = (current if isinstance(current, (int, float)) else 0) + delta
            self._pending_deltas[key] = self._pending_deltas.get(key, 0) + delta

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
        # 竞品笔记清单：字符串按换行/逗号切，必须是带 xsec_token 的完整链接
        if "note_urls" in partial:
            val = partial["note_urls"]
            if isinstance(val, str):
                val = [u.strip() for u in re.split(r"[\n，,]", val) if u.strip()]
            cfg["note_urls"] = [str(u).strip() for u in (val or []) if "xiaohongshu.com" in str(u)][:50]
        # 采集模式：auto（清单优先）/ list（只爬清单）/ search（只关键词）
        if "collect_mode" in partial:
            val = str(partial["collect_mode"] or "").strip().lower()
            if val in ("auto", "list", "search"):
                cfg["collect_mode"] = val
        for key in (
            "collect_interval_hours", "max_notes_per_keyword", "max_comments_per_video",
            "collect_timeout_minutes", "freshness_a_hours", "freshness_b_hours",
            "max_new_candidates_per_cycle", "max_per_video_per_day", "daily_send_limit",
            "send_interval_seconds", "send_jitter_seconds", "llm_screen_threshold", "user_cooldown_days",
            "opinion_like_bypass",
            # 热评通道：配额与竞争判定阈值
            "hot_comment_max_per_cycle", "hot_comment_min_play", "hot_comment_cold_comments",
            "hot_comment_crowd_floor", "hot_comment_min_sample", "hot_comment_max_silence_hours",
        ):
            if key in partial:
                try:
                    cfg[key] = max(1, int(partial[key]))
                except (TypeError, ValueError):
                    continue
        # 停损时长允许 0（=关闭停损），其余数值键保持下限 1
        if "sender_pause_hours" in partial:
            try:
                cfg["sender_pause_hours"] = max(0, int(partial["sender_pause_hours"]))
            except (TypeError, ValueError):
                pass
        # 倍数型阈值是浮点（2.0 / 0.5），塞进上面那张 int 白名单会被 int()
        # 截断成 2 和 0——0 会让「竞争空白」判定永不成立。单独处理。
        for key in ("hot_comment_crowd_multiple", "hot_comment_open_ratio"):
            if key in partial:
                try:
                    cfg[key] = max(0.1, float(partial[key]))
                except (TypeError, ValueError):
                    continue
        for key in ("send_window_start", "send_window_end"):
            if key in partial:
                val = str(partial[key] or "").strip()
                if re.fullmatch(r"\d{1,2}:\d{2}", val):
                    cfg[key] = val
        for key in ("enabled", "auto_draft", "llm_screen", "hot_comment_enabled"):
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
        self.bump_stat("candidates_total", added)
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

    def bulk_approve_llm_screened(self) -> tuple[int, int, int]:
        """批量批准全部 LLM 精筛且已有草稿的待审条目。返回 (批准数, 无草稿跳过, 相似度拦截跳过)。"""
        approved = skipped = skipped_similar = 0
        for it in list(self._state["items"]):
            if it.get("status") != "pending_review" or it.get("screened_by") != "llm":
                continue
            if not (it.get("draft") or "").strip():
                skipped += 1
                continue
            try:
                if self.decide(it["id"], "approve"):
                    approved += 1
            except ValueError:  # 相似度拦截
                skipped_similar += 1
        return approved, skipped, skipped_similar

    def _recent_outbound_drafts(self, exclude_id: str = "", days: int = 30) -> list[str]:
        """近 N 天已发/发送中/已批准的草稿,作为相似度比对基准。"""
        cutoff = datetime.now() - timedelta(days=days)
        out: list[str] = []
        for it in self._state["items"]:
            if it.get("status") not in ("sent", "sending", "approved"):
                continue
            if exclude_id and it["id"] == exclude_id:
                continue
            ts_str = it.get("sent_at") or it.get("decided_at") or it.get("created_at") or ""
            try:
                ts = datetime.fromisoformat(ts_str) if ts_str else None
            except ValueError:
                ts = None
            if ts and ts < cutoff:
                continue
            d = (it.get("draft") or "").strip()
            if d:
                out.append(d)
        return out

    def decide(self, item_id: str, action: str, draft: str = "") -> Optional[dict[str, Any]]:
        it = self.find(item_id)
        if not it or it["status"] != "pending_review":
            return None
        if action == "approve":
            final = (draft or it.get("draft") or "").strip()
            if not final:
                return None
            # P0-2 相似度闸:与近 30 天已发/已批草稿比对,block 拒绝、warn 放行但标警
            verdict, score = similarity_verdict(
                final, self._recent_outbound_drafts(exclude_id=item_id), lane=str(it.get("lane") or "help")
            )
            if verdict == "block":
                raise ValueError(
                    f"草稿与近期已发/已批内容过于相似({score:.0%}),为防账号风控已拦截,请改写后再批"
                )
            # 小红书出站硬校验：链接/联系方式/引流话术是封控与举报的直接诱因，批准口拦截
            if self.platform == "xhs":
                violations = xhs_draft_violations(final)
                if violations:
                    raise ValueError(
                        f"草稿含小红书通道硬禁内容({'、'.join(violations)})，已拦截：删掉后重新提交"
                    )
            it["draft"] = final
            it["lint_warnings"] = list(check_reply_style(final))
            if verdict == "warn":
                it["lint_warnings"].append(f"与近期内容相似度 {score:.0%},建议微调措辞")
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
        # 停损暂停：风控类失败后整条通道冷却，到期自动恢复
        pause_until = s.get("pause_until") or ""
        if pause_until:
            try:
                if datetime.fromisoformat(pause_until) > now:
                    reason = s.get("pause_reason") or "风控停损"
                    return False, f"发送暂停中（{reason}，至 {pause_until[5:16]}）"
            except ValueError:
                pass
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

    def pause_sender(self, hours: float, reason: str) -> None:
        """停损：发送撞风控后暂停整条通道（hours<=0 等价于立即恢复）。"""
        if hours <= 0:
            self.clear_pause()
            return
        s = self._state["sender"]
        s["pause_until"] = (datetime.now() + timedelta(hours=hours)).isoformat(timespec="seconds")
        s["pause_reason"] = str(reason)[:120]
        self.save()

    def clear_pause(self) -> None:
        self._state["sender"].pop("pause_until", None)
        self._state["sender"].pop("pause_reason", None)
        self.save()

    def mark_sending(self, item: dict[str, Any]) -> None:
        item["status"] = "sending"
        # 时间戳供启动时 reconcile_stuck_sending() 判断是否中断
        item["sending_at"] = datetime.now().isoformat(timespec="seconds")
        self.save()

    def mark_sent(self, item: dict[str, Any], reply_id: str) -> None:
        item["status"] = "sent"
        item["sent_at"] = datetime.now().isoformat(timespec="seconds")
        item["reply_id"] = str(reply_id or "")
        self.bump_stat("sent_total", 1)
        s = self._state["sender"]
        s["last_send_at"] = item["sent_at"]
        interval = self._state["config"]["send_interval_seconds"]
        jitter = self._state["config"]["send_jitter_seconds"]
        s["next_allowed_at"] = (
            datetime.now() + timedelta(seconds=interval + random.uniform(0, jitter))
        ).isoformat(timespec="seconds")
        self._roll_daily()
        s["sent_today"] = s.get("sent_today", 0) + 1
        # P0-1:发送成功即记入已回复用户表(冷却期内不再选中同一个人)
        cid = str(item.get("commenter_id") or "").strip()
        if cid:
            self._state.setdefault("replied_users", {})[cid] = time.time()
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
    platform: str = "bili",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """从采集行里筛出候选。返回 (候选列表, 漏斗统计)。"""
    now = now or datetime.now()
    funnel = {"comments": 0, "excluded": 0, "stale": 0, "dedup": 0, "candidates": 0, "replied_user": 0, "sub_context": 0}
    quota_left = max(1, int(config.get("max_new_candidates_per_cycle", 8)))
    video_today: dict[str, str] = {}
    today = now.strftime("%Y-%m-%d")
    for it in config.get("_items_today", []):  # 由调用方注入：今天已入队的视频
        video_today[str(it.get("video_id"))] = today
    # 已回复用户冷却表(调用方注入 {mid: 上次发送成功 ts});同一人短期内不重复回复
    cooldown_s = float(config.get("user_cooldown_days", 14)) * 86400
    replied_users: dict[str, float] = {
        str(k): float(v) for k, v in (config.get("_replied_users") or {}).items()
    }
    # 楼中楼(parent != 0)不作为候选:只做语境供精筛判「问题是否已被答好」
    sub_by_parent: dict[str, list[dict[str, Any]]] = {}
    for row in comment_rows:
        pid = str(row.get("parent_comment_id") or "0")
        if pid and pid != "0":
            sub_by_parent.setdefault(pid, []).append(row)

    def _thread_texts(root_id: str, depth: int = 0) -> list[str]:
        """收拢 root_id 楼下(含孙子楼)的子评论文本,最多 8 条、每条 120 字。"""
        texts: list[str] = []
        for sub in sub_by_parent.get(root_id, []):
            if len(texts) >= 8:
                break
            t = str(sub.get("content") or "").strip()
            if t:
                texts.append(t[:120])
            if depth < 2:  # 展开到第三层
                texts.extend(x for x in _thread_texts(str(sub.get("comment_id") or ""), depth + 1) if len(texts) < 8)
        return texts[:8]

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
        if str(row.get("parent_comment_id") or "0") not in ("0", ""):
            funnel["sub_context"] += 1
            continue  # 楼中楼:上面已收进语境表,不当候选
        nickname = str(row.get("nickname") or "")
        if _RE_SPAM_NICK.search(nickname):
            funnel["excluded"] += 1
            continue  # 营销号昵称:卖订阅/代充/接单,评论再像样也不回
        commenter_id = str(row.get("user_id") or "").strip()
        if commenter_id and commenter_id in replied_users:
            if now.timestamp() - replied_users[commenter_id] < cooldown_s:
                funnel["replied_user"] += 1
                continue  # 冷却期内已回过的人,不重复回复
        text = str(row.get("content") or "").strip()
        status, signal = classify_comment(text, platform=platform)
        if status == "excluded" and signal == "无提问":
            # 高赞观点旁路(2026-10-27):语料库本身来自AI关键词采集,视频语境即AI域;
            # 评论没写"AI"两个字≠不在谈AI(实测546条≥50赞实质观点被实体词门槛埋掉)。
            # 赞数过线的实质观点放行给 LLM 精筛,水评仍由感叹/AI水评等规则拦。
            if _lk(row) >= int(config.get("opinion_like_bypass", 50)) and len(text) >= 30:
                status, signal = "target_c", "高赞观点(社区验证过实质)"
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
        sub_replies = _thread_texts(cid)
        picked.append(
            {
                "id": f"c_{cid}",
                "comment_id": cid,
                "video_id": vid,
                "video_title": str(video.get("title") or "")[:80],
                "video_url": str(video.get("video_url") or ""),
                # 小红书受控回复用：带 xsec_token 的完整评论直链（直链无 token 会 404）
                "comment_url": str(row.get("comment_url") or ""),
                "platform": platform,
                "commenter": nickname,
                "commenter_id": commenter_id,
                "comment_text": text[:500],
                "like_count": _lk(row),
                "age_hours": round(age_hours, 1),
                "signal": signal,
                "tier": tier,
                "lane": lane,
                # 动作：这一条要「回复某个人」还是「发根评论」。发送器靠它决定
                # B 站接口的 root/parent（根评论两个都是 0），别有第二处判断。
                "action": "reply",
                "worth": 0,
                "intent": "",
                "match_reason": signal,
                "screened_by": "rules",
                "persona": "",
                "sub_replies": sub_replies,
                "sub_reply_count": len(sub_replies),
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

# 2026-11-11 纠正：这里原先把「我们的定位」硬编码成「用 AI 做视频/动画/图片的教程」，
# 于是筛选标准变成「你符合我的 AI 定位吗」——做母婴/健身/本地服务的人用它，
# 会系统性筛掉自己真正的目标用户。现在定位一律来自项目档案，代码不含任何行业预设。
# 档案未配置时直接报错（ProfileNotConfigured），而不是悄悄用 AI 口径跑。

LLM_SCREEN_PROMPT = """你是评论区「值得回复的人」的精筛助手。回复名额有限,只留给值得回复的人。

我们是谁(产品/内容定位):
{niche}

目标受众:
{audience}

我们的核心价值(用户能从我们这里得到什么):
{value}

{scenario_block}

判定「值得回复」的**唯一标准**：这个人和我们的产品/内容之间,有没有真实的**接触点**。
接触点不是「他属于我们的受众画像」,而是下列任一条成立:
- 他正在经历我们解决的问题(痛点陈述、求助、抱怨);
- 他在用替代方案解决同一问题(别的工具/服务/自学/找人代做),可能有替换或补充空间;
- 他表达了与我们价值主张直接相关的疑问、怀疑或期待;
- 他在讨论我们所在的品类/做法,能自然接话而不显突兀。
**注意**:接触点是「问题层」的,不是「关键词层」的。用户在说「我做的图老板说太假」,
即使一个我们的品牌词都没提,也是强接触点(他在经历我们的问题);
反之用户只是复读了我们视频里的术语,不代表有接触点。

值得回复的人分两类(lane):
- help(帮助型):有明确接触点,且我们能给出**完整、可执行**的答案。特征:具体问题、真实在动手或真准备动手。我们答案覆盖不到的地方(需要专业资质、需要线下、领域外的琐事)不算 help。
- engage(互动型):对我们的品类/做法发表真实观点、体验、怀疑或预测,有内容可接话。
  纯情绪("太强了""泪目")没内容可接,不是 engage。

一律不选(skip):纯水(666/哈哈哈/打卡)、AI生成水评、纯礼貌夸up、引战抬杠、
与我们产品完全无关的求助、购买渠道/账号充值/个案报错调试、求UP主私有资源。
**纯焦虑但零行动意愿**("好焦虑""求暴富""风口不敢上")不是实干者,skip;
**同行/拉人头营销话术**("带你赚""上车""私我")一律 skip。

对方画像(persona,六选一,决定后续回复怎么说话):
- novice_doer 新手实干者:已在动手或真准备动手,卡在具体问题上,需要完整答案和路径
- expert_doer 老手实干者:懂行,谈参数/细节/选型,对等交流给增量信息
- thinker 观点讨论者:发表看法/预测/吐槽,不是求助,接话延续讨论
- watcher 观望焦虑者:看得心动但犹豫、怕被割韭菜,需要稳住+一个能上手的第一步
- beggar 求带党:"求带""怎么加入""带带我",只想被牵着走不想自己动手 → lane=skip
- seller 同行/营销号:拉人头、卖课、引流话术 → lane=skip

评论信号分型(选最贴近的一个,填进 intent):
求工具/求推荐 | 求做法/路径 | 痛点吐槽求解决 | 对比纠结 | 观点/预测 | 经验分享 | 吐槽/怀疑 | 讨论闲聊 | 求UP主专属 | 离域求助

打分 worth(0-10 整数):
- help:接触点强度 × 真实行动意愿 × 我们能答全,三者越齐分越高
- engage:观点有内容 × 能自然接话,能延续对话的吐槽/预测/体验分享高分,纯情绪低分
- watcher 型 engage 值得回(可转化),但值得≠被收割:他们值得一句稳住人心、能上手的真话

真人鉴定(is_ai_comment):平台有大量AI/Agent生成的评论,回它=机器对机器,浪费名额。
AI评论特征:装饰符包裹(❀✦❖)、标签式开头("现身说法版:""这条把账算得最清楚:")、
复述视频内容给结构化评价、完美"不是X是Y"翻案且无个人痕迹、精确数字考据腔、
放任何视频下都成立的通用口号。真人特征:个人处境(我大一/我辞职了/家里人…)、
情绪残留(语气词/错字/粗暴)、具体经历、平台原生梗和表情、@朋友闲聊。
疑似AI生成 → is_ai_comment=true,一律 lane=skip,reason 写明证据。

已答判定(already_answered):输入可能带「评论区已有回复」(楼中楼摘录)。
若 UP 或热心人已在评论区把该问题答得靠谱完整,再答一遍像机器人刷存在感 →
already_answered=true,一律 lane=skip,reason 里写明「已被答」。
若已有回复只是不痛不痒/答非所问,才继续评分。

接触点判据(contact,必填,给人工审核看):
写清「这个人处于哪个具体情境、为什么和我们有关」。至少包含一个具体细节
(他的动作/处境/卡点),不许写空话。若 lane=skip 且无接触点,写"无接触点"。

输入给你评论原文、所在视频标题、(若有)楼中楼摘录。只输出一个 JSON 对象:
{{"lane": "help|engage|skip", "contact": "一句话说清他的情境与关联", "persona": "novice_doer|expert_doer|thinker|watcher|beggar|seller", "intent": "信号类型", "worth": 0-10, "is_ai_comment": true|false, "already_answered": true|false, "reason": "一句话理由,给人工审核看"}}
"""


class LlmScreenUnavailable(RuntimeError):
    """LLM 精筛整体不可用(未配置/网关不通),调用方应降级为纯规则模式。"""


def _screen_brief() -> str:
    """把项目档案注入精筛 prompt。

    定位来源优先级：项目档案（唯一真相源）→ 策略档案（旧字段，兼容）
    → **报错**。绝不再回落到某个内置行业，否则通用工作台又会退化成
    「只服务 AI 内容创作者」。
    """
    from api.services.insight.project_profiles import (
        ProfileNotConfigured,
        get_profile,
        is_configured,
    )

    profile = None
    try:
        from api.services import strategy as _strategy

        s = _strategy.load() or {}
    except Exception:  # noqa: BLE001
        s = {}

    # 优先用策略档案里显式填写的定位（用户在设置页填的），
    # 它通常比通用 project profile 更贴近当前账号。
    niche = str(s.get("niche") or s.get("domain") or s.get("name") or "").strip()
    audience = str(s.get("target_audience") or "").strip()

    # 定位和分析口径现在是同一份档案（2026-11-11 合并），拿到 profile_id 就整份取出来，
    # 下面还要用它的 research_goal 当价值主张。
    pid = str(s.get("profile_id") or "").strip()
    if pid:
        try:
            candidate = get_profile(pid)
        except Exception:  # noqa: BLE001
            candidate = None
        if candidate is not None and is_configured(candidate):
            profile = candidate
    if profile is not None:
        niche = niche or str(profile.domain or "").strip() or str(profile.name or "").strip()
        audience = audience or str(profile.target_audience or "").strip()

    if not (niche and audience):
        raise ProfileNotConfigured(
            "回复筛选需要先知道「我们是谁、面向谁」。请到「增长工作台 → 产品档案」"
            "填写 niche 与 target_audience，或配置一份项目档案（domain / target_audience）。"
            "此前这里会静默回落到内置的 AI 内容定位，导致筛选口径整体跑偏。"
        )

    # 价值主张：档案里没这一项时用研究目标兜底，仍为空则明确写出来，
    # 让模型知道自己没有这项信息，而不是自行编造。
    value = ""
    if profile is not None:
        value = str(profile.research_goal or "").strip() or str(profile.context_compact or "").strip()
    if not value:
        value = "（未填写：请仅根据「定位」与「受众」判断接触点，不要假设具体卖点）"

    # 切场景：如果用户已经跑过「场景矩阵」并选定场景，把它注入进来，
    # 这样筛选会围绕"这条评论属于哪个已选场景"来判断，而不是泛泛而谈。
    scenario_block = ""
    selected = s.get("target_scenarios") or []
    if isinstance(selected, list) and selected:
        lines = []
        for item in selected[:5]:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                trigger = str(item.get("trigger") or "").strip()
                if name:
                    lines.append(f"- {name}" + (f"（触发情境：{trigger}）" if trigger else ""))
        if lines:
            scenario_block = (
                "我们当前重点切入的具体场景（评论命中这些场景的优先级更高）：\n"
                + "\n".join(lines)
                + "\n"
            )

    return LLM_SCREEN_PROMPT.format(
        niche=niche,
        audience=audience,
        value=value,
        scenario_block=scenario_block,
    )


def _extract_screen_json(reply: str) -> Optional[dict[str, Any]]:
    """统一走 api.services.llm_json（原先贪婪正则会跨对象乱切）。"""
    from api.services.llm_json import extract_json_object

    return extract_json_object(reply)


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
        user_payload: dict[str, Any] = {
            "视频标题": item.get("video_title", ""),
            "评论原文": item.get("comment_text", ""),
        }
        if item.get("sub_replies"):
            user_payload["评论区已有回复"] = item["sub_replies"]
        user_msg = json.dumps(user_payload, ensure_ascii=False)
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
        if str(data.get("is_ai_comment", "")).strip().lower() in ("true", "是", "1"):
            lane = "skip"  # 疑似AI生成评论:回它是机器对机器,一律拦下
            item["match_reason"] = "疑似AI生成评论,不互动"
        if str(data.get("already_answered", "")).strip().lower() in ("true", "是", "1"):
            lane = "skip"  # 已被答好:再答像机器人,一律拦下
        if lane not in ("help", "engage"):
            lane = "skip"
        persona = str(data.get("persona") or "").strip().lower()
        if persona not in ("novice_doer", "expert_doer", "thinker", "watcher", "beggar", "seller"):
            persona = "novice_doer" if lane == "help" else "thinker"
        if persona in ("beggar", "seller"):
            lane = "skip"  # 求带党/卖课同行:永不互动
        item["lane"] = lane
        item["persona"] = persona
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

BILI_AUTO_SYSTEM_PROMPT = """为B站评论区一位具体用户起草公开回复（只输出正文，40-140中文字）。
你是用 AI 做生意的实战创业者。回复的目标：把答案直接给全,给对方真价值。

写法:
- 开头直接回应他问的事，步骤、工具、参数给全；不指路、不让对方自己去翻去找
- 平等口吻，像同路人帮忙，不像老师教学生；东西难找就归因于入口设计，不说对方
- 长短句混着写，允许口语词(其实/说白了/后来我直接);步骤说完就停,不追加"希望有帮助",不憋金句收尾
- 个人经验用泛化表达("我之前也这么试过");没量过的精确数字不写,不编细节
- 结尾禁装饰:步骤或观点说完自然停,不总结不升华,不写「这块我也还在试」式程式化露怯尾巴

硬禁令：
- 不出现任何产品名、下载、链接、App、网址、关注我、私信我
- 不用破折号；冒号只能用来引直接原话
- 禁"不是…而是…"翻案句式；禁居高临下（其实很简单/再找找看/别急着放弃）
- 禁黑话（赋能/闭环/底层逻辑/码住/建议收藏/值得关注）
- 禁结尾开放反问(你觉得呢/怎么看/哪个更好这类),陈述完就收
- 禁金句收尾(本质上/归根结底/真正的X是Y这类收束句),观点说完平淡收
- 禁套话开场(太真实了/深有同感/说到心坎)
- 不编造不确定的事实；没有十足把握就不提自己的主页或作品
- 禁"跟我学""带你赚"式卖课腔;禁贩卖焦虑"""

BILI_ENGAGE_SYSTEM_PROMPT = """为B站评论区一位具体用户起草公开回复（只输出正文，25-100中文字）。
你也是在做 AI 生意的人,对方发表了对 AI 或 AI 商业机会的看法/体验/吐槽,不是在求助。像评论区里恰好懂行的路人,接一句就走。

人味规则(优先级最高):
- 别用固定模具:有时一两句就完,有时三四句;严禁每条都是「共情开场+个人经验+观点收束」三段式
- 长短句混着写:可以一句三个字,也可以一句三十字不换气;允许口语词(其实/说白了/后来我直接/有一说一)
- **结尾禁一切装饰**:最后一句就是一个具体的事实、细节或观点,说完自然停;不总结、不升华、不表态收束、不程式化露怯(「这块我也还在试」「没完全跑通」这类尾巴一律不写)——结尾是模板感最重的位置
- 个人经历只写泛化的、你真会有的(「我之前也这么试过」);严禁编造精确细节和数字
- 禁套话开场:「太真实了」「深有同感」「说到心坎」;共情用半个词(确实/是这样的/倒也没错)

接话要领:
- 先接住对方的具体观点再回应:认可哪点、补充一点,或有不一致就温和说出来
- 平等口吻,对观点不对人,不说教不纠正人
- 说完就收尾,像真人路过留一句;只有你真想听对方答案、且问题具体到他的处境时才随口一问

硬禁令：
- 禁结尾开放反问（"你觉得呢""你怎么看""你们觉得哪个好"这类引导互动式提问）——运营号求互动的套路
- 不出现任何产品名、下载、链接、App、网址、关注我、私信我
- 不用破折号；冒号只能用来引直接原话
- 禁"不是…而是…"翻案句式；禁居高临下（其实很简单/再找找看/别急着放弃）
- 禁黑话（赋能/闭环/底层逻辑/码住/建议收藏/值得关注）
- 不编造事实；没把握的经验不说
- 禁"跟我学""带你赚"式卖课腔;禁贩卖焦虑;禁群发味称呼(亲/家人们)"""

# 根评论（直接评在视频下）与「回复某个人」是两种文体：
# 回复有明确的对话对象，可以接话、可以答问题；根评论面对的是**还没说话的一群人**，
# 而且它要和已有的热评抢排序。所以这里不写"回应他"，写"补一个别人没说的点"。
BILI_HOT_SYSTEM_PROMPT = """为一条B站视频写一条公开根评论（只输出正文，30-110中文字）。
这条评论会直接出现在视频下方，和已有的热评一起按赞数排序。看的人还没说话，你是在替他们补一个角度。

写法:
- 给一个具体的、可验证的观察或经验,不要泛泛赞同视频。让人看完能说"这条说到点上了"
- 最好带上视频里没讲到的那个细节/代价/前提——这是能拿到赞的原因
- 平等口吻,像同行看完随手留一句;不评价UP主水平,不说"讲得真好"
- 长短句混着写,允许口语词(其实/说白了/后来我直接);一到三句就够
- 结尾就是最后那个事实或判断,说完停;不总结不升华不喊话

硬禁令：
- 不出现任何产品名、下载、链接、App、网址、关注我、私信我
- 不用破折号；冒号只能用来引直接原话
- 禁"不是…而是…"翻案句式；禁居高临下
- 禁黑话（赋能/闭环/底层逻辑/码住/建议收藏/值得关注）
- 禁结尾开放反问(你觉得呢/怎么看),禁求互动式收尾
- 禁金句收尾(本质上/归根结底/真正的X是Y)
- 禁套话开场(太真实了/深有同感/说到心坎),禁"前排""沙发"
- 不编造没做过的经验和不存在的数字;禁"跟我学""带你赚"式卖课腔"""

# persona → 起草策略(识别对方是什么样的人,说针对性的话;beggar/seller 不入起草)
_PERSONA_TACTICS = {
    "novice_doer": "对方是新手实干者:给全答案+完整路径,步骤化,专业词配大白话",
    "expert_doer": "对方是老手实干者:对等交流,给增量信息和实战细节,不解释基础概念,不居高临下",
    "thinker": "对方是观点讨论者:自然接话,延续对方的观点,带一句自己的实际经验",
    "watcher": "对方是观望焦虑者:先稳住人心(不贩卖焦虑也不灌鸡汤),再给一个今天就能上手的第一步,把心动变成行动,绝不推销",
}

# 结构变体:按条打散骨架,防「每条同一模具」的批量 AI 感(id 哈希选,可复现)
_ENGAGE_STRUCTURES = [
    "一两句短评就完,别铺开",
    "先接一句,再补一点自己的看法,收在一个具体细节上",
    "只补一个具体的小经验或小细节,别的都不说",
    "就观点回观点,有分歧就温和说,不共情开场",
    "以一个具体的事实或观察开头,说完就停,不加任何收束",
    "帮对方把他的观点往前推一步,用你见过的一个现象佐证,不收尾",
]
_HELP_STRUCTURES = [
    "直接给答案,步骤说完就停",
    "先接一句对方的处境,再给步骤",
    "答案给全,末尾跟一句为什么,平收",
    "以最关键的一个动作开头,展开完自然结束,不总结",
]


def _system_prompt_for(item: dict[str, Any]) -> str:
    # 根评论是第三种文体：不是回答谁，是给还没说话的观众补一个角度（见 BILI_HOT_SYSTEM_PROMPT）
    if item.get("action") == "hot_comment":
        base = BILI_HOT_SYSTEM_PROMPT
    elif item.get("lane") == "engage":
        base = BILI_ENGAGE_SYSTEM_PROMPT
    else:
        base = BILI_AUTO_SYSTEM_PROMPT
    if item.get("platform") == "xhs":
        return base + XHS_PROMPT_ADDENDUM
    if item.get("platform") == "dy":
        return base + DY_PROMPT_ADDENDUM
    return base


# 小红书平台补充规则：语气/篇幅适配 + 平台红线（拼接在 B 站基础 prompt 之后）
XHS_PROMPT_ADDENDUM = """

小红书补充规则（这是小红书评论区，不是B站）：
- 语气比B站更生活化一点，可用一两个 emoji（不堆砌），不写B站梗
- 篇幅更短：30-80 字优先；对方问什么答什么，别铺教程长文
- 红线：绝不出现链接、任何平台账号名、联系方式、「看我主页/私信我」式引流——这是小红书封控主因，比语气问题严重得多"""


# 抖音平台补充规则：拼接在 B 站基础 prompt 之后
DY_PROMPT_ADDENDUM = """

抖音补充规则（这是抖音评论区，不是B站）：
- 语气比B站更口语更直接，像刷视频的人顺手回一句；可以用「哈哈」「确实」这类语气词，不堆 emoji（最多一个）
- 篇幅短：20-60 字优先；抖音评论没人读长文，一两句说完就收
- 红线：绝不出现链接、任何平台账号名、联系方式、「看我主页/私信我」式引流——抖音对引流评论降权重罚，比语气问题严重得多"""


def _llm_user_message(item: dict[str, Any]) -> str:
    _platform_label = {"xhs": "小红书", "dy": "抖音"}.get(item.get("platform"), "B站")
    is_hot = item.get("action") == "hot_comment"
    payload: dict[str, Any] = {
        "平台": _platform_label,
        "回复类型": (
            "根评论(直接评在视频下,面对还没说话的一群观众)"
            if is_hot
            else ("帮助型(给全答案)" if item.get("lane", "help") == "help" else "互动型(自然接话)")
        ),
        "视频标题": item["video_title"],
        "信号": item.get("intent") or item["signal"],
        "入选理由": item.get("match_reason", ""),
    }
    if is_hot:
        # 根评论没有「对方评论」，取而代之的是「已经有人说了什么」——
        # 重复已有的热评等于白写一条，必须让模型知道要绕开哪些点
        if item.get("sub_replies"):
            payload["评论区已有热评"] = item["sub_replies"]
            payload["写法要求"] = "别重复上面这些已经被说过的话;找它们没提到的那一面"
    else:
        payload["对方评论"] = item["comment_text"]
    persona = str(item.get("persona") or "")
    if persona and persona in _PERSONA_TACTICS:
        payload["对方画像"] = persona
        payload["回复策略"] = _PERSONA_TACTICS[persona]
    # 结构变体:同批草稿骨架互不相同,打散批量模板感
    structures = _HELP_STRUCTURES if item.get("lane", "help") == "help" else _ENGAGE_STRUCTURES
    payload["本条写法"] = structures[hash(str(item.get("id") or "")) % len(structures)]
    # 私域操盘知识库素材(风物执守·XY 原子,仅观点参考,不照抄不提来源)
    _query = str(item.get("comment_text") or "").strip() or str(item.get("video_title") or "").strip()
    try:
        from api.services import knowledge as kb

        hits = kb.search(_query, k=2, topics=["私域运营", "成交与话术", "流量获取", "IP人设", "内容创作与平台"])
        if hits:
            payload["可用素材"] = [h["knowledge"][:120] for h in hits]
            payload["素材用法"] = "只取观点融入自己的话,不照抄原句,不提素材来源"
    except Exception:  # noqa: BLE001
        pass
    if item.get("sub_replies") and not is_hot:
        payload["评论区已有回复(楼中楼)"] = item["sub_replies"]
        payload["已有回复处理"] = "若已有人答对一部分,给增量或更完整版,不重复原话"
    head = "起草视频根评论：" if is_hot else "起草评论区回复："
    return head + "\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# 自动重写触发类(AI味硬伤,命中即重写;冒号/排比等低危格式仅标注不重写)
_REWRITE_TRIGGER_KEYS = ("结尾开放反问", "金句收尾", "套话开场", "翻译腔", "群发味", "连接词堆叠", "编造感精确数字", "模板化不确定尾巴")


def _ai_flavor_issues(warnings: list[str]) -> list[str]:
    """从 lint 警告里抽出需要自动重写的 AI 味硬伤。"""
    return [w for w in warnings if any(k in w for k in _REWRITE_TRIGGER_KEYS)]


async def draft_with_llm(item: dict[str, Any]) -> str:
    """起草→自动去 AI 味环:lint 命中硬伤→带具体反馈重写→复检,干净才返回。"""
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
        draft = await asyncio.to_thread(_call)
    except Exception:
        return ""
    if not draft:
        return ""

    # —— 自动去 AI 味环:lint 硬伤→带反馈重写→复检(最多 2 轮,干净即出) ——
    for _round in range(2):
        issues = _ai_flavor_issues(check_reply_style(draft))
        if not issues:
            break

        # 默认参数在定义时绑定当前轮的 draft/issues：
        # 避免闭包读到下一轮循环的值（B023）。
        def _rewrite(_draft: str = draft, _issues: list[str] = issues) -> str:
            completion = client.chat.completions.create(
                model=settings.get("model_name") or "deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt
                     + "\n\n你现在修改自己的草稿。只修复下列问题,内容与长度大致保持,其余一字不动;输出修改后的完整回复正文,不要任何说明。"},
                    {"role": "user", "content": _llm_user_message(item)
                     + f"\n\n我的草稿:\n{_draft}\n\n必须修复的问题:\n"
                       + "\n".join(f"- {w}" for w in _issues)},
                ],
                temperature=0.4,
                max_tokens=2000,
            )
            return (completion.choices[0].message.content or "").strip()

        try:
            fixed = await asyncio.to_thread(_rewrite)
        except Exception:  # noqa: BLE001
            break
        if not fixed:
            break
        draft = fixed
    return draft


# ---------------------------------------------------------------------------
# 采集子进程 + 数据读取
# ---------------------------------------------------------------------------

def build_collect_command(config: dict[str, Any], platform: str = "bili") -> list[str]:
    keywords = ",".join(config.get("keywords") or [])
    # 子评论开关从采集器全局配置读(P1-4 打开;曾因硬编码 false 导致始终不采)
    try:
        from config import base_config as _crawler_cfg

        sub_comment = str(bool(_crawler_cfg.ENABLE_GET_SUB_COMMENTS)).lower()
    except Exception:  # noqa: BLE001
        sub_comment = "false"
    if platform == "xhs":
        # 小红书：Cookie 登录（取自 CDP 浏览器，经 VC_CRAWLER_COOKIES 注入子进程）
        # 目标源两种：竞品笔记清单（detail，读请求最少）或关键词搜索（search，发现新爆笔记）
        note_urls = [str(u).strip() for u in (config.get("note_urls") or []) if str(u).strip()]
        mode = str(config.get("collect_mode") or "auto")
        use_list = bool(note_urls) and mode in ("auto", "list")
        cmd = [
            "uv", "run", "python", "main.py",
            "--platform", "xhs",
            "--lt", "cookie",
            "--type", "detail" if use_list else "search",
            "--crawler_max_notes_count", str(config.get("max_notes_per_keyword", 10)),
            "--max_comments_count_singlenotes", str(config.get("max_comments_per_video", 60)),
            "--get_comment", "true",
            "--get_sub_comment", sub_comment,
            "--save_data_option", "jsonl",
            "--save_data_path", str(comment_dir_for("xhs").relative_to(PROJECT_ROOT)),
            # 注意不传 --split_by_video：默认 True 才会平铺落盘 contents_/comments_*.jsonl，
            # 传 false 反而走 {platform}/{file_type}/search_* 嵌套布局，read_collected 找不到
            "--headless", "false",
        ]
        if use_list:
            cmd.extend(["--specified_id", ",".join(note_urls)])
        else:
            cmd.extend(["--keywords", keywords])
        return cmd
    if platform == "dy":
        # 抖音：CDP 模式连本机已登录浏览器（client 直接从浏览器上下文取 cookie，
        # 不需要注入 cookie env）。目标源同 xhs：对标视频清单(detail)或关键词搜索(search)。
        # 注意 dy 搜索每页固定 10 条（crawler 内部会把 max_notes 强制抬到 ≥10），
        # 配置里的 max_notes_per_keyword 按每词 10 条理解即可。
        video_urls = [str(u).strip() for u in (config.get("note_urls") or []) if str(u).strip()]
        mode = str(config.get("collect_mode") or "auto")
        use_list = bool(video_urls) and mode in ("auto", "list")
        cmd = [
            "uv", "run", "python", "main.py",
            "--platform", "dy",
            "--lt", "qrcode",
            "--type", "detail" if use_list else "search",
            "--crawler_max_notes_count", str(config.get("max_notes_per_keyword", 10)),
            "--max_comments_count_singlenotes", str(config.get("max_comments_per_video", 60)),
            "--get_comment", "true",
            "--get_sub_comment", sub_comment,
            "--save_data_option", "jsonl",
            "--save_data_path", str(comment_dir_for("dy").relative_to(PROJECT_ROOT)),
            # 同 xhs 教训：不传 --split_by_video，保持平铺 contents_/comments_*.jsonl
            "--headless", "false",
        ]
        if use_list:
            cmd.extend(["--specified_id", ",".join(video_urls)])
        else:
            cmd.extend(["--keywords", keywords])
        return cmd
    return [
        "uv", "run", "python", "main.py",
        "--platform", "bili",
        "--lt", "qrcode",
        "--type", "search",
        "--keywords", keywords,
        "--crawler_max_notes_count", str(config.get("max_notes_per_keyword", 20)),
        "--max_comments_count_singlenotes", str(config.get("max_comments_per_video", 100)),
        "--get_comment", "true",
        "--get_sub_comment", sub_comment,
        "--save_data_option", "jsonl",
        "--save_data_path", str(COMMENT_DIR.relative_to(PROJECT_ROOT)),
        "--headless", "false",
    ]


def _normalize_ts(value: Any) -> int:
    """评论时间归一成秒级 int；无法解析返回 0。容忍 int 秒/int 毫秒/常见日期串。"""
    try:
        if isinstance(value, (int, float)):
            ts = int(value)
            return ts // 1000 if ts > 10_000_000_000 else ts
        text = str(value or "").strip()
        if not text:
            return 0
        if text.isdigit():
            ts = int(text)
            return ts // 1000 if ts > 10_000_000_000 else ts
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return int(datetime.strptime(text, fmt).timestamp())
            except ValueError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return 0


def _is_xhs_comment_row(row: dict[str, Any]) -> bool:
    """xhs 存储层的判据：有 note_id 而无 video_id（bili 行恒有 video_id）。"""
    return bool(row.get("note_id")) and not row.get("video_id")


def _normalize_xhs_comment(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["video_id"] = str(row.get("note_id") or "")
    out["create_time"] = _normalize_ts(row.get("create_time"))
    out["platform"] = "xhs"
    return out


def _normalize_xhs_content(row: dict[str, Any]) -> dict[str, Any]:
    """xhs 笔记行归一成 bili 形状（video_id/video_url/title），供筛选层无差别消费。"""
    out = dict(row)
    out["video_id"] = str(row.get("note_id") or row.get("video_id") or "")
    out["video_url"] = str(row.get("note_url") or row.get("video_url") or "")
    if not str(out.get("title") or "").strip():
        out["title"] = str(row.get("desc") or "")[:80]
    out["platform"] = "xhs"
    return out


def _is_dy_comment_row(row: dict[str, Any]) -> bool:
    """dy 存储层的判据：有 aweme_id 而无 video_id/note_id。"""
    return bool(row.get("aweme_id")) and not row.get("video_id") and not row.get("note_id")


def _normalize_dy_comment(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["video_id"] = str(row.get("aweme_id") or "")
    out["create_time"] = _normalize_ts(row.get("create_time"))
    out["platform"] = "dy"
    return out


def _normalize_dy_content(row: dict[str, Any]) -> dict[str, Any]:
    """dy 视频行归一成 bili 形状（video_id/video_url/title）。"""
    out = dict(row)
    out["video_id"] = str(row.get("aweme_id") or row.get("video_id") or "")
    out["video_url"] = str(row.get("aweme_url") or row.get("video_url") or "")
    if not str(out.get("title") or "").strip():
        out["title"] = str(row.get("desc") or row.get("title") or "")[:80]
    out["platform"] = "dy"
    return out


def _row_platform(row: dict[str, Any]) -> str:
    """按行形状识别采集行属于哪个平台（归一化过的行带 platform 字段，优先读它）。"""
    p = str(row.get("platform") or "").strip()
    if p in ("xhs", "dy", "bili"):
        return p
    if row.get("note_id"):
        return "xhs"
    if row.get("aweme_id"):
        return "dy"
    return "bili" if row.get("video_id") or row.get("bvid") else ""


def _fit_platform(row: dict[str, Any], platform: str) -> bool:
    """该行是否属于当前通道。bili 通道放行未知形状行（历史行为），其余严格匹配。"""
    rp = _row_platform(row)
    if platform in ("xhs", "dy"):
        return rp == platform
    return rp in ("", "bili")


def read_collected(
    comment_dir: Path = COMMENT_DIR, platform: str = "bili"
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """读自动化目录下全部 contents/comments jsonl（跨周期追加，靠 comment_id 去重）。

    platform=xhs/dy 时把该平台行归一成 bili 形状并只保留本平台数据；
    platform=bili 时跳过混进同一目录的 xhs/dy 行，各通道互不串数据。
    """
    video_map: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    if not comment_dir.exists():
        return rows, video_map
    for path in sorted(comment_dir.glob("contents_*.jsonl")):
        try:
            # 注意用 split("\n") 而非 splitlines()：笔记/评论正文可能含 U+2028 等
            # Unicode 行分隔符（splitlines 会切它，文件迭代不会），splitlines 会把
            # 完整 JSON 行撕成两半导致解析失败丢数据
            for line in path.read_text(encoding="utf-8").split("\n"):
                if line.strip():
                    v = json.loads(line)
                    if not _fit_platform(v, platform):
                        continue
                    if platform == "xhs":
                        v = _normalize_xhs_content(v)
                    elif platform == "dy":
                        v = _normalize_dy_content(v)
                    video_map[str(v.get("video_id"))] = v
        except (json.JSONDecodeError, OSError):
            continue
    for path in sorted(comment_dir.glob("comments_*.jsonl")):
        try:
            for line in path.read_text(encoding="utf-8").split("\n"):
                if line.strip():
                    row = json.loads(line)
                    if not _fit_platform(row, platform):
                        continue
                    if platform == "xhs":
                        row = _normalize_xhs_comment(row)
                    elif platform == "dy":
                        row = _normalize_dy_comment(row)
                    rows.append(row)
        except (json.JSONDecodeError, OSError):
            continue
    return rows, video_map


BULK_COMMENT_DIR = PROJECT_ROOT / "data" / "comments"


def _hot_busy_videos(store: AutomationStore) -> dict[str, str]:
    """哪些视频不该再出根评论候选（已经有根评论在队列里/今天发过）。

    根评论是公开表态，同一个视频下一天连发两条非常像刷屏；而且我们的
    每日上限本来就窄，浪费在同一个视频上不划算。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    busy: dict[str, str] = {}
    for it in store.items:
        if it.get("action") != "hot_comment":
            continue
        vid = str(it.get("video_id") or "")
        if not vid:
            continue
        status = str(it.get("status") or "")
        if status in ("pending_review", "approved", "sending"):
            busy[vid] = status
        elif status == "sent" and str(it.get("sent_at") or "").startswith(today):
            busy[vid] = "sent_today"
    return busy


async def _queue_candidates(
    store: AutomationStore,
    rows: list[dict[str, Any]],
    video_map: dict[str, dict[str, Any]],
    *,
    max_candidates: int,
    auto_draft: bool,
) -> dict[str, Any]:
    """筛选 → 精筛 → 起草 → 入队。`screen_collected` 与 `run_cycle` 共用这一份。

    原先两处各抄了一遍同样的 30 行，加通道时改一处漏一处是必然的。
    这里并联两条通道：

    - `build_candidates`：按**评论**找人 → `action="reply"`（确定触达 1 人）
    - `build_hot_candidates`：按**视频**找空位 → `action="hot_comment"`（争公域曝光）

    两条通道共用每日上限，但根评论另有 `hot_comment_max_per_cycle` 的小配额：
    根评论风险高于楼中楼回复（公开、永久、对账号权重影响更大），不该占满额度。
    """
    from .hot_comment import build_hot_candidates, mark_video_routes

    cfg = dict(store.config)
    quota = max(1, int(max_candidates))
    cfg["_items_today"] = [it for it in store.items if str(it.get("created_at", "")).startswith(datetime.now().strftime("%Y-%m-%d"))]
    cfg["_replied_users"] = dict(store._state.get("replied_users") or {})

    hot_picked, hot_funnel = build_hot_candidates(
        rows,
        video_map,
        cfg,
        platform=store.platform,
        busy_videos=_hot_busy_videos(store),
    )
    hot_picked = hot_picked[: max(1, int(cfg.get("hot_comment_max_per_cycle", 2)))]
    reply_quota = max(1, quota - len(hot_picked))

    # 粗筛放大 3 倍给 LLM 精筛挑选，最终仍按 reply_quota 截断
    cfg["max_new_candidates_per_cycle"] = max(1, min(reply_quota * 3, 150))
    reply_picked, funnel = build_candidates(
        rows, video_map, cfg, store._state["processed_comment_ids"], platform=store.platform
    )
    reply_picked, screen_stats = await _refine_candidates(reply_picked, cfg, reply_quota)
    reply_picked = reply_picked[:reply_quota]

    # 根评论候选**不走** LLM 精筛：那套 prompt 判的是「这个人值不值得回」，
    # 根评论没有具体的人；它该不该发已经在 assess_video_competition 里按
    # 播放档/竞争强度判过了。草稿质量由起草 prompt 与人审把关。
    routes = mark_video_routes(hot_picked + reply_picked)
    picked = hot_picked + reply_picked

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
    return {
        "funnel": funnel,
        "hot_funnel": hot_funnel,
        "routes": routes,
        "llm_screen": screen_stats,
        "new_candidates": added,
        "llm_drafted": drafted,
    }


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
        if source_dir is not None:
            rows, video_map = read_collected(source_dir, platform=store.platform)
        else:
            # 默认双目录合并(手动批量 data/comments + 自动周期 data/automation/comments),comment_id 去重
            rows_a, vm_a = read_collected(BULK_COMMENT_DIR, platform=store.platform)
            rows_b, vm_b = read_collected(comment_dir_for(store.platform), platform=store.platform)
            seen: set[str] = set()
            rows = []
            for r in rows_a + rows_b:
                cid = str(r.get("comment_id") or "")
                if cid:
                    if cid in seen:
                        continue
                    seen.add(cid)
                rows.append(r)
            video_map = {**vm_a, **vm_b}
        if not rows:
            return {"ok": False, "error": "两个采集目录都没有数据,先去「评论采集」面板爬一批"}
        queued = await _queue_candidates(
            store, rows, video_map, max_candidates=max_candidates, auto_draft=auto_draft
        )
        summary = {
            "ok": True,
            "source": str(source_dir) if source_dir else "双目录合并(bulk+cycle)",
            "videos": len(video_map),
            "comments": len(rows),
            **queued,
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


def _crawl_profile_env() -> dict[str, str]:
    """采集档（独立浏览器档案）的环境变量；未启用时返回空 dict。

    启用条件：`CRAWL_PROFILE_SUFFIX` 非空（见 `tools/browser_profile.py` 的说明）。
    """
    from tools.browser_profile import crawl_profile_env

    return crawl_profile_env()


def _collect_env(platform: str, xhs_cookie: str = "") -> dict[str, str]:
    """采集子进程环境。

    默认（未启用采集档）：bili 自开浏览器(qrcode)；xhs/dy 连已开的 9222 登录浏览器——
    若让子进程另开浏览器会抢同一 cdp 档案目录，kill_stale_browsers 还会把正在运行的
    登录浏览器当残留杀掉，发送通道随之失效。dy 的 client 直接从浏览器上下文取
    cookie，无需 VC_CRAWLER_COOKIES 注入。

    启用采集档（CRAWL_PROFILE_SUFFIX）后：采集一律自己开浏览器用独立档案 + 独立端口，
    也不再借用发送侧的 Cookie——那正是「读侧拖垮写侧」的技术根因。代价是采集档要单独
    登录一次（登录态存在它自己的 profile 里）。
    """
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    profile_env = _crawl_profile_env()
    if profile_env:
        env.update(profile_env)
        env["CDP_CONNECT_EXISTING"] = "0"
        env.pop("VC_CRAWLER_COOKIES", None)
        return env
    env["CDP_CONNECT_EXISTING"] = "0" if platform == "bili" else "1"
    if platform == "xhs" and xhs_cookie:
        env["VC_CRAWLER_COOKIES"] = xhs_cookie
    return env


async def run_cycle(store: AutomationStore, mode_override: str = "") -> dict[str, Any]:
    """跑一个完整周期：采集 → 读取 → 筛选 → 起草 → 入队。

    mode_override 可临时切换采集模式（list/search），供"手动补一次关键词扫描"用。
    """
    if store._state["cycle"].get("running"):
        return {"ok": False, "error": "已有采集周期在运行"}
    store._state["cycle"]["running"] = True
    store._state["cycle"]["last_error"] = ""
    store.save()
    try:
        cmd_config = dict(store.config)
        if mode_override in ("list", "search"):
            cmd_config["collect_mode"] = mode_override
        cmd = build_collect_command(cmd_config, store.platform)
        # 启用采集档时不向发送侧借 Cookie：那会把「读侧撞风控」直接传导到写侧，
        # 采集档用自己的档案登录（登录一次，之后存在它自己的 profile 里）。
        xhs_cookie = ""
        if store.platform == "xhs" and not _crawl_profile_env():
            xhs_cookie = await _xhs_crawl_cookie()
        env = _collect_env(store.platform, xhs_cookie)
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
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise RuntimeError(f"采集超时（>{timeout // 60}分钟），已终止") from exc

        rows, video_map = read_collected(comment_dir_for(store.platform), platform=store.platform)
        queued = await _queue_candidates(
            store,
            rows,
            video_map,
            max_candidates=int(store.config.get("max_new_candidates_per_cycle", 8)),
            auto_draft=bool(store.config.get("auto_draft", True)),
        )
        stats = store._state["stats"]
        stats["cycles"] += 1
        stats["collected_videos"] = len(video_map)
        stats["collected_comments"] = len(rows)
        stats["excluded"] += queued["funnel"]["excluded"]
        summary = {
            "ok": True,
            "videos": len(video_map),
            "comments": len(rows),
            **queued,
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
# 登录态（B 站 Cookie 缓存 / 小红书 CDP 提取）
# ---------------------------------------------------------------------------

async def _xhs_crawl_cookie() -> str:
    """小红书采集子进程的登录态：从本机已登录的 CDP 浏览器提取 Cookie。

    读侧（采集）与发送侧共用同一个浏览器档案，登录一次两边可用。
    """
    try:
        from .xhs_reply_sender import fetch_xhs_cookie

        return await fetch_xhs_cookie()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"小红书登录态不可用：{str(exc)[:160]}。"
            "请先启动带调试端口的浏览器并登录小红书，再启动采集"
        ) from exc


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
    # 只为触发副作用（headless 读档案 + 落盘 + 记录账号信息），返回值这里不用
    await refresh_bili_cookie()
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
# 已发回复的互动回采(点赞/被回复数——用户要看到自己回复的真实反馈)
# ---------------------------------------------------------------------------

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"


def _fetch_reply_engagement(cookie: str, oid: str, root: str, rpid: str) -> Optional[dict[str, Any]]:
    """查已发回复在B站的实时状态:like/rcount/是否被删/楼中楼预览。"""
    import httpx

    try:
        resp = httpx.get(
            "https://api.bilibili.com/x/v2/reply/reply",
            params={"type": 1, "oid": oid, "root": root, "pn": 1, "ps": 49},
            headers={"Cookie": cookie, "User-Agent": _UA, "Referer": "https://www.bilibili.com/"},
            timeout=15.0,
            trust_env=False,
        )
        d = resp.json()
        if d.get("code") != 0:
            return {"missing": True, "like": 0, "rcount": 0, "note": f"接口code={d.get('code')}", "subs": []}
        data = d.get("data") or {}

        def _pack(node: dict[str, Any]) -> dict[str, Any]:
            subs = [
                f"{(s.get('member') or {}).get('uname', '?')}:{(s.get('content') or {}).get('message', '')[:60]}"
                for s in (node.get("replies") or [])[:3]
            ]
            return {
                "missing": False,
                "like": int(node.get("like") or 0),
                "rcount": int(node.get("rcount") or 0),
                "subs": subs,
            }

        # 根评论：我们发的那条**就是**这个楼层的 root，不在 replies 里。
        # 实测（2026-11-11）：root=<rpid> 时 data["root"] 返回该评论本身，
        # 带 like/rcount；而 data["replies"] 是它下面的楼中楼，永远找不到自己。
        root_node = data.get("root") or {}
        if root_node and str(root_node.get("rpid")) == str(rpid):
            return _pack(root_node)
        for r in data.get("replies") or []:
            if str(r.get("rpid")) == str(rpid):
                return _pack(r)
        return {"missing": True, "like": 0, "rcount": 0, "note": "楼内未找到(可能被删/折叠)", "subs": []}
    except Exception:  # noqa: BLE001
        return None


async def refresh_sent_engagement(store: "AutomationStore") -> dict[str, Any]:
    """回采全部已发回复的互动:点赞/被回复数/楼中楼预览,写入条目并持久化。"""
    if store.platform != "bili":
        # 互动回采走 B 站 API；小红书侧暂无对应接口（发送即验，不额外读平台）
        return {"ok": False, "updated": 0, "with_activity": [], "error": "互动回采仅支持 B 站通道"}
    cookie = _cached_cookie()
    sent = [it for it in store._state["items"] if it.get("status") == "sent" and it.get("reply_id")]
    updated = 0
    with_activity: list[dict[str, Any]] = []
    for it in sent:
        if not cookie:
            break
        rpid = str(it.get("reply_id") or "")
        # 根评论自己就是所在楼层的 root，查它要 root=rpid；楼中楼回复才是 root=comment_id
        root = rpid if str(it.get("action") or "") == "hot_comment" else str(it.get("comment_id") or "")
        info = await asyncio.to_thread(
            _fetch_reply_engagement, cookie, str(it.get("video_id") or ""), root, rpid
        )
        if info is None:
            continue
        it["reply_like_count"] = info["like"]
        it["reply_rcount"] = info["rcount"]
        it["engagement_at"] = datetime.now().isoformat(timespec="seconds")
        if info.get("missing"):
            it["engagement_note"] = str(info.get("note") or "")[:60]
        else:
            it.pop("engagement_note", None)
        it["reply_sub_preview"] = info["subs"]
        updated += 1
        if info["like"] > 0 or info["rcount"] > 0:
            with_activity.append({"id": it["id"], "like": info["like"], "rcount": info["rcount"], "subs": info["subs"]})
        await asyncio.sleep(0.8)  # 温柔节拍,不枛阅读接口
    if updated:
        store.save()
    return {"ok": True, "updated": updated, "with_activity": with_activity}


# ---------------------------------------------------------------------------
# 发送循环
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlatformSendAdapter:
    """一个平台的受控发送差异点。

    2026-11-11 重构背景：小红书的 `_sender_tick_xhs` 与抖音的
    `_sender_tick_dy` 相似度 0.75（difflib 实测），骨架完全一致——
    硬校验 → 前置条件 → mark_sending → 发送 → mark_sent/failed →
    风控停损 → 飞书通知。按现状再接快手/微博/知乎/贴吧会变成 6 份拷贝。

    现在把「骨架」收在 `_run_sender_tick()` 里，平台只声明差异：
    - `name`：日志与通知文案用的中文名
    - `violations`：出站硬校验函数
    - `precondition`：发送前必须满足的条件（返回 None 表示通过）
    - `send`：实际发送函数（同步，会在 to_thread 里跑）
    - `needs_comment_url`：是否需要带 token 的评论直链
    """

    name: str
    violations: Callable[[str], list[str]]
    precondition: Optional[Callable[[dict[str, Any]], Optional[str]]]
    send: Callable[..., Any]
    needs_comment_url: bool = False


def _xhs_adapter() -> PlatformSendAdapter:
    from .xhs_reply_sender import send_xhs_reply

    def _precondition(item: dict[str, Any]) -> Optional[str]:
        # 带令牌的评论直链是定位评论的唯一可靠途径（直链无 token 会 404）
        if not str(item.get("comment_url") or "").strip():
            return "缺少带 xsec_token 的评论链接，无法受控回复；请重新采集该笔记"
        return None

    return PlatformSendAdapter(
        name="小红书",
        violations=xhs_draft_violations,
        precondition=_precondition,
        send=send_xhs_reply,
        needs_comment_url=True,
    )


def _dy_adapter() -> PlatformSendAdapter:
    from .dy_reply_sender import send_dy_reply

    def _precondition(item: dict[str, Any]) -> Optional[str]:
        # 抖音评论没有可定位的直链锚点（无 xsec_token 机制），
        # 在视频页评论区按「昵称+评论内容」定位；comment_url 非必需。
        if not str(item.get("video_id") or "").strip():
            return "缺少视频 id，无法定位评论区；请重新采集该视频"
        return None

    return PlatformSendAdapter(
        name="抖音",
        violations=dy_draft_violations,
        precondition=_precondition,
        send=send_dy_reply,
        needs_comment_url=False,
    )


async def _run_sender_tick(
    store: AutomationStore,
    item: dict[str, Any],
    adapter: PlatformSendAdapter,
) -> str:
    """通用受控发送：所有平台共用这一条路径。

    顺序不能变——硬校验必须在 mark_sending 之前（否则拦下的条目会卡在
    sending），停损必须在 mark_failed 之后（否则无法判断该不该暂停通道）。
    """
    # 根评论通道只有 B 站有接口。小红书/抖音走浏览器自动化，必须先滚动定位到
    # 某条具体评论才能回复——没有「直接在评论框发言」的流程。明确退回并说明，
    # 不能让它以「回复某条评论」的方式悄悄发出去（那发错了对象更糟）。
    if str(item.get("action") or "") == "hot_comment":
        item["status"] = "pending_review"
        item["note"] = f"{adapter.name}暂不支持发根评论（浏览器通道只能定位到具体评论后回复），请改手动发送或换 B 站"
        store.save()
        return f"条目退回待审（{adapter.name}不支持根评论）"

    # 发送前二次硬校验（防批准后改草稿/历史遗留条目绕过批准口校验）
    violations = adapter.violations(item.get("draft") or "")
    if violations:
        item["status"] = "pending_review"
        item.setdefault("lint_warnings", []).append("硬校验拦截：" + "、".join(violations))
        item["note"] = "发送前硬校验拦截，退回待审"
        store.save()
        return f"条目退回待审（{'、'.join(violations)}）"

    if adapter.precondition is not None:
        reason = adapter.precondition(item)
        if reason:
            item["status"] = "pending_review"
            item["note"] = reason
            store.save()
            # 回显一句短的定位原因（沿用旧文案，用户已熟悉）
            short = "缺评论直链" if adapter.needs_comment_url else reason[:16]
            return f"条目退回待审（{short}）"

    store.mark_sending(item)
    try:
        kwargs: dict[str, Any] = {
            "content_id": str(item.get("video_id") or ""),
            "comment_id": str(item.get("comment_id") or ""),
            "message": str(item.get("draft") or ""),
        }
        if adapter.name == "抖音":
            # 抖音按「昵称 + 评论原文」定位评论，必须带上
            kwargs["commenter"] = str(item.get("commenter") or "")
            kwargs["comment_text"] = str(item.get("comment_text") or "")
        else:
            kwargs["url"] = str(item.get("comment_url") or "")

        await asyncio.to_thread(adapter.send, **kwargs)
        store.mark_sent(item, "")
        store._state["sender"]["last_error"] = ""
        store.save()
        if not store.next_approved():
            if notify_mod.should_notify(
                store._state["sender"].setdefault("notified", {}), "queue_empty", "队列已清空"
            ):
                await notify_mod.notify(f"{adapter.name}发送队列已清空", ["所有已批准回复均已发送完毕"])
        return f"已发送 → {item.get('commenter', '')}（《{str(item.get('video_title') or '')[:20]}》）"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        store.mark_failed(item, msg)
        store._state["sender"]["last_error"] = msg[:200]
        store._state["sender"]["last_error_at"] = datetime.now().isoformat(timespec="seconds")
        store.save()
        # 停损：风控/登录类失败 → 暂停整条通道（默认 24h），到期自动恢复。
        # 被平台处理就停，而不是调参数继续撞——这是与「对抗风控」的本质区别。
        if any(k in msg for k in ("频繁", "限流", "敏感", "登录", "风控", "验证")):
            hours = float(store.config.get("sender_pause_hours", 24) or 0)
            if hours > 0:
                store.pause_sender(hours, f"发送撞风控：{msg[:80]}")
            if notify_mod.should_notify(
                store._state["sender"].setdefault("notified", {}), "risk_pause", msg[:120]
            ):
                await notify_mod.notify(
                    f"{adapter.name}发送已停损暂停",
                    [
                        f"原因:{msg[:160]}",
                        f"暂停 {hours:g} 小时后自动恢复；可在设置页查看通道状态",
                        "建议人工确认账号未被限流后再恢复",
                    ],
                )
        return f"发送失败：{msg[:120]}"


async def _sender_tick_xhs(store: AutomationStore, item: dict[str, Any]) -> str:
    """小红书发送：走通用 tick，差异在 _xhs_adapter()。"""
    return await _run_sender_tick(store, item, _xhs_adapter())


async def _sender_tick_dy(store: AutomationStore, item: dict[str, Any]) -> str:
    """抖音发送：走通用 tick，差异在 _dy_adapter()。"""
    return await _run_sender_tick(store, item, _dy_adapter())


async def _sender_tick(store: AutomationStore) -> str:
    # 登录窗口开启期间暂停发送:档案浏览器被占用,headless 刷新会撞锁
    if (store._state["sender"].get("login_flow") or {}).get("running"):
        return "扫码登录窗口开启中,发送暂停"
    ok, reason = store.can_send_now()
    if not ok:
        # P0-3:配额用尽/窗口外等重要节奏事件推飞书(节流:同文案 6h 一次)
        if "配额" in reason or "窗口" in reason:
            if notify_mod.should_notify(store._state["sender"].setdefault("notified", {}), "pace", reason):
                await notify_mod.notify("发送节奏提醒", [reason, "可在设置页查看发送通道状态"])
        return reason or "等待中"
    item = store.next_approved()
    if not item:
        return "无已批准待发条目"
    if store.platform == "xhs":
        return await _sender_tick_xhs(store, item)
    if store.platform == "dy":
        return await _sender_tick_dy(store, item)
    # Cookie 刷新需要独占 cdp_bili 档案，采集周期进行中不动浏览器，只发已缓存的
    cookie_cached = _cached_cookie()
    if not cookie_cached and store._state["cycle"].get("running"):
        return "采集进行中，Cookie 刷新延后"
    try:
        cookie = cookie_cached or await refresh_bili_cookie()
    except Exception as exc:  # noqa: BLE001
        # 错误必须可见：记录到 sender 状态，监工台展示;登录失效推飞书(节流)
        store._state["sender"]["last_error"] = str(exc)[:200]
        store._state["sender"]["last_error_at"] = datetime.now().isoformat(timespec="seconds")
        store.save()
        if notify_mod.should_notify(
            store._state["sender"].setdefault("notified", {}), "blocked", str(exc)[:120]
        ):
            await notify_mod.notify(
                "发送通道阻塞",
                [str(exc)[:160], "批准的回复在队列等待;去设置页「扫码恢复B站登录」"],
            )
        return f"发送阻塞：{str(exc)[:120]}"
    store.mark_sending(item)
    is_hot = str(item.get("action") or "") == "hot_comment"
    try:
        from .reply_sender import send_bilibili_reply

        reply_id = await asyncio.to_thread(
            send_bilibili_reply,
            content_id=item["video_id"],
            comment_id=item["comment_id"],
            message=item["draft"],
            cookie=cookie,
            # 根评论：B 站接口的 root/parent 都为 "0"（不挂在任何评论下）
            root_id="0" if is_hot else "",
        )
        store.mark_sent(item, reply_id)
        store._state["sender"]["last_error"] = ""
        store.save()
        # 队列清空即告知(节流 1h):全部发送完成
        if not store.next_approved():
            if notify_mod.should_notify(
                store._state["sender"].setdefault("notified", {}), "queue_empty", "队列已清空"
            ):
                await notify_mod.notify("发送队列已清空", ["所有已批准回复均已发送完毕"])
        if is_hot:
            return f"已发根评论（《{str(item.get('video_title') or '')[:20]}》）"
        return f"已发送 → {item['commenter']}（《{item['video_title'][:20]}》）"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        store.mark_failed(item, msg)
        # P0-3:发送失败/风控预警码推飞书(同条目同错误节流)
        risk = "风控预警:" if any(k in msg for k in ("折叠", "验证", "频繁", "限流")) else ""
        _target = (
            f"视频:《{str(item.get('video_title') or '')[:24]}》(根评论)"
            if is_hot
            else f"对象:{item['commenter']}《{item['video_title'][:24]}》"
        )
        if notify_mod.should_notify(
            store._state["sender"].setdefault("notified", {}), f"fail:{item['id']}", msg[:120]
        ):
            await notify_mod.notify(
                f"回复发送失败 {risk}".strip(),
                [
                    _target,
                    f"原因:{msg[:160]}",
                    f"状态:{item['status']}(重试 {item.get('attempts', 0)}/3)",
                ],
            )
        if "bili_jct" in msg or "Cookie" in msg:
            try:
                COOKIE_PATH.unlink()
            except OSError:
                pass
        return f"发送失败：{msg[:120]}"


# ---------------------------------------------------------------------------
# 后台任务
# ---------------------------------------------------------------------------

_stores: dict[str, AutomationStore] = {}
_tasks: list[asyncio.Task] = []
_stop_event: Optional[asyncio.Event] = None

logger = logging.getLogger(__name__)


def get_store(platform: str = "bili") -> AutomationStore:
    """按平台取自动化引擎实例（bili 用原 bili_reply.json，xhs 用 xhs_reply.json）。"""
    platform = platform if platform in PLATFORMS else "bili"
    if platform not in _stores:
        _stores[platform] = AutomationStore(path=store_path_for(platform), platform=platform)
    return _stores[platform]


async def automation_loop(stop: Optional[asyncio.Event] = None) -> None:
    """定时采集循环。

    `stop` 用于优雅关闭：lifespan 退出时置位，循环在下一轮边界退出，
    不会被直接 cancel 掉正在跑的采集。
    """
    while True:
        for platform in PLATFORMS:
            try:
                store = get_store(platform)
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
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # 原先是裸 `pass`：循环静默死掉也看不出来。至少留一条日志。
                logger.exception("[automation] 采集循环 %s 出错", platform)
        if stop is not None and stop.is_set():
            return
        await asyncio.sleep(60)


async def sender_loop(stop: Optional[asyncio.Event] = None) -> None:
    """定时发送循环（受 can_send_now 的窗口/配额/冷却约束）。"""
    while True:
        for platform in PLATFORMS:
            try:
                store = get_store(platform)
                if store.config.get("enabled"):
                    await _sender_tick(store)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("[automation] 发送循环 %s 出错", platform)
        if stop is not None and stop.is_set():
            return
        await asyncio.sleep(20)


def reconcile_stuck_sending(store: AutomationStore, *, older_than_hours: float = 1.0) -> int:
    """把卡在 `sending` 的条目救回来。

    2026-11-11 审计：`mark_sending()` 之后如果进程被杀/浏览器崩溃，
    条目会永远停在 `sending`——`next_approved()` 只挑 `approved`，
    funnel 又只统计 5 种状态，于是这条既发不出去、在 UI 里也看不见。
    这里在启动时把超时未完成的 sending 退回 `approved` 并标注原因。
    """
    recovered = 0
    now = datetime.now()
    with store.lock:
        for item in store.items:
            if item.get("status") != "sending":
                continue
            stamp = item.get("sending_at") or item.get("decided_at") or ""
            stale = True
            if stamp:
                try:
                    stale = (now - datetime.fromisoformat(stamp)).total_seconds() >= older_than_hours * 3600
                except ValueError:
                    stale = True
            if not stale:
                continue
            item["status"] = "approved"
            item["sending_at"] = ""
            item["note"] = "上次发送中断（进程退出/浏览器崩溃），已退回待发并计数重置"
            item["attempts"] = int(item.get("attempts", 0) or 0)
            recovered += 1
    if recovered:
        store.save()
    return recovered


def start_background_tasks() -> None:
    """启动后台循环（幂等）。lifespan 负责在退出时调用 stop_background_tasks()。"""
    global _stop_event
    if _tasks:
        return
    _stop_event = asyncio.Event()
    _tasks.append(asyncio.create_task(automation_loop(_stop_event)))
    _tasks.append(asyncio.create_task(sender_loop(_stop_event)))


async def stop_background_tasks(timeout: float = 5.0) -> None:
    """优雅关闭：先让循环在边界退出，超时才 cancel。"""
    global _stop_event
    if _stop_event is not None:
        _stop_event.set()
    tasks = list(_tasks)
    _tasks.clear()
    _stop_event = None
    if not tasks:
        return
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
