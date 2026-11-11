# -*- coding: utf-8 -*-
"""Crawl pacing + crawl guard helpers.

分两层：

1. **Pacing（进程内）**：请求间隔抖动、批量暂停、限流后的自适应退避（原有行为）。
2. **Crawl guard（跨进程）**：
   - 把失败分类成**可执行的错误码**，而不是裸异常；
   - 平台冷却状态**落盘**，下一次采集（新进程、新任务）仍然生效；
   - 平台并发槽位，给同一平台的并发请求数设上限。

三者遵守同一条约定：失败要说清 ``code / message / hint / retry_after_seconds``，
调用方（人、Web 面板、Agent）按 code 决定下一步，而不是猜异常类型。

冷却带**指纹**：配置改变（比如切换安全模式、调整间隔）后旧冷却自动失效，
避免上一次运行得出的结论把新配置锁死。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Set, Tuple

import config
from tools import utils

#: 采集进程因"平台冷却中"被拦下时的退出码（Web 面板据此给出还需等待多久）
BLOCKED_EXIT_CODE = 3

#: 冷却状态格式版本。语义变更（比如改了 entry 字段）才改它，改一次等于作废所有旧冷却。
GUARD_STATE_VERSION = 2

# ---------------------------------------------------------------------------
# 错误码
# ---------------------------------------------------------------------------

RATE_LIMITED = "RATE_LIMITED"
NEED_LOGIN = "NEED_LOGIN"
PLATFORM_BLOCKED = "PLATFORM_BLOCKED"
UPSTREAM_BROKEN = "UPSTREAM_BROKEN"
TIMEOUT = "TIMEOUT"
NOT_FOUND = "NOT_FOUND"
BAD_INPUT = "BAD_INPUT"
BUSY = "BUSY"
NEED_SETUP = "NEED_SETUP"

#: 每个错误码对应一句"下一步该干什么"，供面板/命令行/Agent 直接展示。
ERROR_HINTS: Dict[str, str] = {
    RATE_LIMITED: "平台限流：等冷却结束再抓，不要立刻换账号、换代理或换接口重试。",
    NEED_LOGIN: "登录态失效：重新登录该平台后再抓（tools/login_helper.py）。",
    PLATFORM_BLOCKED: "平台风控/验证码拦截：到官方页面人工处理，暂停该平台采集。",
    UPSTREAM_BROKEN: "上游接口或页面结构变了：先人工核对，再决定是否更新采集实现。",
    TIMEOUT: "请求超时：多为网络或平台变慢，稍后重试，不要连续重试。",
    NOT_FOUND: "目标内容不存在或已删除：核对链接 / ID。",
    BAD_INPUT: "参数不合法：检查输入后重试。",
    BUSY: "该平台并发已满：排队等待，或等当前任务结束再试。",
    NEED_SETUP: "缺少依赖或配置（浏览器 / 代理 / Cookie）：补齐后重试。",
}

#: 哪些错误码会把整个平台标记为冷却，以及冷却多久（配置键，默认秒数）。
_COOLDOWN_CONFIG: Dict[str, Tuple[str, float]] = {
    RATE_LIMITED: ("CRAWL_GUARD_RATE_LIMIT_COOLDOWN_SEC", 900.0),
    PLATFORM_BLOCKED: ("CRAWL_GUARD_BLOCKED_COOLDOWN_SEC", 1800.0),
    NEED_LOGIN: ("CRAWL_GUARD_BLOCKED_COOLDOWN_SEC", 1800.0),
    UPSTREAM_BROKEN: ("CRAWL_GUARD_UPSTREAM_COOLDOWN_SEC", 300.0),
    TIMEOUT: ("CRAWL_GUARD_TIMEOUT_COOLDOWN_SEC", 120.0),
}

_RATE_LIMIT_CODES = {-799, -412, -352, 412, 429}
_RATE_LIMIT_PATTERN = re.compile(
    r"频繁|风控|过快|限制|拦截|稍后再试|操作太|try again|rate.?limit",
    re.I,
)
_LOGIN_PATTERN = re.compile(
    r"未登录|请登录|请先登录|登录已|登录失效|登录过期|重新登录|无权限|"
    r"\blogin\b|\blogged out\b|not logged in|unauthori[sz]ed|token (?:expired|invalid)|"
    r"sessdata|401",
    re.I,
)
_BLOCKED_PATTERN = re.compile(
    r"captcha|verifytype|verifyuuid|验证码|人机验证|滑块|账号异常|"
    r"account blocked|\bblocked\b|ip.?block|拒绝访问|forbidden",
    re.I,
)
_UPSTREAM_PATTERN = re.compile(
    r"playwright|selector|target closed|browser has been closed|"
    r"decode json|unreadable|空页面|页面结构",
    re.I,
)
_NOT_FOUND_PATTERN = re.compile(r"not.?found|不存在|已删除|404", re.I)
#: 缺本地依赖（没装浏览器内核等）——这是"补东西就能好"，不是"上游坏了"
_SETUP_PATTERN = re.compile(
    r"executable doesn't exist|playwright install|not installed|"
    r"missing dependenc|no such file or directory",
    re.I,
)


def is_rate_limited(code: Optional[int], message: str = "") -> bool:
    if code in _RATE_LIMIT_CODES:
        return True
    return bool(message and _RATE_LIMIT_PATTERN.search(message))


def compute_crawl_interval(platform: str = "") -> Tuple[float, float]:
    """Return (base_seconds, jitter_seconds) for crawl pacing."""
    base = float(getattr(config, "CRAWLER_MAX_SLEEP_SEC", 2))
    jitter = float(getattr(config, "CRAWLER_SLEEP_JITTER_SEC", 0))

    if getattr(config, "ENABLE_SAFE_CRAWL_MODE", False):
        base = max(base, 3.0)
        jitter = max(jitter, 1.5)

    if platform == "bili":
        bili_base = float(getattr(config, "BILI_CRAWL_SLEEP_SEC", base))
        bili_jitter = float(getattr(config, "BILI_CRAWL_SLEEP_JITTER_SEC", jitter))
        if getattr(config, "ENABLE_SAFE_CRAWL_MODE", False):
            base = max(base, bili_base)
            jitter = max(jitter, bili_jitter)

    return base, jitter


# ---------------------------------------------------------------------------
# 失败结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrawlFailure:
    """一次采集失败的完整描述：错误码 + 原话 + 下一步 + 还需等多久。"""

    code: str
    message: str = ""
    platform: str = ""
    hint: str = ""
    retry_after_seconds: Optional[int] = None

    @property
    def advice(self) -> str:
        return self.hint or ERROR_HINTS.get(self.code, "")

    def to_dict(self) -> dict:
        """统一信封：``{"ok": False, "platform": ..., "error": {...}}``。"""
        return {
            "ok": False,
            "platform": self.platform,
            "error": {
                "code": self.code,
                "message": self.message,
                "hint": self.advice,
                "retry_after_seconds": self.retry_after_seconds,
            },
        }

    def to_text(self) -> str:
        """给人看的一行话。"""
        parts = [f"[{self.code}]"]
        if self.platform:
            parts.append(f"{self.platform}:")
        parts.append(self.message or self.advice)
        if self.retry_after_seconds:
            parts.append(f"（还需等待 {format_duration(self.retry_after_seconds)}）")
        if self.advice and self.advice not in (self.message or ""):
            parts.append(f"→ {self.advice}")
        return " ".join(parts)


class CrawlBlocked(RuntimeError):
    """采集被 guard 拦下（平台冷却中 / 并发已满）。携带结构化 failure。"""

    def __init__(self, failure: CrawlFailure):
        self.failure = failure
        super().__init__(failure.to_text())


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {sec} 秒" if sec else f"{minutes} 分钟"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分" if minutes else f"{hours} 小时"


def classify_failure(
    exc: Optional[BaseException] = None,
    *,
    platform: str = "",
    code: Optional[int] = None,
    message: Optional[str] = None,
) -> CrawlFailure:
    """把任意异常/响应映射成一个 CrawlFailure。

    分类顺序有意义：先看限流（平台明确说了"太频繁"），再看风控验证，
    再看登录、超时、不存在、上游结构、参数，最后兜底为 UPSTREAM_BROKEN
    ——兜底不选"未知/其他"，是因为未知错误对调用方没有行动价值。
    """
    text = message if message is not None else (str(exc) if exc is not None else "")
    text = text or ""
    name = type(exc).__name__ if exc is not None else ""

    def make(failure_code: str) -> CrawlFailure:
        return CrawlFailure(
            code=failure_code,
            message=text.strip()[:400],
            platform=platform,
            hint=ERROR_HINTS.get(failure_code, ""),
        )

    if is_rate_limited(code, f"{name} {text}"):
        return make(RATE_LIMITED)
    if _BLOCKED_PATTERN.search(f"{name} {text}"):
        return make(PLATFORM_BLOCKED)
    if _LOGIN_PATTERN.search(f"{name} {text}"):
        return make(NEED_LOGIN)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timeout" in f"{name} {text}".lower():
        return make(TIMEOUT)
    if _NOT_FOUND_PATTERN.search(f"{name} {text}"):
        return make(NOT_FOUND)
    if _SETUP_PATTERN.search(f"{name} {text}"):
        return make(NEED_SETUP)
    if _UPSTREAM_PATTERN.search(f"{name} {text}"):
        return make(UPSTREAM_BROKEN)
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return make(BAD_INPUT)
    return make(UPSTREAM_BROKEN)


# ---------------------------------------------------------------------------
# 平台冷却（落盘、跨进程）
# ---------------------------------------------------------------------------


def guard_enabled() -> bool:
    return bool(getattr(config, "ENABLE_CRAWL_GUARD", True))


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _state_dir() -> Path:
    raw = os.environ.get("CRAWL_GUARD_STATE_DIR") or getattr(
        config, "CRAWL_GUARD_STATE_DIR", "./cache/crawl_guard"
    )
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = _project_root() / path
    return path


def platform_fingerprint(platform: str) -> str:
    """冷却指纹：只跟"状态格式版本 + 平台"有关。

    这里**不能**掺进每跑一次都会被改写的参数（采集间隔、安全模式、平台开关，
    CLI 每次都会按参数重设它们），否则进程 A 记录的冷却在进程 B 里会被
    判成"过期结论"而失效——跨进程冷却就白做了。要作废旧冷却就改
    ``GUARD_STATE_VERSION``，或显式 ``clear_platform_cooldown``。
    """
    return sha1(f"{platform}|{GUARD_STATE_VERSION}".encode("utf-8")).hexdigest()[:12]


def _cooldown_seconds(code: str) -> float:
    key, default = _COOLDOWN_CONFIG.get(code, ("", 0.0))
    if not key:
        return 0.0
    try:
        return float(getattr(config, key, default))
    except (TypeError, ValueError):
        return default


class CooldownStore:
    """按平台记录冷却状态的小状态文件（原子写，读坏了自己修）。"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else _state_dir() / "cooldowns.json"

    # -- 存储层 --

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": 1, "platforms": {}}
        if not isinstance(data, dict):
            return {"version": 1, "platforms": {}}
        platforms = data.get("platforms")
        if not isinstance(platforms, dict):
            data["platforms"] = {}
        data.setdefault("version", 1)
        return data

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:  # 状态文件写不了不该让采集本身失败
            utils.logger.warning(f"[CrawlGuard] Cannot write cooldown state {self.path}: {exc}")

    # -- 读写 --

    def snapshot(self) -> Dict[str, dict]:
        return dict(self._load().get("platforms") or {})

    def record(self, platform: str, failure: CrawlFailure, *, cooldown_seconds: Optional[float] = None) -> Optional[dict]:
        if not platform:
            return None
        cooldown = float(cooldown_seconds) if cooldown_seconds is not None else _cooldown_seconds(failure.code)
        if cooldown <= 0:
            self.clear(platform)
            return None
        entry = {
            "code": failure.code,
            "message": failure.message[:400],
            "platform": platform,
            "at": time.time(),
            "retry_after_seconds": int(round(cooldown)),
            "fingerprint": platform_fingerprint(platform),
        }
        data = self._load()
        data.setdefault("platforms", {})[platform] = entry
        self._save(data)
        utils.logger.warning(
            f"[CrawlGuard] {platform} 进入冷却 {format_duration(cooldown)}（{failure.code}）"
        )
        return entry

    def active(self, platform: str) -> Optional[dict]:
        """还在冷却中就返回剩余信息，否则返回 None（顺手清掉过期条目）。"""
        if not platform:
            return None
        entry = self.snapshot().get(platform)
        if not isinstance(entry, dict):
            return None
        if entry.get("fingerprint") and entry["fingerprint"] != platform_fingerprint(platform):
            self.clear(platform)
            return None
        try:
            remaining = float(entry.get("retry_after_seconds") or 0) - (time.time() - float(entry.get("at") or 0))
        except (TypeError, ValueError):
            self.clear(platform)
            return None
        if remaining <= 0:
            self.clear(platform)
            return None
        active = dict(entry)
        active["retry_after_seconds"] = int(round(remaining))
        active["cooldown_seconds"] = entry.get("retry_after_seconds")
        return active

    def clear(self, platform: str) -> None:
        if not platform:
            return
        data = self._load()
        platforms = data.get("platforms") or {}
        if platform in platforms:
            platforms.pop(platform, None)
            data["platforms"] = platforms
            self._save(data)


_STORE: Optional[CooldownStore] = None


def cooldown_store() -> CooldownStore:
    global _STORE
    if _STORE is None:
        _STORE = CooldownStore()
    return _STORE


def reset_cooldown_store(store: Optional[CooldownStore] = None) -> None:
    """测试/切换状态目录时重建单例。"""
    global _STORE
    _STORE = store


def platform_cooldown(platform: str) -> Optional[dict]:
    if not guard_enabled():
        return None
    return cooldown_store().active(platform)


def record_platform_failure(
    platform: str,
    failure: Any,
    *,
    cooldown_seconds: Optional[float] = None,
) -> Optional[dict]:
    """记录一次失败并可能让整个平台进入冷却。failure 可传异常或 CrawlFailure。"""
    if not guard_enabled():
        return None
    if not isinstance(failure, CrawlFailure):
        failure = classify_failure(failure, platform=platform)
    if not platform:
        return None
    return cooldown_store().record(platform, failure, cooldown_seconds=cooldown_seconds)


def clear_platform_cooldown(platform: str) -> None:
    if platform:
        cooldown_store().clear(platform)


def ensure_platform_available(platform: str) -> None:
    """采集任务**开始前**的硬检查：平台在冷却中就抛 CrawlBlocked。"""
    active = platform_cooldown(platform)
    if not active:
        return
    raise CrawlBlocked(
        CrawlFailure(
            code=str(active.get("code") or "RATE_LIMITED"),
            message=str(active.get("message") or ""),
            platform=platform,
            hint=ERROR_HINTS.get(str(active.get("code") or ""), ""),
            retry_after_seconds=active.get("retry_after_seconds"),
        )
    )


def failure_envelope(platform: str, failure: Any) -> dict:
    """给 API / CLI 用的失败信封。"""
    if not isinstance(failure, CrawlFailure):
        failure = classify_failure(failure, platform=platform)
    return failure.to_dict()


# ---------------------------------------------------------------------------
# 平台并发槽位
# ---------------------------------------------------------------------------


@dataclass
class _LoopState:
    per_platform: int
    global_limit: int
    global_sem: asyncio.Semaphore
    platform_sems: Dict[str, asyncio.Semaphore] = field(default_factory=dict)
    held: Dict[str, Set[Any]] = field(default_factory=dict)

    def sem(self, platform: str) -> asyncio.Semaphore:
        sem = self.platform_sems.get(platform)
        if sem is None:
            sem = asyncio.Semaphore(self.per_platform)
            self.platform_sems[platform] = sem
        return sem


class PlatformSlots:
    """同一平台最多 N 条并发、全局最多 M 条并发；超时返回 BUSY。

    槽位按事件循环隔离（测试里多个 ``asyncio.run`` 不会互相污染），
    并且**可重入**：同一任务内嵌套取槽不会自己把自己卡死。
    """

    def __init__(self, per_platform: Optional[int] = None, global_limit: Optional[int] = None):
        self._per_platform = per_platform
        self._global_limit = global_limit
        self._states: "weakref.WeakKeyDictionary[Any, _LoopState]" = weakref.WeakKeyDictionary()

    def limits(self) -> Tuple[int, int]:
        per = self._per_platform or int(getattr(config, "CRAWL_MAX_CONCURRENCY_PER_PLATFORM", 2))
        total = self._global_limit or int(getattr(config, "CRAWL_MAX_CONCURRENCY_GLOBAL", 4))
        return max(1, per), max(1, total)

    def _state(self) -> _LoopState:
        loop = asyncio.get_running_loop()
        state = self._states.get(loop)
        if state is None:
            per, total = self.limits()
            state = _LoopState(per_platform=per, global_limit=total, global_sem=asyncio.Semaphore(total))
            self._states[loop] = state
        return state

    async def _acquire(self, sem: asyncio.Semaphore, wait: float, platform: str) -> None:
        try:
            await asyncio.wait_for(sem.acquire(), wait)
        except asyncio.TimeoutError:
            raise CrawlBlocked(
                CrawlFailure(
                    code=BUSY,
                    message=f"{platform or '全部平台'} 并发已满：等待超过 {wait:.0f}s",
                    platform=platform,
                    hint=ERROR_HINTS[BUSY],
                )
            ) from None

    @asynccontextmanager
    async def acquire(self, platform: str = "", timeout: Optional[float] = None) -> AsyncIterator[None]:
        state = self._state()
        task = asyncio.current_task()
        held = state.held.setdefault(platform, set())
        if task is not None and task in held:  # 重入
            yield
            return

        wait = float(timeout if timeout is not None else getattr(config, "CRAWL_SLOT_WAIT_SEC", 120))
        got_global = got_platform = False
        platform_sem = state.sem(platform)
        try:
            await self._acquire(state.global_sem, wait, platform)
            got_global = True
            await self._acquire(platform_sem, wait, platform)
            got_platform = True
            if task is not None:
                held.add(task)
            try:
                yield
            finally:
                if task is not None:
                    held.discard(task)
        finally:
            if got_platform:
                platform_sem.release()
            if got_global:
                state.global_sem.release()


_SLOTS: Optional[PlatformSlots] = None


def platform_slots() -> PlatformSlots:
    global _SLOTS
    if _SLOTS is None:
        _SLOTS = PlatformSlots()
    return _SLOTS


def platform_slot(platform: str = "", timeout: Optional[float] = None):
    """``async with platform_slot("xhs"): ...``"""
    return platform_slots().acquire(platform, timeout)


# ---------------------------------------------------------------------------
# 进程内调节器
# ---------------------------------------------------------------------------


class CrawlPacer:
    """Adaptive delay between requests with jitter and backoff on rate limits.

    同时负责把失败写进跨进程的平台冷却（``record_platform_failure``）。
    """

    def __init__(self, platform: str = ""):
        self.platform = platform
        self._multiplier = 1.0
        self._request_count = 0

    # -- guard 前置检查 --

    def cooldown_remaining(self) -> float:
        active = platform_cooldown(self.platform)
        if not active:
            return 0.0
        return float(active.get("retry_after_seconds") or 0)

    async def before_request(self) -> None:
        """请求前看一眼平台冷却。

        这里**不抛异常**：任务是用户已经决定要跑的，中途抛错会把已抓到的
        进度打断；正确做法是按 ``CRAWL_GUARD_WAIT_GRACE_SEC`` 最多等一小段
        再继续，真正的硬阻断放在任务开始前（``ensure_platform_available``）。
        """
        remaining = self.cooldown_remaining()
        if remaining <= 0:
            return
        grace = float(getattr(config, "CRAWL_GUARD_WAIT_GRACE_SEC", 20))
        wait = min(remaining, grace)
        if wait <= 0:
            utils.logger.warning(
                f"[CrawlPacer] {self.platform} 仍在冷却（剩余 {format_duration(remaining)}），跳过等待"
            )
            return
        utils.logger.warning(
            f"[CrawlPacer] {self.platform} 冷却中（剩余 {format_duration(remaining)}），先等 {wait:.0f}s"
        )
        await asyncio.sleep(wait)

    # -- 失败/成功 --

    def on_rate_limit(self) -> float:
        max_mul = float(getattr(config, "ADAPTIVE_THROTTLE_MAX_MULTIPLIER", 6))
        self._multiplier = min(self._multiplier * 1.8, max_mul)
        cooldown = float(getattr(config, "BILI_RATE_LIMIT_COOLDOWN_SEC", 30))
        utils.logger.warning(
            f"[CrawlPacer] Rate limit detected, multiplier={self._multiplier:.1f}, "
            f"cooldown={cooldown:.0f}s"
        )
        record_platform_failure(
            self.platform,
            CrawlFailure(
                code=RATE_LIMITED,
                message=f"{self.platform} 限流（自适应节流 ×{self._multiplier:.1f}）",
                platform=self.platform,
                hint=ERROR_HINTS[RATE_LIMITED],
            ),
        )
        return cooldown

    def on_failure(self, exc: BaseException) -> CrawlFailure:
        """分类并记录；返回结构化失败，调用方可以继续抛或写进任务结果。"""
        failure = classify_failure(exc, platform=self.platform)
        record_platform_failure(self.platform, failure)
        return failure

    def on_success(self) -> None:
        if not getattr(config, "ENABLE_ADAPTIVE_THROTTLE", True):
            return
        if self._multiplier > 1.0:
            self._multiplier = max(1.0, self._multiplier * 0.85)

    # -- 等待 --

    async def sleep(self, reason: str = "") -> None:
        if not getattr(config, "ENABLE_ADAPTIVE_THROTTLE", True):
            base, jitter = compute_crawl_interval(self.platform)
        else:
            base, jitter = compute_crawl_interval(self.platform)
            base *= self._multiplier

        delay = base + (random.uniform(0, jitter) if jitter > 0 else 0)
        self._request_count += 1

        batch_every = int(getattr(config, "CRAWLER_PAGE_BATCH_PAUSE_EVERY", 0))
        if batch_every > 0 and self._request_count % batch_every == 0:
            extra = float(getattr(config, "CRAWLER_PAGE_BATCH_PAUSE_SEC", 8))
            if self.platform == "bili":
                extra = max(extra, float(getattr(config, "BILI_COMMENT_EXTRA_PAUSE_SEC", 10)))
            delay += extra
            utils.logger.info(
                f"[CrawlPacer] Batch pause +{extra:.1f}s after {self._request_count} requests"
            )

        if reason:
            utils.logger.debug(f"[CrawlPacer] Sleeping {delay:.2f}s ({reason})")
        await asyncio.sleep(delay)

    async def sleep_on_error(self, attempt: int, rate_limited: bool = False) -> None:
        if rate_limited and getattr(config, "ENABLE_ADAPTIVE_THROTTLE", True):
            cooldown = self.on_rate_limit()
            await asyncio.sleep(cooldown + random.uniform(0, 3))
            return
        delay = (5 * (2**attempt)) + random.uniform(0, 2)
        await asyncio.sleep(delay)
