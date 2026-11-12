# -*- coding: utf-8 -*-
"""知乎接入采集防护：平台节奏 + 平台冷却。

背景（2026-11-12）：知乎这条链路原来**完全裸奔**——每请求固定 `sleep 3s`、
没有平台冷却、没有并发槽，403 只抛 `ForbiddenError` 不记账。
用户在问"会不会被封"时才查出来。这个文件把补上的防护锁住。
"""

import pytest

import config
from media_platform.zhihu.core import ZhihuCrawler
from tools import crawl_pacing as cp


@pytest.fixture
def isolated_cooldowns(tmp_path):
    cp.reset_cooldown_store(cp.CooldownStore(tmp_path / "cooldowns.json"))
    yield cp.cooldown_store()
    cp.reset_cooldown_store(None)


def test_zhihu_pacing_override_is_wired(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_SAFE_CRAWL_MODE", True)
    base, jitter = cp.compute_crawl_interval("zhihu")
    assert (base, jitter) == (8.0, 4.0)


def test_zhihu_pacing_is_slower_than_generic(monkeypatch):
    """通用值是给 B 站调的 3s；知乎的风控比它敏感，不能被通用值兜住。"""
    monkeypatch.setattr(config, "ENABLE_SAFE_CRAWL_MODE", True)
    generic = float(getattr(config, "CRAWLER_MAX_SLEEP_SEC", 2))
    base, _ = cp.compute_crawl_interval("zhihu")
    assert base > generic


def test_zhihu_registered_as_platform():
    assert "zhihu" in cp._PLATFORM_PACING
    base_key, jitter_key = cp._PLATFORM_PACING["zhihu"]
    assert hasattr(config, base_key) and hasattr(config, jitter_key)


def test_pace_interval_uses_platform_config(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_SAFE_CRAWL_MODE", True)
    # base + jitter/2 = 8 + 2
    assert ZhihuCrawler._pace_interval() == pytest.approx(10.0)


def test_zhihu_403_like_failure_blocks_next_run(isolated_cooldowns):
    """记一次 PLATFORM_BLOCKED 之后，下一次启动前就该被 `ensure_platform_available` 拦下。"""
    cp.record_platform_failure(
        "zhihu",
        cp.CrawlFailure(code="PLATFORM_BLOCKED", message="知乎返回 403", platform="zhihu"),
    )
    with pytest.raises(cp.CrawlBlocked):
        cp.ensure_platform_available("zhihu")


def test_core_records_failure_instead_of_swallowing():
    """静态保证：core 里确实接了记账，而不是只抛异常（原来就是这样漏的）。"""
    import inspect

    source = inspect.getsource(__import__("media_platform.zhihu.core", fromlist=["x"]))
    assert "record_platform_failure" in source
    assert "ensure_platform_available" in source
    # 固定 3 秒的老写法不该再出现在真正会跑的分支里（注释里提到可以）
    executable = [
        line
        for line in source.splitlines()
        if "asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)" in line and not line.strip().startswith("#")
    ]
    assert not executable
