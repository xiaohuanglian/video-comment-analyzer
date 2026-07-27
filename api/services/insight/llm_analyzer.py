# -*- coding: utf-8 -*-
"""Shared OpenAI-compatible client, usage and pricing helpers."""

from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI


@dataclass
class LlmUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


def build_openai_client(base_url: str, api_key: str):
    kwargs: dict = {"api_key": api_key}
    if base_url.strip():
        kwargs["base_url"] = base_url.strip()
    return OpenAI(**kwargs)


def parse_usage(raw_usage) -> LlmUsage:
    usage = LlmUsage()
    if raw_usage is None:
        return usage
    usage.prompt_tokens = int(getattr(raw_usage, "prompt_tokens", 0) or 0)
    usage.completion_tokens = int(getattr(raw_usage, "completion_tokens", 0) or 0)
    usage.prompt_cache_hit_tokens = int(getattr(raw_usage, "prompt_cache_hit_tokens", 0) or 0)
    usage.prompt_cache_miss_tokens = int(getattr(raw_usage, "prompt_cache_miss_tokens", 0) or 0)
    if usage.prompt_cache_hit_tokens <= 0 and usage.prompt_tokens > 0:
        details = getattr(raw_usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) if details is not None else None
        if cached:
            usage.prompt_cache_hit_tokens = int(cached)
            usage.prompt_cache_miss_tokens = max(0, usage.prompt_tokens - usage.prompt_cache_hit_tokens)
    elif usage.prompt_cache_miss_tokens <= 0 and usage.prompt_tokens > 0:
        usage.prompt_cache_miss_tokens = max(0, usage.prompt_tokens - usage.prompt_cache_hit_tokens)
    return usage


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    *,
    input_price: float,
    output_price: float,
    prompt_cache_hit_tokens: int = 0,
    input_price_cache_hit: float = 0.0,
) -> float:
    """Prices are CNY per 1K tokens. Input can split cache hit vs miss (DeepSeek V4)."""
    hit = max(0, min(prompt_cache_hit_tokens, prompt_tokens))
    miss = max(0, prompt_tokens - hit)
    hit_price = input_price_cache_hit if input_price_cache_hit > 0 else input_price * 0.02
    return round(
        (miss / 1000) * input_price
        + (hit / 1000) * hit_price
        + (completion_tokens / 1000) * output_price,
        6,
    )
