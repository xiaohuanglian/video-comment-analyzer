# -*- coding: utf-8 -*-
"""模型连接设置：base URL 归一化、持久化、脱敏、凭据回落。

2026-11-11 语义变更：base URL 一律存**根地址**（不含 `/v1`），
由 `llm_config.chat_completions_url()` / OpenAI SDK 负责补端点。
旧实现存的是带 `/v1` 的形式，与 `llm.py` 硬拼的 `/v1` 叠成 `v1/v1`。
"""

import os
import stat

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services import model_settings
from api.services.llm_config import chat_completions_url


@pytest.fixture()
def settings_tmp(tmp_path, monkeypatch):
    path = tmp_path / "model_settings.json"
    monkeypatch.setattr(model_settings, "SETTINGS_PATH", path)
    return path


def test_normalize_base_url_strips_v1():
    assert model_settings.normalize_base_url("https://x.com/ai-router") == "https://x.com/ai-router"
    assert model_settings.normalize_base_url("https://x.com/ai-router/") == "https://x.com/ai-router"
    assert model_settings.normalize_base_url("https://api.deepseek.com/v1") == "https://api.deepseek.com"
    assert model_settings.normalize_base_url("https://api.deepseek.com/v1/") == "https://api.deepseek.com"
    assert model_settings.normalize_base_url("") == ""


def test_stored_base_url_yields_single_v1_endpoint():
    """存根地址，端点永远只出现一个 /v1——这是审计里炸掉的那个点。"""
    stored = model_settings.normalize_base_url("https://x.com/ai-router/v1")
    url = chat_completions_url(stored)
    assert url == "https://x.com/ai-router/v1/chat/completions"
    assert url.count("/v1/") == 1


def test_save_load_mask_and_perms(settings_tmp):
    model_settings.save_model_settings("https://x.com/router", "m1", "sk-abcdefgh12345")
    s = model_settings.load_model_settings()
    assert s["base_url"] == "https://x.com/router"  # 存根地址
    assert s["api_key"] == "sk-abcdefgh12345"
    mode = stat.S_IMODE(os.stat(settings_tmp).st_mode)
    assert mode == 0o600  # 仅本人可读写
    view = model_settings.masked_view()
    assert view["configured"] and view["api_key_masked"] == "sk-****2345"
    # 明文 key 不出现在脱敏视图中
    assert "sk-abcdefgh12345" not in str(view)


def test_resolve_credentials_fallback(settings_tmp):
    model_settings.save_model_settings("https://x.com/v1", "m_stored", "sk-stored00000")
    c = model_settings.resolve_credentials("", "", "")
    assert c["api_key"] == "sk-stored00000" and c["model_name"] == "m_stored"
    assert c["base_url"] == "https://x.com"
    c2 = model_settings.resolve_credentials("sk-override000", "", "m_req")
    assert c2["api_key"] == "sk-override000" and c2["base_url"] == "https://x.com"


def test_settings_api_roundtrip(settings_tmp):
    client = TestClient(app)
    r = client.post(
        "/api/settings/model",
        json={"base_url": "https://x.com/router", "model_name": "m1", "api_key": "sk-test123456789"},
    )
    assert r.status_code == 200
    assert r.json()["configured"] and r.json()["base_url"] == "https://x.com/router"
    r2 = client.get("/api/settings/model")
    assert "sk-test123456789" not in r2.text  # 明文 key 不出现在接口响应
    # 再保存：空 key 保留原值
    client.post("/api/settings/model", json={"base_url": "https://x.com/router"})
    assert model_settings.load_model_settings()["api_key"] == "sk-test123456789"
    client.delete("/api/settings/model")
    assert client.get("/api/settings/model").json()["configured"] is False


def test_settings_test_endpoint_no_key(settings_tmp):
    client = TestClient(app)
    r = client.post("/api/settings/model/test", json={})
    assert r.json()["ok"] is False and "Key" in r.json()["error"]
