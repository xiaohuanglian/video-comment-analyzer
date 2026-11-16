# -*- coding: utf-8 -*-
"""Crawl guard 测试：错误码分类、跨进程平台冷却、平台并发槽位。"""

import asyncio

import pytest

import config
from tools import crawl_pacing as cp


@pytest.fixture(autouse=True)
def isolated_cooldowns(tmp_path):
    """每个测试独立的冷却状态文件，避免互相污染。"""
    cp.reset_cooldown_store(cp.CooldownStore(tmp_path / "cooldowns.json"))
    yield
    cp.reset_cooldown_store(None)


# ---------------------------------------------------------------------------
# 错误码分类
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc, expected",
    [
        (Exception("请求过于频繁，请稍后再试"), cp.RATE_LIMITED),
        (Exception("验证码校验失败"), cp.PLATFORM_BLOCKED),
        (Exception("blocked"), cp.PLATFORM_BLOCKED),
        (Exception("请先登录后再操作"), cp.NEED_LOGIN),
        (Exception("SESSDATA 已过期"), cp.NEED_LOGIN),
        (TimeoutError("read timeout"), cp.TIMEOUT),
        (Exception("Note not found"), cp.NOT_FOUND),
        (ValueError("params or payload is required"), cp.BAD_INPUT),
        (Exception("Executable doesn't exist at ..."), cp.NEED_SETUP),
        (RuntimeError("something unexpected"), cp.UPSTREAM_BROKEN),
    ],
)
def test_classify_failure_maps_to_actionable_code(exc, expected):
    assert cp.classify_failure(exc, platform="xhs").code == expected


def test_rate_limit_code_wins_over_message_patterns():
    # 平台返回的限流码优先判定，避免被其它关键词抢走
    failure = cp.classify_failure(code=-412, message="请先登录", platform="bili")
    assert failure.code == cp.RATE_LIMITED


def test_failure_envelope_shape():
    envelope = cp.failure_envelope("xhs", Exception("频率过快"))
    assert envelope["ok"] is False
    assert envelope["platform"] == "xhs"
    assert envelope["error"]["code"] == cp.RATE_LIMITED
    assert envelope["error"]["hint"] == cp.ERROR_HINTS[cp.RATE_LIMITED]


def test_every_code_has_a_hint():
    for code in (
        cp.RATE_LIMITED,
        cp.NEED_LOGIN,
        cp.PLATFORM_BLOCKED,
        cp.UPSTREAM_BROKEN,
        cp.TIMEOUT,
        cp.NOT_FOUND,
        cp.BAD_INPUT,
        cp.BUSY,
        cp.NEED_SETUP,
    ):
        assert cp.ERROR_HINTS.get(code)


# ---------------------------------------------------------------------------
# 平台冷却（落盘、跨进程）
# ---------------------------------------------------------------------------


def test_cooldown_survives_a_new_store(tmp_path):
    path = tmp_path / "cooldowns.json"
    cp.reset_cooldown_store(cp.CooldownStore(path))
    cp.record_platform_failure(
        "xhs", cp.CrawlFailure(cp.RATE_LIMITED, "太频繁", platform="xhs")
    )

    # 模拟"下一个进程"：只有磁盘上的状态
    cp.reset_cooldown_store(cp.CooldownStore(path))
    active = cp.platform_cooldown("xhs")
    assert active is not None
    assert active["code"] == cp.RATE_LIMITED
    assert 0 < active["retry_after_seconds"] <= 900


def test_ensure_platform_available_blocks_while_cooling(monkeypatch):
    monkeypatch.setattr(config, "CRAWL_GUARD_RATE_LIMIT_COOLDOWN_SEC", 120, raising=False)
    cp.record_platform_failure("xhs", cp.CrawlFailure(cp.RATE_LIMITED, "太频繁"))

    with pytest.raises(cp.CrawlBlocked) as excinfo:
        cp.ensure_platform_available("xhs")

    failure = excinfo.value.failure
    assert failure.code == cp.RATE_LIMITED
    assert failure.retry_after_seconds and failure.retry_after_seconds > 0
    assert "还需等待" in str(excinfo.value)


def test_cooldown_expires(monkeypatch):
    cp.record_platform_failure(
        "xhs", cp.CrawlFailure(cp.RATE_LIMITED, "太频繁"), cooldown_seconds=1
    )
    assert cp.platform_cooldown("xhs") is not None

    # 时间往前走，过期条目会被自动清掉
    real_time = cp.time.time
    monkeypatch.setattr(cp.time, "time", lambda: real_time() + 5)
    assert cp.platform_cooldown("xhs") is None
    assert cp.cooldown_store().snapshot() == {}


def test_per_run_config_changes_do_not_drop_cooldown(monkeypatch):
    """回归：CLI 每次都会按参数重设采集间隔，冷却必须仍然有效。

    早期版本把采集间隔掺进冷却指纹，导致"进程 A 限流、进程 B 照样开抓"，
    跨进程冷却形同虚设。
    """
    cp.record_platform_failure(
        "xhs", cp.CrawlFailure(cp.RATE_LIMITED, "太频繁"), cooldown_seconds=600
    )
    assert cp.platform_cooldown("xhs") is not None

    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 99, raising=False)
    monkeypatch.setattr(config, "ENABLE_SAFE_CRAWL_MODE", False, raising=False)
    assert cp.platform_cooldown("xhs") is not None


def test_state_version_bump_invalidates_cooldown(monkeypatch):
    cp.record_platform_failure(
        "xhs", cp.CrawlFailure(cp.RATE_LIMITED, "太频繁"), cooldown_seconds=600
    )
    monkeypatch.setattr(cp, "GUARD_STATE_VERSION", cp.GUARD_STATE_VERSION + 1)
    assert cp.platform_cooldown("xhs") is None


def test_clear_cooldown_after_recovery():
    cp.record_platform_failure(
        "xhs", cp.CrawlFailure(cp.RATE_LIMITED, "太频繁"), cooldown_seconds=600
    )
    cp.clear_platform_cooldown("xhs")
    assert cp.platform_cooldown("xhs") is None


def test_guard_disabled_records_nothing(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_CRAWL_GUARD", False, raising=False)
    cp.record_platform_failure(
        "xhs", cp.CrawlFailure(cp.RATE_LIMITED, "太频繁"), cooldown_seconds=600
    )
    assert cp.platform_cooldown("xhs") is None


def test_non_cooldown_codes_do_not_block_platform():
    # 参数错误/找不到内容不该把整个平台停掉
    cp.record_platform_failure("xhs", cp.CrawlFailure(cp.BAD_INPUT, "bad params"))
    cp.record_platform_failure("xhs", cp.CrawlFailure(cp.NOT_FOUND, "note gone"))
    assert cp.platform_cooldown("xhs") is None


def test_pacer_records_rate_limit_for_whole_platform(monkeypatch):
    # 验证配置时固定时钟，避免真实耗时跨秒令 42 变成 41。
    monkeypatch.setattr(cp.time, "time", lambda: 1_800_000_000.0)
    monkeypatch.setattr(config, "CRAWL_GUARD_RATE_LIMIT_COOLDOWN_SEC", 42, raising=False)
    pacer = cp.CrawlPacer("xhs")
    pacer.on_rate_limit()

    active = cp.platform_cooldown("xhs")
    assert active is not None
    assert active["code"] == cp.RATE_LIMITED
    assert active["retry_after_seconds"] == 42


def test_pacer_on_failure_classifies_and_records():
    pacer = cp.CrawlPacer("bili")
    failure = pacer.on_failure(Exception("请先登录后再操作"))
    assert failure.code == cp.NEED_LOGIN
    assert cp.platform_cooldown("bili") is not None


def test_before_request_never_raises_during_cooldown(monkeypatch):
    monkeypatch.setattr(config, "CRAWL_GUARD_WAIT_GRACE_SEC", 0, raising=False)
    cp.record_platform_failure(
        "xhs", cp.CrawlFailure(cp.RATE_LIMITED, "太频繁"), cooldown_seconds=600
    )

    # 抓取中途冷却只做软等待，不能抛异常打断已经拿到的进度
    asyncio.run(cp.CrawlPacer("xhs").before_request())


# ---------------------------------------------------------------------------
# 平台并发槽位
# ---------------------------------------------------------------------------


def test_per_platform_slot_caps_concurrency():
    slots = cp.PlatformSlots(per_platform=1, global_limit=4)
    peak = 0
    active = 0

    async def worker():
        nonlocal peak, active
        async with slots.acquire("xhs", timeout=5):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    async def runner():
        await asyncio.gather(*(worker() for _ in range(3)))

    asyncio.run(runner())
    assert peak == 1


def test_global_slot_caps_concurrency_across_platforms():
    slots = cp.PlatformSlots(per_platform=2, global_limit=1)
    peak = 0
    active = 0

    async def worker(platform):
        nonlocal peak, active
        async with slots.acquire(platform, timeout=5):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    async def runner():
        await asyncio.gather(worker("xhs"), worker("bili"), worker("dy"))

    asyncio.run(runner())
    assert peak == 1


def test_slot_is_reentrant_within_one_task():
    slots = cp.PlatformSlots(per_platform=1, global_limit=1)

    async def runner():
        async with slots.acquire("xhs", timeout=1):
            # 同一任务内嵌套取槽：不能自己把自己卡死
            async with slots.acquire("xhs", timeout=1):
                return "ok"

    assert asyncio.run(runner()) == "ok"


def test_slot_timeout_returns_busy_failure():
    slots = cp.PlatformSlots(per_platform=1, global_limit=1)

    async def runner():
        holding = asyncio.Event()

        async def holder():
            async with slots.acquire("xhs", timeout=1):
                holding.set()
                await asyncio.sleep(0.3)

        async def intruder():
            await holding.wait()
            try:
                async with slots.acquire("xhs", timeout=0.05):
                    return None
            except cp.CrawlBlocked as blocked:
                return blocked.failure

        holder_task = asyncio.create_task(holder())
        failure = await asyncio.create_task(intruder())
        await holder_task
        return failure

    failure = asyncio.run(runner())
    assert failure is not None
    assert failure.code == cp.BUSY
    assert failure.advice == cp.ERROR_HINTS[cp.BUSY]
