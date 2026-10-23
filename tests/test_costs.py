# -*- coding: utf-8 -*-
"""费用台账:记录/汇总/计价回算/透明包装客户端(纯离线)。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services import costs
from api.services.insight import llm_analyzer


@pytest.fixture(autouse=True)
def _isolate_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(costs, "COSTS_DIR", tmp_path)
    monkeypatch.setattr(costs, "LEDGER_FILE", tmp_path / "ledger.jsonl")
    monkeypatch.delenv(costs.ENV_PRICE_IN, raising=False)
    monkeypatch.delenv(costs.ENV_PRICE_OUT, raising=False)


def test_record_and_ledger_newest_first():
    costs.record(feature="chat", model="m1", prompt_tokens=100, completion_tokens=50, duration_ms=900)
    costs.record(feature="writer", model="m1", prompt_tokens=10, completion_tokens=5)
    entries = costs.ledger(limit=10)
    assert len(entries) == 2
    assert entries[0]["feature"] == "writer"  # 新→旧
    assert entries[1]["total_tokens"] == 150
    assert entries[1]["ok"] is True


def test_record_failure_counts_call():
    costs.record(feature="chat", model="m", ok=False, error="HTTPError: 502")
    s = costs.summary()
    assert s["total"]["calls"] == 1
    assert s["total"]["ok_calls"] == 0
    assert s["total"]["total_tokens"] == 0


def test_summary_aggregates_by_feature_and_today():
    costs.record(feature="chat", prompt_tokens=100, completion_tokens=40)
    costs.record(feature="chat", prompt_tokens=60, completion_tokens=20)
    costs.record(feature="topics.plan", prompt_tokens=1000, completion_tokens=500)
    s = costs.summary()
    assert s["total"]["calls"] == 3
    assert s["total"]["prompt_tokens"] == 1160
    assert s["total"]["completion_tokens"] == 560
    assert s["today"]["calls"] == 3  # 测试记录都落在当天
    by = {f["feature"]: f for f in s["by_feature"]}
    assert by["chat"]["calls"] == 2
    assert by["topics.plan"]["total_tokens"] == 1500
    assert s["by_feature"][0]["feature"] == "topics.plan"  # 按 tokens 降序


def test_cost_computed_when_price_configured(monkeypatch):
    monkeypatch.setenv(costs.ENV_PRICE_IN, "2.0")   # 元/百万
    monkeypatch.setenv(costs.ENV_PRICE_OUT, "8.0")
    costs.record(feature="chat", prompt_tokens=1_000_000, completion_tokens=500_000)
    s = costs.summary()
    assert s["pricing"]["configured"] is True
    assert s["total"]["cost"] == pytest.approx(2.0 + 4.0, rel=1e-3)


def test_cost_zero_when_unpriced():
    costs.record(feature="chat", prompt_tokens=999, completion_tokens=999)
    s = costs.summary()
    assert s["pricing"]["configured"] is False
    assert s["total"]["cost"] == 0.0


def _fake_openai_client():
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=30)
    resp = SimpleNamespace(usage=usage, model="test-model")
    create_calls = []

    class Completions:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            return resp

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()
        api_key = "k"  # __getattr__ 透传验证用

    return Client(), create_calls


def test_recording_client_sync_create_records_usage():
    inner, _ = _fake_openai_client()
    client = llm_analyzer.UsageRecordingClient(inner, "insight")
    resp = client.chat.completions.create(model="test-model", messages=[])
    assert resp.usage.prompt_tokens == 120  # 透传返回原对象
    entries = costs.ledger(limit=5)
    assert entries[0]["feature"] == "insight"
    assert entries[0]["prompt_tokens"] == 120
    assert entries[0]["completion_tokens"] == 30
    assert entries[0]["model"] == "test-model"


def test_recording_client_passthrough_attrs():
    inner, _ = _fake_openai_client()
    client = llm_analyzer.UsageRecordingClient(inner, "insight")
    assert client.api_key == "k"  # 非 chat 属性原样透传


def test_recording_client_async_create_records_usage():
    import asyncio

    inner, _ = _fake_openai_client()

    class AsyncCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3), model="m"
            )

    class AsyncChat:
        completions = AsyncCompletions()

    class AsyncClient:
        chat = AsyncChat()

    client = llm_analyzer.UsageRecordingClient(AsyncClient(), "reply_draft")
    resp = asyncio.run(client.chat.completions.create(model="m", messages=[]))
    assert resp.usage.prompt_tokens == 7
    entries = costs.ledger(limit=5)
    assert entries[0]["feature"] == "reply_draft"
    assert entries[0]["total_tokens"] == 10
