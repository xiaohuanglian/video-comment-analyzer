# -*- coding: utf-8 -*-
"""小红书搜索的次数预算：治「一口气问 12 个词」，不只是治间隔。

## 为什么加这个

2026-11-11 事故里，「间隔 3 秒」只是表象。真正的问题是**行为形态**：
一个真人不会在 40 秒里连问 12 个不相关的话题（刷手机无聊 → 信息过载 →
播客推荐 → AI资讯 → 独处 → 专注力 → 信息焦虑）。真人要么一次问一个，
要么隔一阵再来。

间隔拉长（``XHS_SEARCH_SLEEP_SEC`` 45 秒）能降低速率，但「一天问 12 个词」
这个量级本身仍然不像人。所以再加一层**日预算 + 单批上限**：

- ``XHS_SEARCH_DAILY_LIMIT``：一天最多几次搜索，跨进程计数（落盘）。
- ``XHS_MAX_KEYWORDS_PER_BATCH``：单次命令最多几个关键词，超出直接拒绝。

预算文件与平台冷却放在同一个目录（``cache/crawl_guard/``，已 gitignore），
这样「看冷却」和「看今天还能搜几次」在同一个地方。

## 用在哪

``scripts/xhs_keyword_notes.py``（纯搜索）、以及任何以 search 接口为主的入口。
**detail/feed 型采集不走这套**：那是"看已知内容"，不是"主动搜库"。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import config

#: 预算文件默认与 crawl guard 同目录
_DEFAULT_STATE_DIR = "./cache/crawl_guard"
_BUDGET_FILE = "xhs_search_budget.json"


class SearchBudgetExceeded(RuntimeError):
    """今天的搜索额度用完 / 单批关键词太多。带上人话和还需等待时长。"""

    def __init__(self, message: str, *, retry_after_seconds: Optional[float] = None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class QuietHoursActive(SearchBudgetExceeded):
    """现在是夜里，采集不该开工。

    单列一个子类只为让上层能说人话（「现在是夜间静默时段」而不是「额度不够」）；
    调用方 ``except SearchBudgetExceeded`` 依然能统一接住。
    """


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _state_dir() -> Path:
    raw = os.environ.get("CRAWL_GUARD_STATE_DIR") or getattr(
        config, "CRAWL_GUARD_STATE_DIR", _DEFAULT_STATE_DIR
    )
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = _project_root() / path
    return path


def daily_search_limit() -> int:
    return max(1, int(getattr(config, "XHS_SEARCH_DAILY_LIMIT", 6)))


def max_keywords_per_batch() -> int:
    return max(1, int(getattr(config, "XHS_MAX_KEYWORDS_PER_BATCH", 4)))


def _today() -> str:
    return time.strftime("%Y-%m-%d")


@dataclass
class SearchBudget:
    """一天内已经用掉的搜索次数（跨进程，落盘）。"""

    path: Optional[Path] = None

    def __post_init__(self) -> None:
        if self.path is None:
            self.path = _state_dir() / _BUDGET_FILE

    # -- 存储 --

    def _load(self) -> dict:
        try:
            data = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        try:
            path = Path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            # 预算文件写不了不该让采集本身报错；最坏情况是下次少算一次
            pass

    # -- 读写 --

    def used_today(self) -> int:
        data = self._load()
        if str(data.get("date") or "") != _today():
            return 0
        try:
            return max(0, int(data.get("used") or 0))
        except (TypeError, ValueError):
            return 0

    def remaining_today(self) -> int:
        return max(0, daily_search_limit() - self.used_today())

    def consume(self, count: int = 1) -> Tuple[int, int]:
        """记一次（或 n 次）搜索，返回 ``(今日已用, 今日上限)``。"""
        data = self._load()
        if str(data.get("date") or "") != _today():
            data = {"date": _today(), "used": 0}
        used = max(0, int(data.get("used") or 0)) + max(0, int(count))
        data["used"] = used
        data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._save(data)
        return used, daily_search_limit()

    def reset(self) -> None:
        self._save({"date": _today(), "used": 0, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")})


_STORE: Optional[SearchBudget] = None


def search_budget() -> SearchBudget:
    global _STORE
    if _STORE is None:
        _STORE = SearchBudget()
    return _STORE


def reset_search_budget(budget: Optional[SearchBudget] = None) -> None:
    """测试/切换状态目录时重建单例。"""
    global _STORE
    _STORE = budget


def plan_keywords(
    keywords: list[str],
    *,
    max_per_batch: Optional[int] = None,
    today: Optional[str] = None,
) -> Tuple[list[str], list[str]]:
    """把一整串关键词切成「这一批该搜的」与「留到下一批的」。

    为什么要切：单批上限是硬约束（一次问太多话题本身就是机器人特征），
    但配置里通常有 9 个词。如果永远只取前 N 个，后面的词就永远轮不到。

    所以按**日期**轮转起点：第 1 天从第 0 个开始，第 2 天从第 N 个开始……
    这样每天搜的词不同，总量仍然受日预算约束。返回 ``(本批, 被推迟的)``。
    """
    items = [str(k).strip() for k in keywords if str(k).strip()]
    if not items:
        return [], []
    limit = max(1, int(max_per_batch if max_per_batch is not None else max_keywords_per_batch()))
    if len(items) <= limit:
        return items, []
    stamp = today or _today()
    try:
        ordinal = int(time.strftime("%j", time.strptime(stamp, "%Y-%m-%d")))
    except (ValueError, TypeError):
        ordinal = 0
    start = (ordinal * limit) % len(items)
    rotated = items[start:] + items[:start]
    return rotated[:limit], rotated[limit:]


def ensure_batch_allowed(keyword_count: int) -> None:
    """批前硬检查：单批关键词数 + 今日剩余额度，任一不足就拒绝开工。

    在**发第一个请求之前**拒绝，而不是跑到一半才发现没额度——后半截被砍掉
    等于白打了几次请求，反而不如一次都不打。
    """
    limit = max_keywords_per_batch()
    if keyword_count > limit:
        raise SearchBudgetExceeded(
            f"一次最多搜 {limit} 个关键词（本次 {keyword_count} 个）。"
            f"小红书风控最敏感的就是连续搜索，请拆成多批、隔一段时间再来。",
        )
    remaining = search_budget().remaining_today()
    if remaining < keyword_count:
        raise SearchBudgetExceeded(
            f"今天的搜索额度不够：还剩 {remaining} 次，本次要 {keyword_count} 次"
            f"（每日上限 {daily_search_limit()} 次）。明天再来，或减少关键词。",
            retry_after_seconds=_seconds_until_tomorrow(),
        )


def _seconds_until_tomorrow() -> float:
    """距离本地时间明天 0 点还有多少秒（额度是按自然日重置的）。"""
    now = time.localtime()
    tomorrow = time.mktime(
        (
            now.tm_year,
            now.tm_mon,
            now.tm_mday + 1,
            0,
            0,
            0,
            0,
            0,
            -1,
        )
    )
    return max(0.0, tomorrow - time.time())


# ---------------------------------------------------------------------------
# 夜间静默
# ---------------------------------------------------------------------------


def quiet_hours() -> Tuple[int, int]:
    """返回 ``(开始小时, 结束小时)``，读配置，默认 01:00–06:00。"""
    start = int(getattr(config, "XHS_QUIET_HOURS_START", 1)) % 24
    end = int(getattr(config, "XHS_QUIET_HOURS_END", 6)) % 24
    return start, end


def in_quiet_hours(now: Optional[float] = None) -> bool:
    """现在是不是夜间静默时段。

    用「真人要睡觉」这条最朴素的拟人化：凌晨三点爬起来搜六个不相关话题的
    账号，和白天通勤时顺手搜一下的账号，风险不是一个量级。间隔、预算都治
    不了「作息」这一个维度。

    支持跨零点（``23 → 7``）。起止相同视为不启用。
    """
    start, end = quiet_hours()
    if start == end:
        return False
    stamp = time.localtime(now if now is not None else time.time())
    hour = stamp.tm_hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def seconds_until_quiet_end(now: Optional[float] = None) -> float:
    """距离静默结束还有多少秒（用于告诉人「几小时后可以来」）。"""
    start, end = quiet_hours()
    if start == end:
        return 0.0
    current = now if now is not None else time.time()
    stamp = time.localtime(current)
    target = time.mktime(
        (stamp.tm_year, stamp.tm_mon, stamp.tm_mday, end, 0, 0, 0, 0, -1)
    )
    if target <= current:
        target += 86400
    return max(0.0, target - current)


def ensure_not_quiet_hours(now: Optional[float] = None) -> None:
    """夜间开工前硬拦；白天什么都不做。

    放在批前检查里而不是 ``ensure_batch_allowed`` 里，是为了让额度相关的测试
    与运行时刻无关：额度是确定性的，作息不是。两个入口各自显式调用它。
    """
    if not in_quiet_hours(now):
        return
    start, end = quiet_hours()
    wait = seconds_until_quiet_end(now)
    raise QuietHoursActive(
        f"现在是夜间静默时段（{start:02d}:00–{end:02d}:00），采集不在这时开工。"
        f"真人不会凌晨三点爬起来搜六个不相关的话题——这正是最容易被判定为机器人的行为。"
        f"约 {format_seconds(wait)}后（{end:02d}:00）再来。",
        retry_after_seconds=wait,
    )


def format_seconds(seconds: float) -> str:
    """把秒数说成人话：``3 小时 12 分``。"""
    try:
        total = int(max(0, round(float(seconds))))
    except (TypeError, ValueError):
        return "0 分钟"
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours} 小时 {minutes} 分"
    if hours:
        return f"{hours} 小时"
    if minutes:
        return f"{minutes} 分钟"
    return f"{total} 秒"
