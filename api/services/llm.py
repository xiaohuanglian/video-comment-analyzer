# -*- coding: utf-8 -*-
"""LLM 网关统一调用入口(OpenAI 兼容)。

地址/密钥/模型从环境变量读取(参考 .env.example 与 run_web.sh 的 .env 加载);
内网网关必须 trust_env=False 避开系统代理。
"""

from __future__ import annotations

import os

import httpx

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")


def _unconfigured() -> RuntimeError:
    return RuntimeError(
        "LLM 网关未配置:请在 .env 或环境变量里设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL(参考 .env.example)"
    )


async def complete(
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    timeout: float = 90,
) -> str:
    """调 chat/completions,返回正文文本。失败抛异常。"""
    if not (LLM_BASE_URL and LLM_API_KEY and LLM_MODEL):
        raise _unconfigured()
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={"model": LLM_MODEL, "messages": messages, "temperature": temperature},
        )
        resp.raise_for_status()
        payload = resp.json()
    return (payload.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
