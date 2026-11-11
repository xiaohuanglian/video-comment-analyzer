# -*- coding: utf-8 -*-
"""统一 API 错误信封。

为什么（2026-11-11 审计）：
项目里原先有三种互不兼容的失败表达：

1. `HTTPException(detail="中文一句话")` —— FastAPI 默认包成 `{"detail": "..."}`
2. 业务接口自己返回 `{"ok": False, "error": "..."}`（chat / writer 等）
3. 采集 guard 的 `{"ok": False, "platform": ..., "error": {code, message, hint, retry_after_seconds}}`

前端因此要写三套解析。这里统一成第 3 种——它已经是全项目最完整的形状
（有错误码、可执行建议、还要等多久），其余两路在异常处理器里被归一。

约束：**不改状态码语义**，也不改响应体里的 `detail` 字段（仍有前端读它），
只在外面再包一层统一的 `error`。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

#: HTTP 状态码 → 稳定的机器可读错误码（前端据此分支，不必匹配中文文案）。
_STATUS_CODE_MAP: dict[int, str] = {
    400: "BAD_INPUT",
    401: "NEED_AUTH",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "UPSTREAM_BROKEN",
    503: "UNAVAILABLE",
    504: "TIMEOUT",
}


def error_code_for_status(status_code: int) -> str:
    return _STATUS_CODE_MAP.get(status_code, "ERROR")


def error_envelope(
    *,
    code: str,
    message: str,
    hint: str = "",
    retry_after_seconds: Optional[int] = None,
    status_code: int = 400,
    platform: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """构造统一失败信封。"""
    body: dict[str, Any] = {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "hint": hint,
            "retry_after_seconds": retry_after_seconds,
        },
        # 保留 detail：既有前端与测试仍在读它，不能破坏
        "detail": message,
        "status": status_code,
    }
    if platform:
        body["platform"] = platform
    if extra:
        body.update(extra)
    return body


def _as_text(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        # 已经是结构化 detail（如 crawl guard 的 error 对象）
        for key in ("message", "detail", "error"):
            value = detail.get(key)
            if isinstance(value, str) and value:
                return value
        return str(detail)
    return str(detail)


def _hint_from_detail(detail: Any) -> str:
    if isinstance(detail, dict):
        hint = detail.get("hint") or detail.get("advice")
        if isinstance(hint, str):
            return hint
    return ""


def install_error_handlers(app: FastAPI) -> None:
    """把 HTTPException / 校验错误统一成同一信封。"""

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        body = error_envelope(
            code=error_code_for_status(exc.status_code),
            message=_as_text(exc.detail),
            hint=_hint_from_detail(exc.detail),
            status_code=exc.status_code,
            # 透传结构化 detail 里的附加信息（如 retry_after_seconds）
            extra=(
                {"error_detail": exc.detail}
                if isinstance(exc.detail, (dict, list))
                else None
            ),
        )
        headers = getattr(exc, "headers", None) or {}
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for item in exc.errors():
            loc = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
            fields.append({"field": loc, "message": item.get("msg", "")})
        first = fields[0] if fields else {"field": "", "message": "请求参数不合法"}
        body = error_envelope(
            code="VALIDATION_FAILED",
            message=f"参数校验失败：{first['field']} {first['message']}".strip(),
            hint="检查请求体的字段类型与必填项",
            status_code=422,
            extra={"fields": fields},
        )
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(Exception)
    async def _unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
        # 未预期异常：不把堆栈或内部细节泄露给调用方，但要进日志
        logger.exception("[api] 未处理异常")
        body = error_envelope(
            code="INTERNAL_ERROR",
            message="服务内部错误，详情见服务端日志",
            hint="若持续出现，请查看 run_web.sh 的终端输出",
            status_code=500,
        )
        return JSONResponse(status_code=500, content=body)
