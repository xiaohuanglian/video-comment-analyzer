# -*- coding: utf-8 -*-
"""LLM 配置解析：单一真相源，不再出现双 `/v1`。

背景（2026-11-11 审计）：`llm.py` 硬拼 `/v1/chat/completions`（期望 env 不带
`/v1`），`growth/model_settings.normalize_base_url()` 却会补 `/v1`（期望带）。
两边一起来就变成 `.../ai-router/v1/v1/chat/completions`。而且 `llm.complete`
只读环境变量，不回落设置页保存的配置。
"""

from __future__ import annotations

import pytest

from api.services import llm_config
from api.services.llm_config import (
    LlmConfig,
    chat_completions_url,
    normalize_base_url,
    resolve_llm_config,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://api.deepseek.com", "https://api.deepseek.com"),
        ("https://api.deepseek.com/", "https://api.deepseek.com"),
        ("https://api.deepseek.com/v1", "https://api.deepseek.com"),
        ("https://api.deepseek.com/v1/", "https://api.deepseek.com"),
        ("https://gw.example.com/ai-router", "https://gw.example.com/ai-router"),
        ("https://gw.example.com/ai-router/v1", "https://gw.example.com/ai-router"),
        ("  ", ""),
    ],
)
def test_normalize_base_url_strips_single_v1(raw, expected):
    assert normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
        "https://api.deepseek.com/v1/",
    ],
)
def test_endpoint_has_exactly_one_v1(raw):
    url = chat_completions_url(raw)
    assert url.count("/v1/") == 1
    assert url.endswith("/v1/chat/completions")
    assert "/v1/v1/" not in url


def test_no_double_v1_regression():
    """审计里实测复现过的那个 URL，必须永远拼不出来。"""
    assert "v1/v1" not in chat_completions_url("https://gw/ai-router/v1")


def test_growth_normalize_delegates_to_single_impl():
    from api.services.model_settings import normalize_base_url as growth_normalize

    for raw in ("https://a.com/v1", "https://a.com", "https://a.com/x/v1/"):
        assert growth_normalize(raw) == normalize_base_url(raw)


def test_resolution_falls_back_to_persisted_settings(monkeypatch, tmp_path):
    """设置页保存后，未设环境变量的进程也应能用同一份配置。"""
    from api.services import model_settings

    settings = tmp_path / "model_settings.json"
    monkeypatch.setattr(model_settings, "SETTINGS_PATH", settings)
    model_settings.save_model_settings("https://gw.example.com/ai-router", "m-1", "sk-stored")

    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)

    config = resolve_llm_config()
    assert config.base_url == "https://gw.example.com/ai-router"
    assert config.model == "m-1"
    assert config.api_key == "sk-stored"
    assert config.configured is True


def test_explicit_request_beats_env_and_stored(monkeypatch, tmp_path):
    from api.services import model_settings

    monkeypatch.setattr(model_settings, "SETTINGS_PATH", tmp_path / "s.json")
    model_settings.save_model_settings("https://stored.example.com", "stored-model", "sk-stored")
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("LLM_API_KEY", "sk-env")
    monkeypatch.setenv("LLM_MODEL", "env-model")

    config = resolve_llm_config(api_key="sk-req", base_url="https://req.example.com", model="req-model")
    assert config.base_url == "https://req.example.com"
    assert config.model == "req-model"
    assert config.api_key == "sk-req"


def test_env_beats_stored(monkeypatch, tmp_path):
    from api.services import model_settings

    monkeypatch.setattr(model_settings, "SETTINGS_PATH", tmp_path / "s.json")
    model_settings.save_model_settings("https://stored.example.com", "stored-model", "sk-stored")
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("LLM_API_KEY", "sk-env")
    monkeypatch.setenv("LLM_MODEL", "env-model")

    config = resolve_llm_config()
    assert config.base_url == "https://env.example.com"


def test_default_base_when_nothing_configured(monkeypatch, tmp_path):
    from api.services import model_settings

    monkeypatch.setattr(model_settings, "SETTINGS_PATH", tmp_path / "none.json")
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)

    config = resolve_llm_config()
    assert config.base_url == llm_config.DEFAULT_BASE_URL
    assert config.model == llm_config.DEFAULT_MODEL
    assert config.configured is False


def test_masked_never_returns_plaintext_key():
    view = llm_config.masked(LlmConfig(base_url="https://a.com", api_key="sk-1234567890", model="m"))
    assert "sk-1234567890" not in str(view)
    assert view["api_key_masked"].endswith("7890")


def test_complete_raises_clear_error_when_unconfigured(monkeypatch, tmp_path):
    import asyncio

    from api.services import llm, model_settings

    monkeypatch.setattr(model_settings, "SETTINGS_PATH", tmp_path / "none.json")
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(RuntimeError, match="未配置"):
        asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))


def test_complete_uses_resolved_config_endpoint(monkeypatch):
    """真正发出去的 URL 必须来自解析结果，不能再有第二处拼接。"""
    import asyncio

    from api.services import llm

    seen: dict[str, str] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            seen["url"] = url
            return FakeResponse()

    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient)
    config = LlmConfig(base_url="https://gw.example.com/ai-router", api_key="k", model="m")
    out = asyncio.run(llm.complete([{"role": "user", "content": "hi"}], config=config))

    assert out == "ok"
    assert seen["url"] == "https://gw.example.com/ai-router/v1/chat/completions"


def test_settings_page_save_drives_all_llm_calls(monkeypatch, tmp_path):
    """设置页保存后，未设环境变量的进程也能用同一份配置（单轨）。

    审计（2026-11-11）：`llm.complete` 原先只读环境变量，而设置页写的是
    `data/model_settings.json`，等于「保存了也不生效」。现在两者走同一个 resolver。
    """
    from api.services import model_settings

    monkeypatch.setattr(model_settings, "SETTINGS_PATH", tmp_path / "s.json")
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)

    model_settings.save_model_settings(
        "https://gateway.example.com/ai-router", "some-model", "sk-from-settings-page"
    )

    config = resolve_llm_config()
    assert config.api_key == "sk-from-settings-page"
    assert config.model == "some-model"
    # 关键：端点只能有一个 /v1，这是审计里炸掉的那处
    assert config.endpoint == "https://gateway.example.com/ai-router/v1/chat/completions"
    assert config.endpoint.count("/v1/") == 1


def test_ui_has_model_settings_section():
    """设置页必须真的能改模型配置——否则 README 说的「配置模型」无处落脚。"""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "web_react" / "src" / "pages" / "SettingsPage.tsx").read_text(
        encoding="utf-8"
    )
    assert "模型网关" in page
    assert "modelSettingsSave" in page
    assert "modelSettingsTest" in page
