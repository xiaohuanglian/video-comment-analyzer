# -*- coding: utf-8 -*-
"""OpenAI-compatible JSON analysis for comment insight (no Instructor schema overhead)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from .prompts import SYSTEM_PROMPT, build_user_message
from .result_cache import content_fingerprint, get_cached_analysis, put_cached_analysis
from .schemas import CommentAnalysisLLMOutput, CommentAnalysisResult, RunConfig, SourceRecord


@dataclass
class LlmUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


@dataclass
class LlmAnalysisResponse:
    analysis: CommentAnalysisResult
    usage: LlmUsage
    from_cache: bool = False


def build_openai_client(base_url: str, api_key: str):
    kwargs: dict = {"api_key": api_key}
    if base_url.strip():
        kwargs["base_url"] = base_url.strip()
    return OpenAI(**kwargs)


# Backward-compatible alias for tests and older imports.
build_instructor_client = build_openai_client


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
        (miss / 1000) * input_price + (hit / 1000) * hit_price + (completion_tokens / 1000) * output_price,
        6,
    )


def analyze_record_llm(
    record: SourceRecord,
    config: RunConfig,
    api_key: str,
    *,
    client=None,
) -> LlmAnalysisResponse:
    if not api_key.strip():
        raise ValueError("缺少 API Key，请在页面填写（不会写入磁盘）")
    if not config.model_name.strip():
        raise ValueError("缺少模型名称")

    fingerprint = content_fingerprint(record)
    cached = get_cached_analysis(fingerprint)
    if cached is not None:
        cached.record_id = record.internal_record_id
        return LlmAnalysisResponse(analysis=cached, usage=LlmUsage(), from_cache=True)

    llm_client = client or build_openai_client(config.base_url, api_key)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(record)},
    ]

    total_usage = LlmUsage()
    last_error: Exception | None = None
    max_attempts = 2
    for attempt in range(max_attempts):
        completion = llm_client.chat.completions.create(
            model=config.model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        usage = parse_usage(getattr(completion, "usage", None))
        total_usage.prompt_tokens += usage.prompt_tokens
        total_usage.completion_tokens += usage.completion_tokens
        total_usage.prompt_cache_hit_tokens += usage.prompt_cache_hit_tokens
        total_usage.prompt_cache_miss_tokens += usage.prompt_cache_miss_tokens
        raw_content = completion.choices[0].message.content or ""
        try:
            payload = json.loads(raw_content)
            llm_output = CommentAnalysisLLMOutput.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            last_error = exc
            if attempt + 1 < max_attempts:
                messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            f"上次输出无法解析（{type(exc).__name__}）。"
                            "请只返回符合字段要求的 JSON 对象；"
                            "help_seeking 必须是 true 或 false，不能是字符串或数组。"
                        ),
                    }
                ]
            continue

        analysis = CommentAnalysisResult(
            record_id=record.internal_record_id,
            **llm_output.model_dump(),
        )
        put_cached_analysis(fingerprint, analysis)
        return LlmAnalysisResponse(analysis=analysis, usage=total_usage, from_cache=False)

    raise ValueError(f"LLM 返回 JSON 无法解析: {last_error}")
