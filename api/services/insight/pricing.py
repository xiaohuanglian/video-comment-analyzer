# -*- coding: utf-8 -*-
"""Provider pricing presets — users should not type token prices manually."""

from __future__ import annotations

from typing import Dict

# CNY per 1K tokens (V4 list prices ≈ USD $0.14/$0.0028 miss/hit input, $0.28 output @ ~7.2 FX)
PROVIDER_PRESETS: Dict[str, Dict[str, object]] = {
    "deepseek": {
        "label": "DeepSeek V4-Flash",
        "input_price": 0.001,
        "input_price_cache_hit": 0.00002,
        "output_price": 0.002,
        "currency": "CNY",
    },
    "deepseek_pro": {
        "label": "DeepSeek V4-Pro",
        "input_price": 0.003,
        "input_price_cache_hit": 0.000026,
        "output_price": 0.006,
        "currency": "CNY",
    },
    "openai": {
        "label": "OpenAI",
        "input_price": 0.025,
        "input_price_cache_hit": 0.0025,
        "output_price": 0.075,
        "currency": "CNY",
    },
    "moonshot": {
        "label": "Moonshot / Kimi",
        "input_price": 0.012,
        "input_price_cache_hit": 0.0012,
        "output_price": 0.012,
        "currency": "CNY",
    },
    "siliconflow": {
        "label": "SiliconFlow",
        "input_price": 0.001,
        "input_price_cache_hit": 0.00002,
        "output_price": 0.002,
        "currency": "CNY",
    },
    "generic": {
        "label": "通用估算",
        "input_price": 0.002,
        "input_price_cache_hit": 0.0002,
        "output_price": 0.006,
        "currency": "CNY",
    },
}

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"

MODEL_ALIASES = {
    "deepseek-chat": "deepseek-v4-flash（非思考模式，推荐）",
    "deepseek-reasoner": "deepseek-v4-flash（思考模式，更贵更慢）",
    "deepseek-v4-flash": "DeepSeek V4-Flash",
    "deepseek-v4-pro": "DeepSeek V4-Pro（贵约 3×，非必要勿用）",
}


def model_display_name(model_name: str) -> str:
    key = (model_name or "").strip().lower()
    return str(MODEL_ALIASES.get(key, model_name or DEFAULT_MODEL))


def detect_provider(base_url: str, model_name: str = "") -> str:
    haystack = f"{base_url} {model_name}".lower()
    if "deepseek" in haystack:
        if "pro" in model_name.lower() or "reasoner" in model_name.lower():
            return "deepseek_pro" if "pro" in model_name.lower() else "deepseek"
        return "deepseek"
    if "openai" in haystack or "api.openai.com" in haystack:
        return "openai"
    if "moonshot" in haystack or "kimi" in haystack:
        return "moonshot"
    if "siliconflow" in haystack:
        return "siliconflow"
    return "generic"


def resolve_pricing(base_url: str, model_name: str = "") -> Dict[str, object]:
    provider = detect_provider(base_url, model_name)
    preset = PROVIDER_PRESETS[provider]
    return {
        "provider": provider,
        "provider_label": preset["label"],
        "input_price": float(preset["input_price"]),
        "input_price_cache_hit": float(preset["input_price_cache_hit"]),
        "output_price": float(preset["output_price"]),
        "currency": str(preset["currency"]),
        "model_display": model_display_name(model_name),
    }


def normalize_model_settings(
    *,
    model_name: str = "",
    base_url: str = "",
    input_price: float = 0.0,
    output_price: float = 0.0,
    currency: str = "CNY",
) -> Dict[str, object]:
    resolved_base = (base_url or DEFAULT_BASE_URL).strip()
    resolved_model = (model_name or DEFAULT_MODEL).strip()
    pricing = resolve_pricing(resolved_base, resolved_model)
    return {
        "model_name": resolved_model,
        "base_url": resolved_base,
        "input_price": input_price if input_price > 0 else pricing["input_price"],
        "output_price": output_price if output_price > 0 else pricing["output_price"],
        "input_price_cache_hit": pricing["input_price_cache_hit"],
        "currency": currency or pricing["currency"],
        "provider": pricing["provider"],
        "provider_label": pricing["provider_label"],
        "model_display": pricing["model_display"],
    }
