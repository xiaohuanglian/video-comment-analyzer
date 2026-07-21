# -*- coding: utf-8 -*-
"""Run performance / cost metrics for evidence-agent extractions."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PerformanceMetrics:
    started_at: str = ""
    finished_at: str = ""
    elapsed_seconds: float = 0.0
    processed: int = 0
    failed: int = 0
    cache_hits: int = 0
    format_failures: int = 0
    splits: int = 0
    batch_count: int = 0
    batch_size: int = 20
    concurrency: int = 1
    requests_count: int = 0
    retry_count: int = 0
    comments_per_minute: float = 0.0
    average_batch_latency: float = 0.0
    p50_batch_latency: float = 0.0
    p95_batch_latency: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    actual_cost: Optional[float] = None
    currency: str = "CNY"
    model_name: str = ""
    batch_latencies: List[float] = field(default_factory=list)

    def mark_start(self) -> None:
        self.started_at = _utc_now()

    def add_batch_latency(self, seconds: float) -> None:
        self.batch_latencies.append(max(0.0, float(seconds)))
        self.batch_count = len(self.batch_latencies)

    def finalize(
        self,
        *,
        processed: int,
        failed: int,
        cache_hits: int,
        format_failures: int,
        splits: int,
        retry_count: int,
        requests_count: int,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit_tokens: int = 0,
        batch_size: int = 20,
        concurrency: int = 1,
        model_name: str = "",
        input_price: Optional[float] = None,
        output_price: Optional[float] = None,
        input_price_cache_hit: Optional[float] = None,
        currency: str = "CNY",
    ) -> Dict[str, Any]:
        self.finished_at = _utc_now()
        if self.started_at:
            try:
                start = datetime.fromisoformat(self.started_at)
                end = datetime.fromisoformat(self.finished_at)
                self.elapsed_seconds = max(0.0, (end - start).total_seconds())
            except ValueError:
                self.elapsed_seconds = 0.0
        self.processed = processed
        self.failed = failed
        self.cache_hits = cache_hits
        self.format_failures = format_failures
        self.splits = splits
        self.retry_count = retry_count
        self.requests_count = requests_count
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.cache_hit_tokens = cache_hit_tokens
        self.batch_size = batch_size
        self.concurrency = concurrency
        self.model_name = model_name
        self.currency = currency
        if self.elapsed_seconds > 0 and processed > 0:
            self.comments_per_minute = round(processed / (self.elapsed_seconds / 60.0), 2)
        if self.batch_latencies:
            self.average_batch_latency = round(statistics.mean(self.batch_latencies), 3)
            self.p50_batch_latency = round(statistics.median(self.batch_latencies), 3)
            sorted_lat = sorted(self.batch_latencies)
            idx = min(len(sorted_lat) - 1, max(0, int(round(0.95 * (len(sorted_lat) - 1)))))
            self.p95_batch_latency = round(sorted_lat[idx], 3)
        if input_price is not None and output_price is not None and (input_price > 0 or output_price > 0):
            hit = max(0, min(cache_hit_tokens, prompt_tokens))
            miss = max(0, prompt_tokens - hit)
            hit_price = input_price_cache_hit if input_price_cache_hit and input_price_cache_hit > 0 else input_price * 0.02
            self.actual_cost = round(
                (miss / 1000) * input_price + (hit / 1000) * hit_price + (completion_tokens / 1000) * output_price,
                6,
            )
        else:
            self.actual_cost = None
        return self.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("batch_latencies", None)
        return payload
