# -*- coding: utf-8 -*-
"""数据浏览接口的安全边界。

背景（2026-11-11 审计）：`/api/data/*` 原本默认全开——`data/` 下任何文件
都能列出、预览、下载，而 `data/model_settings.json`（LLM 网关密钥）和
`data/automation/bili_cookie.json`（可接管账号的登录 Cookie）就躺在里面。
这组测试锁死「凭据拿不走 + 正常数据还能看」两条边界。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers import data as data_router


@pytest.fixture
def data_home(tmp_path, monkeypatch):
    """一个仿真的 data/ 目录：既有可下载的采集结果，也有不该外泄的凭据。"""
    (tmp_path / "comments").mkdir()
    (tmp_path / "comments" / "comments_2026-11-11.jsonl").write_text(
        '{"comment_id":"c1","content":"hello"}\n{"comment_id":"c2","content":"world"}\n',
        encoding="utf-8",
    )
    (tmp_path / "comments" / "comments.csv").write_text(
        "id,content\n1,first\n2,second\n", encoding="utf-8"
    )
    (tmp_path / "wechat" / "作者" / "2026-11-01_标题").mkdir(parents=True)
    (tmp_path / "wechat" / "作者" / "2026-11-01_标题" / "article.md").write_text(
        "# 标题\n\n正文内容\n", encoding="utf-8"
    )

    # 内部状态目录：短链队列里也有 comment_url 之类的运营数据，不该被浏览
    (tmp_path / "automation").mkdir()
    (tmp_path / "automation" / "bili_reply.json").write_text(
        json.dumps({"items": [], "config": {"keywords": ["私有运营词"]}}), encoding="utf-8"
    )

    # 凭据：真实存在过的两种文件
    (tmp_path / "model_settings.json").write_text(
        json.dumps(
            {
                "base_url": "https://gateway.example.com/v1",
                "model_name": "some-model",
                "api_key": "sk-SECRET-SHOULD-NEVER-LEAK",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "automation" / "bili_cookie.json").write_text(
        json.dumps({"cookie": "SESSDATA=SECRET-COOKIE", "account": {"uname": "someone"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(data_router, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(data_home):
    return TestClient(app)


def test_llm_api_key_file_is_not_listable(client):
    paths = [f["path"] for f in client.get("/api/data/files").json()["files"]]
    assert "model_settings.json" not in paths
    assert all("model_settings" not in p for p in paths)


@pytest.mark.parametrize(
    "path",
    [
        "model_settings.json",
        "automation/bili_cookie.json",
        "automation/bili_reply.json",
    ],
)
@pytest.mark.parametrize(
    "endpoint",
    ["/api/data/files/{p}", "/api/data/files/{p}?preview=false", "/api/data/download/{p}"],
)
def test_credentials_and_state_are_not_readable(client, path, endpoint):
    response = client.get(endpoint.format(p=path))
    assert response.status_code == 403, f"{endpoint} 泄露了 {path}"
    assert "SECRET" not in response.text
    assert "私有运营词" not in response.text


def test_data_root_is_not_browsable(client):
    """data 根目录本身不开放（那里就是密钥和状态文件的落脚点）。"""
    assert client.get("/api/data/files/").status_code in (403, 404, 307, 400)


def test_path_traversal_outside_data_dir_is_blocked(client, tmp_path):
    outside = tmp_path.parent / "outside.json"
    outside.write_text('{"secret": "nope"}', encoding="utf-8")
    response = client.get("/api/data/download/../outside.json")
    assert response.status_code in (403, 404)
    assert "nope" not in response.text


def test_unknown_directory_is_denied(client, data_home):
    (data_home / "private_notes").mkdir()
    (data_home / "private_notes" / "a.json").write_text("[]", encoding="utf-8")
    response = client.get("/api/data/download/private_notes/a.json")
    assert response.status_code == 403


def test_collected_comments_still_downloadable(client):
    """安全边界不能把正常功能一起封掉。"""
    listing = client.get("/api/data/files").json()["files"]
    paths = {f["path"] for f in listing}
    assert "comments/comments_2026-11-11.jsonl" in paths
    assert "comments/comments.csv" in paths
    assert "wechat/作者/2026-11-01_标题/article.md" in paths

    got = client.get("/api/data/download/comments/comments_2026-11-11.jsonl")
    assert got.status_code == 200
    assert "hello" in got.text


def test_csv_preview_and_total(client):
    response = client.get("/api/data/files/comments/comments.csv?preview=true&limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["data"]) == 1


def test_wechat_markdown_preview_no_longer_500(client):
    """公众号「查看 md」曾因不支持的后缀返回 500（还包成 detail=400）。"""
    response = client.get("/api/data/files/wechat/作者/2026-11-01_标题/article.md")
    assert response.status_code == 200
    body = response.json()
    assert body["raw"] is True
    assert "正文内容" in body["data"]


def test_stats_counts_only_browsable_files(client):
    stats = client.get("/api/data/stats").json()
    listing = client.get("/api/data/files").json()["files"]
    assert stats["total_files"] == len(listing)
    assert stats["total_files"] >= 3


def test_listing_is_cached_between_unchanged_calls(client, data_home, monkeypatch):
    """列表接口曾每次都把所有 json 重新解析；文件没变应当复用缓存。"""
    calls = {"n": 0}
    original = data_router.get_file_info

    def counting(path):
        calls["n"] += 1
        return original(path)

    monkeypatch.setattr(data_router, "get_file_info", counting)
    client.get("/api/data/files")
    first = calls["n"]
    assert first > 0
    client.get("/api/data/files")
    assert calls["n"] == first, "文件未变化时不应重复解析"
