# -*- coding: utf-8 -*-
"""模型连接设置：/v1 归一化、持久化、脱敏、凭据回落。"""

import os
import stat

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.growth import model_settings


@pytest.fixture()
def settings_tmp(tmp_path, monkeypatch):
    path = tmp_path / "model_settings.json"
    monkeypatch.setattr(model_settings, "SETTINGS_PATH", path)
    return path


def test_normalize_base_url():
    assert model_settings.normalize_base_url("https://x.com/ai-router") == "https://x.com/ai-router/v1"
    assert model_settings.normalize_base_url("https://x.com/ai-router/") == "https://x.com/ai-router/v1"
    assert model_settings.normalize_base_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1"
    assert model_settings.normalize_base_url("") == ""


def test_save_load_mask_and_perms(settings_tmp):
    model_settings.save_model_settings("https://x.com/router", "m1", "sk-abcdefgh12345")
    s = model_settings.load_model_settings()
    assert s["base_url"] == "https://x.com/router/v1"  # 自动补 /v1
    assert s["api_key"] == "sk-abcdefgh12345"
    mode = stat.S_IMODE(os.stat(settings_tmp).st_mode)
    assert mode == 0o600  # 仅本人可读写
    view = model_settings.masked_view()
    assert view["configured"] and "12345" not in view["api_key_masked"].replace("2345", "")
    assert view["api_key_masked"] == "sk-****2345"
    # 明文 key 不出现在脱敏视图中
    assert "sk-abcdefgh12345" not in str(view)


def test_resolve_credentials_fallback(settings_tmp):
    model_settings.save_model_settings("https://x.com/v1", "m_stored", "sk-stored00000")
    c = model_settings.resolve_credentials("", "", "")
    assert c["api_key"] == "sk-stored00000" and c["model_name"] == "m_stored"
    c2 = model_settings.resolve_credentials("sk-override000", "", "m_req")
    assert c2["api_key"] == "sk-override000" and c2["base_url"] == "https://x.com/v1"


def test_settings_api_roundtrip(settings_tmp):
    client = TestClient(app)
    r = client.post("/api/growth/settings/model", json={
        "base_url": "https://x.com/router", "model_name": "m1", "api_key": "sk-test123456789"})
    assert r.status_code == 200
    assert r.json()["configured"] and r.json()["base_url"] == "https://x.com/router/v1"
    r2 = client.get("/api/growth/settings/model")
    assert "sk-test123456789" not in r2.text  # 明文 key 不出现在接口响应
    # 再保存：空 key 保留原值
    client.post("/api/growth/settings/model", json={"base_url": "https://x.com/router"})
    assert model_settings.load_model_settings()["api_key"] == "sk-test123456789"
    client.delete("/api/growth/settings/model")
    assert client.get("/api/growth/settings/model").json()["configured"] is False


def test_settings_test_endpoint_no_key(settings_tmp):
    client = TestClient(app)
    r = client.post("/api/growth/settings/model/test", json={})
    assert r.json()["ok"] is False and "Key" in r.json()["error"]
