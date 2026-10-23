# -*- coding: utf-8 -*-
"""Shared OpenAI-compatible client, usage and pricing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI


@dataclass
class LlmUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


def build_openai_client(base_url: str, api_key: str, feature: str = "insight"):
    kwargs: dict = {"api_key": api_key}
    if base_url.strip():
        kwargs["base_url"] = base_url.strip()
    return UsageRecordingClient(OpenAI(**kwargs), feature)


class _CompletionsProxy:
    """包住 chat.completions.create,同步/异步调用都记 token 用量到费用台账。"""

    def __init__(self, inner: Any, feature: str):
        self._inner = inner
        self._feature = feature

    def create(self, **kwargs: Any):
        import inspect
        import time as _time

        started = _time.monotonic()
        result = self._inner.create(**kwargs)
        if inspect.isawaitable(result):

            async def _wrapped():
                try:
                    resp = await result
                except Exception as e:  # noqa: BLE001
                    _record_call(self._feature, kwargs, started, ok=False, error=e)
                    raise
                _record_call(self._feature, kwargs, started, resp=resp)
                return resp

            return _wrapped()
        try:
            _record_call(self._feature, kwargs, started, resp=result)
        except Exception:  # noqa: BLE001
            pass
        return result

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class _ChatProxy:
    def __init__(self, inner: Any, feature: str):
        self._inner = inner
        # 公开属性:确保 chat.completions 访问到代理而不是透传到原始对象
        self.completions = _CompletionsProxy(inner.completions, feature)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class UsageRecordingClient:
    """OpenAI 客户端透明包装:除 chat.completions.create 记账外,其余行为完全一致。"""

    def __init__(self, inner: Any, feature: str):
        self._inner = inner
        self._feature = feature
        self.chat = _ChatProxy(inner.chat, feature)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def _record_call(
    feature: str,
    kwargs: dict,
    started: float,
    resp: Any = None,
    ok: bool = True,
    error: Exception | None = None,
) -> None:
    import time as _time

    from api.services import costs

    usage = parse_usage(getattr(resp, "usage", None)) if resp is not None else None
    costs.record(
        feature=feature,
        model=str(kwargs.get("model") or getattr(resp, "model", "") or ""),
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        duration_ms=int((_time.monotonic() - started) * 1000),
        ok=ok,
        error=f"{type(error).__name__}: {error}" if error else "",
    )


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
