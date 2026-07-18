# -*- coding: utf-8 -*-
"""Crawl pacing helpers to reduce anti-bot triggers."""

from __future__ import annotations

import asyncio
import random
import re
from typing import Optional, Tuple

import config
from tools import utils

_RATE_LIMIT_CODES = {-799, -412, -352, 412, 429}
_RATE_LIMIT_PATTERN = re.compile(
    r"频繁|风控|过快|限制|拦截|稍后再试|操作太|try again|rate.?limit",
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


class CrawlPacer:
    """Adaptive delay between requests with jitter and backoff on rate limits."""

    def __init__(self, platform: str = ""):
        self.platform = platform
        self._multiplier = 1.0
        self._request_count = 0

    def on_rate_limit(self) -> float:
        max_mul = float(getattr(config, "ADAPTIVE_THROTTLE_MAX_MULTIPLIER", 6))
        self._multiplier = min(self._multiplier * 1.8, max_mul)
        cooldown = float(getattr(config, "BILI_RATE_LIMIT_COOLDOWN_SEC", 30))
        utils.logger.warning(
            f"[CrawlPacer] Rate limit detected, multiplier={self._multiplier:.1f}, "
            f"cooldown={cooldown:.0f}s"
        )
        return cooldown

    def on_success(self) -> None:
        if not getattr(config, "ENABLE_ADAPTIVE_THROTTLE", True):
            return
        if self._multiplier > 1.0:
            self._multiplier = max(1.0, self._multiplier * 0.85)

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
