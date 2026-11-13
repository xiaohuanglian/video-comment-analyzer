# -*- coding: utf-8 -*-
"""LLM 网关配置的唯一解析入口。

为什么要有它（2026-11-11 审计）：
项目里原先有**两套互不兼容**的 base URL 约定：

- `api/services/llm.py` 直接拼 `f"{LLM_BASE_URL}/v1/chat/completions"`，
  期望环境变量里**不带** `/v1`；
- `growth/model_settings.py` 的 `normalize_base_url()` 会**补上** `/v1`，
  并按这个形式持久化到 `data/model_settings.json`。

于是同一份配置换个来源就会变成 `.../ai-router/v1/v1/chat/completions`。
另外 `llm.complete`（chat / 选题 / 写稿 / 质检 / 回复起草全走它）只读环境变量，
不回落服务端保存的配置，导致「设置页保存了模型，大部分功能仍然无效」。

现在的口径：
1. `normalize_base_url()` 统一成「根地址」，**不含** `/v1`；
2. `resolve_llm_config()` 按 显式入参 → 环境变量 → 服务端持久化 的顺序回落；
3. `chat_completions_url()` 负责拼端点，保证只会出现一个 `/v1`。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


def normalize_base_url(url: str) -> str:
    """归一成「根地址」，去掉结尾的 `/v1` 与多余斜杠。

    >>> normalize_base_url("https://gw.example.com/ai-router/v1/")
    'https://gw.example.com/ai-router'
    """
    value = (url or "").strip().rstrip("/")
    if not value:
        return ""
    # 只剥结尾那一层 /v1，中间的 /v1/ 不动（网关可能真的有这层路径）
    if value.endswith("/v1"):
        value = value[: -len("/v1")].rstrip("/")
    return value


def chat_completions_url(base_url: str) -> str:
    """拼 chat/completions 端点，保证只有一个 `/v1`。"""
    root = normalize_base_url(base_url) or normalize_base_url(DEFAULT_BASE_URL)
    return f"{root}/v1/chat/completions"


@dataclass(frozen=True)
class LlmConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @property
    def endpoint(self) -> str:
        return chat_completions_url(self.base_url)

    def as_dict(self) -> Dict[str, str]:
        return {"base_url": self.base_url, "api_key": self.api_key, "model": self.model}


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _stored() -> Dict[str, str]:
    """读服务端持久化的模型配置；读不到/损坏都不算致命。"""
    try:
        from api.services.growth import model_settings

        data = model_settings.load_model_settings()
    except Exception:  # noqa: BLE001 - 配置缺失不该拦住请求
        return {}
    return {
        "base_url": (data.get("base_url") or "").strip(),
        "api_key": (data.get("api_key") or "").strip(),
        "model": (data.get("model_name") or "").strip(),
    }


def resolve_llm_config(
    *,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    use_stored: bool = True,
) -> LlmConfig:
    """按 入参 → 环境变量 → 持久化配置 的顺序解析，返回归一化后的配置。

    `use_stored=False` 用于「只认本次请求」的严格场景（如验证用户刚填的 key）。
    """
    stored = _stored() if use_stored else {}
    resolved_base = (
        (base_url or "").strip()
        or _env("LLM_BASE_URL")
        or stored.get("base_url", "")
        or DEFAULT_BASE_URL
    )
    resolved_key = (api_key or "").strip() or _env("LLM_API_KEY") or stored.get("api_key", "")
    resolved_model = (model or "").strip() or _env("LLM_MODEL") or stored.get("model") or DEFAULT_MODEL
    return LlmConfig(
        base_url=normalize_base_url(resolved_base),
        api_key=resolved_key,
        model=resolved_model,
    )


def masked(config: LlmConfig) -> Dict[str, Any]:
    """脱敏展示用，**永远不要**返回明文 key。"""
    key = config.api_key
    return {
        "base_url": config.base_url,
        "model": config.model,
        "configured": config.configured,
        "api_key_masked": f"sk-****{key[-4:]}" if len(key) >= 8 else ("****" if key else ""),
    }


def optional_config(**kwargs: Any) -> Optional[LlmConfig]:
    """没配 key 时返回 None（调用方据此给「未配置」提示而不是抛 500）。"""
    config = resolve_llm_config(**kwargs)
    return config if config.api_key else None


def require_llm_api_key(api_key: str = "") -> str:
    """解析**这次请求**真正能用的 key：入参 → 环境变量 → 服务端持久化。

    为什么要有它（2026-11-13）：洞察各路由原先只认 `body.api_key`，而前端
    从来不收集 key（它就该不收集），于是在设置页明明配好了模型、点「开始分析」
    仍然 400「真实 API 分析需要填写 API Key」。模型网关的唯一解析入口是
    `resolve_llm_config()`，这里只是把它套一层，**不要**在各路由里另写回落。
    """
    return (api_key or "").strip() or resolve_llm_config().api_key
