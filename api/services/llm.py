# -*- coding: utf-8 -*-
"""LLM 网关统一调用入口(OpenAI 兼容)。

配置从 `api.services.llm_config.resolve_llm_config()` 解析：
请求入参 → 环境变量(LLM_BASE_URL / LLM_API_KEY / LLM_MODEL) → 服务端持久化配置。
`run_web.sh` 会加载 .env；设置页保存的配置走持久化回落。

2026-11-11 审计修复：原实现直接读模块级环境变量并硬拼 `/v1/chat/completions`，
既不会回落持久化配置，又和 `model_settings.normalize_base_url()` 的约定冲突
（后者会补 `/v1`，两人一起来就得到 `.../v1/v1/chat/completions`）。
内网网关必须 trust_env=False 避开系统代理。
"""

from __future__ import annotations

import time

import httpx

from api.services.llm_config import LlmConfig, resolve_llm_config


def _unconfigured() -> RuntimeError:
    return RuntimeError(
        "LLM 网关未配置:请在 .env 或设置页填写 Base URL / API Key / Model(参考 .env.example)"
    )


async def complete(
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    timeout: float = 90,
    feature: str = "unknown",
    *,
    config: LlmConfig | None = None,
) -> str:
    """调 chat/completions,返回正文文本。失败抛异常。每次调用计入费用台账。

    `config` 允许调用方复用已解析的配置（避免每次调用都重读磁盘）。
    """
    from api.services import costs

    resolved = config or resolve_llm_config()
    if not resolved.configured:
        raise _unconfigured()

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.post(
                resolved.endpoint,
                headers={"Authorization": f"Bearer {resolved.api_key}"},
                json={
                    "model": resolved.model,
                    "messages": messages,
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as e:  # noqa: BLE001
        costs.record(
            feature=feature,
            model=resolved.model,
            duration_ms=int((time.monotonic() - started) * 1000),
            ok=False,
            error=f"{type(e).__name__}: {e}",
        )
        raise
    usage = payload.get("usage") or {}
    costs.record(
        feature=feature,
        model=resolved.model,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return (payload.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
