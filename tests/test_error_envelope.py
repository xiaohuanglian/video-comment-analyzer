# -*- coding: utf-8 -*-
"""统一错误信封：三种历史返回形状归一。

审计（2026-11-11）：HTTPException / 自带 {ok:false,error} / 采集 guard 信封
三种格式并存，前端要写三套解析。这里锁死统一形状，同时保证
**不破坏**既有读 `detail` 的前端与测试。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from api.main import app
from api.services.error_handlers import error_code_for_status, error_envelope

probe = APIRouter()


@probe.get("/raise-400")
async def _raise_400() -> None:
    raise HTTPException(status_code=400, detail="参数不对，请检查")


@probe.get("/raise-404")
async def _raise_404() -> None:
    raise HTTPException(status_code=404, detail="任务不存在")


@probe.get("/raise-403")
async def _raise_403() -> None:
    raise HTTPException(status_code=403, detail="Access denied")


@probe.get("/raise-structured")
async def _raise_structured() -> None:
    raise HTTPException(
        status_code=409,
        detail={"code": "BUSY", "message": "平台并发已满", "hint": "稍后再试"},
    )


@probe.get("/raise-cooldown")
async def _raise_cooldown() -> None:
    raise HTTPException(
        status_code=409,
        detail={
            "code": "PLATFORM_BLOCKED",
            "message": "xhs 平台冷却中：还需等待 12 小时",
            "hint": "到官方页面人工处理",
            "retry_after_seconds": 43200,
        },
    )


@probe.get("/boom")
async def _boom() -> None:
    raise RuntimeError("数据库密码是 hunter2")


app.include_router(probe, prefix="/__test_errors")


def test_400_has_unified_envelope():
    response = TestClient(app, raise_server_exceptions=False).get("/__test_errors/raise-400")
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "BAD_INPUT"
    assert "参数不对" in body["error"]["message"]
    # 兼容层：老前端仍然读 detail
    assert body["detail"] == "参数不对，请检查"
    assert body["status"] == 400


def test_404_maps_to_not_found_code():
    body = TestClient(app, raise_server_exceptions=False).get("/__test_errors/raise-404").json()
    assert body["error"]["code"] == "NOT_FOUND"


def test_403_maps_to_forbidden_code():
    body = TestClient(app, raise_server_exceptions=False).get("/__test_errors/raise-403").json()
    assert body["error"]["code"] == "FORBIDDEN"


def test_structured_detail_carries_hint():
    body = TestClient(app, raise_server_exceptions=False).get("/__test_errors/raise-structured").json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["message"] == "平台并发已满"
    assert body["error"]["hint"] == "稍后再试"
    assert body["error_detail"]["code"] == "BUSY"


def test_validation_error_is_structured():
    # run_id 路径参数不会校验失败，这里用查询参数越界触发 422
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/data/dataset/comments/x.csv?limit=999999"
    )
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert body["fields"]


def test_unhandled_exception_does_not_leak_internals():
    response = TestClient(app, raise_server_exceptions=False).get("/__test_errors/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text


def test_crawl_guard_envelope_shape_is_compatible():
    """采集 guard 的信封本来就是标准形状，统一后不能被改坏。"""
    from tools.crawl_pacing import CrawlFailure

    guard = CrawlFailure(code="RATE_LIMITED", message="被限流", platform="bili").to_dict()
    assert guard["ok"] is False
    assert guard["error"]["code"] == "RATE_LIMITED"
    assert set(guard["error"]) == {"code", "message", "hint", "retry_after_seconds"}


def test_error_envelope_helper_shape():
    body = error_envelope(code="BUSY", message="稍后", hint="等 30 秒", retry_after_seconds=30)
    assert body["ok"] is False
    assert body["error"]["retry_after_seconds"] == 30
    assert body["detail"] == "稍后"


def test_status_code_map_covers_common_cases():
    assert error_code_for_status(400) == "BAD_INPUT"
    assert error_code_for_status(999) == "ERROR"


def test_structured_detail_lifts_retry_after():
    """采集撞平台风控时，409 信封要带出"还要等多久"。

    状态码只能表达"冲突"，前端要显示倒计时就必须拿到 retry_after_seconds；
    这里锁住它会从结构化 detail 抬到信封顶层（code 仍按状态码映射，不变）。
    """

    body = TestClient(app, raise_server_exceptions=False).get("/__test_errors/raise-cooldown").json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["error"]["retry_after_seconds"] == 43200
    assert body["error"]["hint"] == "到官方页面人工处理"
    assert body["error_detail"]["code"] == "PLATFORM_BLOCKED"
