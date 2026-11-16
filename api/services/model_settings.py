# -*- coding: utf-8 -*-
"""模型连接配置：服务端本地持久化（data/model_settings.json，gitignore、0600 权限）。

安全约束：
- 文件只在 data/（已被 .gitignore 忽略），绝不入库；
- GET 只返回脱敏形式（sk-****尾4位）；
- 不写日志、不回显到错误信息中。
"""

from __future__ import annotations

import json
import os
import stat
from typing import Any, Dict, Optional

from .insight.paths import DATA_DIR
from .json_store import atomic_write_text, read_json

SETTINGS_PATH = DATA_DIR / "model_settings.json"


def normalize_base_url(url: str) -> str:
    """归一成**根地址**（不含 `/v1`）。

    2026-11-11 审计修复：这里原先反过来「补 `/v1`」，而 `api/services/llm.py`
    又自己拼 `/v1/chat/completions`，同一份配置换个来源就变成
    `.../ai-router/v1/v1/chat/completions`。现在全项目只认
    `api.services.llm_config.normalize_base_url()` 一个实现。
    """
    from api.services.llm_config import normalize_base_url as _normalize

    return _normalize(url)


def save_model_settings(base_url: str, model_name: str, api_key: str) -> Dict[str, Any]:
    payload = {
        "base_url": normalize_base_url(base_url),
        "model_name": (model_name or "").strip(),
        "api_key": (api_key or "").strip(),
    }
    atomic_write_text(SETTINGS_PATH, json.dumps(payload, ensure_ascii=False, indent=2))
    try:
        os.chmod(SETTINGS_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return payload


def load_model_settings() -> Dict[str, Any]:
    data = read_json(SETTINGS_PATH, default={}, expect=dict)
    return {key: str(data.get(key) or "") for key in ("base_url", "model_name", "api_key")}


def clear_model_settings() -> None:
    try:
        SETTINGS_PATH.unlink()
    except FileNotFoundError:
        pass


def masked_view(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    s = settings or load_model_settings()
    key = s.get("api_key") or ""
    masked = f"sk-****{key[-4:]}" if len(key) >= 8 else ("****" if key else "")
    return {
        "configured": bool(key),
        "base_url": s.get("base_url") or "",
        "model_name": s.get("model_name") or "",
        "api_key_masked": masked,
    }


def resolve_credentials(request_api_key: str = "", request_base_url: str = "",
                        request_model_name: str = "") -> Dict[str, str]:
    """请求未带凭据时回落到服务端保存的配置。"""
    stored = load_model_settings()
    return {
        "api_key": (request_api_key or "").strip() or stored.get("api_key", ""),
        "base_url": (request_base_url or "").strip() or stored.get("base_url", ""),
        "model_name": (request_model_name or "").strip() or stored.get("model_name", ""),
    }
