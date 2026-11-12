# -*- coding: utf-8 -*-
"""采集侧的行为约束：夜间静默 + 搜索配额（按平台）。

## 为什么单独一个模块

这套东西原来是 ``tools/xhs_safety.py``，名字里带 xhs，但里面的两条规则
——「真人要睡觉」「一天不能问太多不相关的话题」——跟平台无关。抖音最终
要和小红书接同一套约束，如果继续从 ``xhs_safety`` 里 import，日后没人敢改
那个文件（一改就怕碰坏小红书）。所以把规则改成按平台取配置，模块名去掉平台。

``tools/xhs_safety.py`` 保留为兼容门面，老代码（以及测试）的行文不用动。

## 两条规则分别治什么

- **间隔**（``tools/crawl_pacing.py``）只治「多快」，治不了「问几个」和「几点问」。
- **配额**治「一天问几个」：一个真人不会在 40 秒里连问 12 个不相关话题，
  也不会一天问 30 次。
- **夜间静默**治「几点」：凌晨三点爬起来搜六个词的账号，是最容易被判成
  机器人的行为形态——它跟签名、UA 都没关系，就是作息。

配额与静默都在**发第一个请求之前**拒绝，而不是跑到一半才发现：后半截被砍掉
等于白打了几次请求，反而不如一次都不打。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import config

_DEFAULT_STATE_DIR = "./cache/crawl_guard"

#: 各平台的默认值（配置里没写时用）。xhs 的 6/4 来自 2026-11-11 事故复盘；
#: dy 收紧到 4/3，因为抖音只能用同一个登录态、且搜索接口比 detail 敏感得多。
_DEFAULT_DAILY_LIMIT = {"xhs": 6, "dy": 4}
_DEFAULT_BATCH_LIMIT = {"xhs": 4, "dy": 3}


class SearchBudgetExceeded(RuntimeError):
    """今天的额度用完 / 单批关键词太多 / 现在是夜间。

    带上人话和还需等待时长，让面板能直接显示「几小时后再来」。
    """

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


def _norm(platform: str) -> str:
    return (platform or getattr(config, "PLATFORM", "") or "xhs").strip().lower()


def _budget_file(platform: str) -> str:
    # 沿用 xhs 的历史文件名，改名会把开发机上已有的额度记到「0 次」重开。
    return f"{platform}_search_budget.json"


def daily_search_limit(platform: str = "xhs") -> int:
    platform = _norm(platform)
    default = _DEFAULT_DAILY_LIMIT.get(platform, 4)
    return max(1, int(getattr(config, f"{platform.upper()}_SEARCH_DAILY_LIMIT", default)))


def max_keywords_per_batch(platform: str = "xhs") -> int:
    platform = _norm(platform)
    default = _DEFAULT_BATCH_LIMIT.get(platform, 3)
    return max(1, int(getattr(config, f"{platform.upper()}_MAX_KEYWORDS_PER_BATCH", default)))


def _today() -> str:
    return time.strftime("%Y-%m-%d")


@dataclass
class SearchBudget:
    """一天内已经用掉的搜索次数（跨进程，落盘）。"""

    path: Optional[Path] = None
    platform: str = "xhs"

    def __post_init__(self) -> None:
        self.platform = _norm(self.platform)
        if self.path is None:
            self.path = _state_dir() / _budget_file(self.platform)

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
        return max(0, daily_search_limit(self.platform) - self.used_today())

    def consume(self, count: int = 1) -> Tuple[int, int]:
        """记一次（或 n 次）搜索，返回 ``(今日已用, 今日上限)``。"""
        data = self._load()
        if str(data.get("date") or "") != _today():
            data = {"date": _today(), "used": 0}
        used = max(0, int(data.get("used") or 0)) + max(0, int(count))
        data["used"] = used
        data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data["platform"] = self.platform
        self._save(data)
        return used, daily_search_limit(self.platform)

    def reset(self) -> None:
        self._save(
            {
                "date": _today(),
                "used": 0,
                "platform": self.platform,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )


_STORES: Dict[str, SearchBudget] = {}


def search_budget(platform: str = "xhs") -> SearchBudget:
    platform = _norm(platform)
    if platform not in _STORES:
        _STORES[platform] = SearchBudget(platform=platform)
    return _STORES[platform]


def reset_search_budget(budget: Optional[SearchBudget] = None) -> None:
    """测试/切换状态目录时重建单例；传 ``None`` 清空所有平台的单例。"""
    if budget is None:
        _STORES.clear()
        return
    _STORES[_norm(budget.platform)] = budget


def plan_keywords(
    keywords: list[str],
    *,
    max_per_batch: Optional[int] = None,
    today: Optional[str] = None,
    platform: str = "xhs",
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
    limit = max(
        1,
        int(
            max_per_batch
            if max_per_batch is not None
            else max_keywords_per_batch(platform)
        ),
    )
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


def ensure_batch_allowed(keyword_count: int, *, platform: str = "xhs") -> None:
    """批前硬检查：单批关键词数 + 今日剩余额度，任一不足就拒绝开工。

    在**发第一个请求之前**拒绝，而不是跑到一半才发现没额度——后半截被砍掉
    等于白打了几次请求，反而不如一次都不打。
    """
    platform = _norm(platform)
    limit = max_keywords_per_batch(platform)
    if keyword_count > limit:
        raise SearchBudgetExceeded(
            f"一次最多搜 {limit} 个关键词（本次 {keyword_count} 个）。"
            f"连续搜索是平台风控最敏感的动作，请拆成多批、隔一段时间再来。",
        )
    remaining = search_budget(platform).remaining_today()
    if remaining < keyword_count:
        raise SearchBudgetExceeded(
            f"今天的搜索额度不够：还剩 {remaining} 次，本次要 {keyword_count} 次"
            f"（每日上限 {daily_search_limit(platform)} 次）。明天再来，或减少关键词。",
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


def quiet_hours(platform: str = "xhs") -> Tuple[int, int]:
    """返回 ``(开始小时, 结束小时)``。

    读取顺序：``<平台>_QUIET_HOURS_*`` → 通用 ``QUIET_HOURS_*`` → 默认 01:00–06:00。
    两边相等视为关闭（比如 ``0, 0``）。
    """
    platform = _norm(platform)
    prefix = platform.upper()
    start = int(
        getattr(
            config,
            f"{prefix}_QUIET_HOURS_START",
            getattr(config, "QUIET_HOURS_START", 1),
        )
    ) % 24
    end = int(
        getattr(
            config,
            f"{prefix}_QUIET_HOURS_END",
            getattr(config, "QUIET_HOURS_END", 6),
        )
    ) % 24
    return start, end


def in_quiet_hours(now: Optional[float] = None, *, platform: str = "xhs") -> bool:
    """现在是不是夜间静默时段。

    用「真人要睡觉」这条最朴素的拟人化：凌晨三点爬起来搜六个不相关话题的
    账号，和白天通勤时顺手搜一下的账号，风险不是一个量级。间隔、预算都治
    不了「作息」这一个维度。

    支持跨零点（``23 → 7``）。起止相同视为不启用。
    """
    start, end = quiet_hours(platform)
    if start == end:
        return False
    stamp = time.localtime(now if now is not None else time.time())
    hour = stamp.tm_hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def seconds_until_quiet_end(now: Optional[float] = None, *, platform: str = "xhs") -> float:
    """距离静默结束还有多少秒（用于告诉人「几小时后可以来」）。"""
    start, end = quiet_hours(platform)
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


def ensure_not_quiet_hours(now: Optional[float] = None, *, platform: str = "xhs") -> None:
    """夜间开工前硬拦；白天什么都不做。

    放在批前检查里而不是 ``ensure_batch_allowed`` 里，是为了让额度相关的测试
    与运行时刻无关：额度是确定性的，作息不是。各入口各自显式调用它。
    """
    if not in_quiet_hours(now, platform=platform):
        return
    start, end = quiet_hours(platform)
    wait = seconds_until_quiet_end(now, platform=platform)
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
