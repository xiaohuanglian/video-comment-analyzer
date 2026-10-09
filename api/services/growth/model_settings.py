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

from ..insight.paths import DATA_DIR
from .store import atomic_write_text

SETTINGS_PATH = DATA_DIR / "model_settings.json"


def normalize_base_url(url: str) -> str:
    """OpenAI 兼容端点必须带 /v1；NewAPI 网关（.../ai-router）常忘写，自动补。"""
    u = (url or "").strip().rstrip("/")
    if not u:
        return u
    if u.endswith("/v1") or "/v1/" in u:
        return u
    return u + "/v1"


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
    if not SETTINGS_PATH.exists():
        return {"base_url": "", "model_name": "", "api_key": ""}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return {
            "base_url": str(data.get("base_url") or ""),
            "model_name": str(data.get("model_name") or ""),
            "api_key": str(data.get("api_key") or ""),
        }
    except (json.JSONDecodeError, OSError):
        return {"base_url": "", "model_name": "", "api_key": ""}


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
