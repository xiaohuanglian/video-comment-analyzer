# -*- coding: utf-8 -*-
"""Phase 2.5A: LLM function-calling request format & response parsing.

环境中无真实 API Key —— 本文件用可注入的假客户端验证：
1) 发送给模型的请求结构（tools/参数/schema）正确；
2) 模型返回的 tool_calls 被正确解析并真实执行；
3) 模型给出不合规输出/异常时安全退出。
真实 Provider 端到端调用仍标记【待验收】。
"""

import json
from types import SimpleNamespace

import pytest

from api.services.growth import seeds, store
from api.services.growth.orchestrator import Orchestrator, SessionConfig


class FakeUsage:
    prompt_tokens = 100
    completion_tokens = 50
    prompt_cache_hit_tokens = 0


def _msg(content="", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tc(name, args, call_id="call_1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeClient:
    """记录请求并按脚本返回的工具调用客户端。"""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        step = self.script.pop(0) if self.script else _msg(content="完成")
        if isinstance(step, Exception):
            raise step
        return SimpleNamespace(usage=FakeUsage(), choices=[SimpleNamespace(message=step)])


@pytest.fixture()
def product(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    return "youvibe"


def _config(**kw):
    base = dict(product_id="youvibe", goal="分析现有数据，推荐下周内容",
                use_mock=False, budget_limit_cny=1.0)
    base.update(kw)
    return SessionConfig(**base)


def test_request_format_and_tool_call_roundtrip(product):
    client = FakeClient([
        _msg(tool_calls=[_tc("query_signals", {"limit": 5})]),
        _msg(tool_calls=[_tc("query_assets", {})]),
        _msg(content="【推断】当前数据不足，建议先导入评论分析结果。"),
    ])
    s = Orchestrator(_config(), client=client).run()
    assert s.status == "done"
    assert "推断" in s.final_answer

    req = client.requests[0]
    # 请求结构：messages + tools(function schema)
    assert req["messages"][0]["role"] == "system"
    names = {t["function"]["name"] for t in req["tools"]}
    assert "query_signals" in names and "send_external_reply" not in names  # L3 不暴露
    sig_tool = next(t for t in req["tools"] if t["function"]["name"] == "query_signals")
    assert sig_tool["function"]["parameters"]["type"] == "object"
    # 第二轮消息中带工具结果
    req2 = client.requests[1]
    tool_msgs = [m for m in req2["messages"] if m.get("role") == "tool"]
    assert tool_msgs and json.loads(tool_msgs[0]["content"])["status"] == "ok"
    # 成本被计费
    assert s.cost_cny > 0 and s.prompt_tokens == 300


def test_malformed_tool_arguments_safe(product):
    bad_tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="query_signals", arguments="{not json"))
    client = FakeClient([_msg(tool_calls=[bad_tc]), _msg(content="结束")])
    s = Orchestrator(_config(), client=client).run()
    assert s.status == "done"  # 坏 JSON 按空参数处理，不崩溃


def test_provider_error_safe_exit(product):
    client = FakeClient([RuntimeError("API 连接失败")])
    s = Orchestrator(_config(), client=client).run()
    assert s.status == "error" and "API 连接失败" in s.stop_reason
    # 失败会话也持久化且有审计
    assert s.iterations == 1
    assert any(a.action == "agent_session_end" for a in store.list_audit("youvibe"))


def test_denied_tool_result_feeds_back(product):
    client = FakeClient([
        _msg(tool_calls=[_tc("crawl_external", {"platform": "bilibili", "target": "BV1"})]),
        _msg(tool_calls=[_tc("send_external_reply", {"to": "u", "content": "广告"})]),
        _msg(content="两项操作均被权限边界拒绝，改建议人工操作。"),
    ])
    s = Orchestrator(_config(), client=client).run()
    assert s.status == "done"
    req_last = client.requests[-1]
    deny_msgs = [m for m in req_last["messages"] if m.get("role") == "tool"]
    statuses = [json.loads(m["content"])["status"] for m in deny_msgs]
    assert statuses == ["denied", "denied"]


def test_agent_stops_when_done(product):
    """模型不再请求工具时立即停止，不空转烧预算。"""
    client = FakeClient([_msg(content="证据已足够。【事实】…【建议】…")])
    s = Orchestrator(_config(), client=client).run()
    assert s.status == "done" and s.iterations == 1
    assert len(client.requests) == 1
