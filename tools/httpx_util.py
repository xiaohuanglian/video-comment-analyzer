# -*- coding: utf-8 -*-
"""统一的 HTTP 客户端工厂。

这里有两个入口，区别是**用在哪一层**，不是"新的比旧的好"：

- :func:`make_async_client` —— 普通 ``httpx.AsyncClient``。图片/视频 CDN 下载、
  二维码取图、短链跳转解析、代理池探活都用它：这些请求不涉及平台风控判定，
  用不着伪装 TLS，少一层依赖也少一个故障点。
- :func:`make_impersonated_client` —— 走 ``curl_cffi`` 的 Chrome TLS 指纹。
  平台业务接口（如抖音 ``/aweme/v1/web/*``）用它。

## 为什么需要第二层

``httpx`` / ``requests`` 用的是 Python 自己的 TLS 栈和 HTTP/1.1：JA3/JA4 指纹、
HTTP/2 SETTINGS 帧、ALPN 协商结果跟 Chrome 完全不是一回事。风控看这一层比看
header 字典顺序重得多——**header 对得再齐，TLS 握手一开口还是 Python**。

实测证据（2026-11-12 本机）：同一个 ``https://www.douyin.com/favicon.ico``，
``httpx`` 返回 302，``curl_cffi(impersonate="chrome")`` 返回 200。
当时的 UA、header 完全一致，差别只在 TLS 层。

## 没装 curl_cffi 怎么办

退回 ``httpx`` 并打一条 warning。理由：curl_cffi 是可选加速/伪装层，缺它
不该让整条采集链起不来；但必须留日志，免得又出现"以为在用 TLS 指纹、
其实还是裸 httpx"的静默降级（和指纹模块里那条教训同一类）。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

import config

#: curl_cffi 是否可用（导入失败就整体退回 httpx）
_CURL_AVAILABLE: Optional[bool] = None
_curl_session_cls: Any = None


def _logger() -> logging.Logger:
    """惰性取项目 logger。

    不能 module-level ``from tools import utils``：``tools.utils`` →
    ``tools.crawler_util`` → ``tools.httpx_util``，会形成循环导入
    （2026-11-12 实测 ImportError: partially initialized module）。
    """
    from tools import utils

    return utils.logger


def _load_curl() -> Any:
    """惰性导入 curl_cffi；不可用返回 None（只试一次，别每个请求都试）。"""
    global _CURL_AVAILABLE, _curl_session_cls
    if _CURL_AVAILABLE is not None:
        return _curl_session_cls
    try:
        from curl_cffi.requests import AsyncSession  # noqa: WPS433 — 可选依赖

        _curl_session_cls = AsyncSession
        _CURL_AVAILABLE = True
    except Exception as exc:  # noqa: BLE001 — 缺依赖/缺 libcurl 都算不可用
        _CURL_AVAILABLE = False
        _curl_session_cls = None
        _logger().warning(
            f"[HttpClient] curl_cffi 不可用（{exc}），退回 httpx："
            f"请求将不带 Chrome TLS 指纹，平台能看出这是 Python 客户端"
        )
    return _curl_session_cls


def tls_impersonation_available() -> bool:
    """TLS 指纹层是否真的可用（测试与启动日志用）。"""
    return _load_curl() is not None


def reset_tls_probe() -> None:
    """测试用：清掉"试过一次"的缓存，让 monkeypatch 能重新决定可用性。"""
    global _CURL_AVAILABLE, _curl_session_cls
    _CURL_AVAILABLE = None
    _curl_session_cls = None


def make_async_client(**kwargs) -> httpx.AsyncClient:
    """创建统一配置的 httpx.AsyncClient。

    从配置文件读取 DISABLE_SSL_VERIFY（默认 False，即开启 SSL 验证）。
    仅在使用企业代理、Burp、mitmproxy 等中间人代理时才需将其设为 True。
    """
    kwargs.setdefault("verify", not getattr(config, "DISABLE_SSL_VERIFY", False))
    return httpx.AsyncClient(**kwargs)


class _AdaptedResponse:
    """把 curl_cffi 的 Response 包成"够用的 httpx 形状"。

    为什么需要：调用方（``douyin/client.py``）用的是 ``reason_phrase``，
    而 curl_cffi 的 Response 没有这个属性（实测 ``hasattr`` 为 False）。
    与其让每个调用点记住"这层是 curl、那层是 httpx"，不如在边界上抹平。

    只代理真正被用到的成员，**不做万能代理**：多代理一层，就可能把
    "curl_cffi 没有这个能力" 藏成一个假的 None。
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: Any):
        self._raw = raw

    @property
    def status_code(self) -> int:
        return int(getattr(self._raw, "status_code", 0) or 0)

    @property
    def text(self) -> str:
        try:
            return self._raw.text or ""
        except Exception:  # noqa: BLE001 — 非文本响应
            return ""

    @property
    def content(self) -> bytes:
        return getattr(self._raw, "content", b"") or b""

    @property
    def headers(self) -> Any:
        return self._raw.headers

    @property
    def reason_phrase(self) -> str:
        import http.client

        return http.client.responses.get(self.status_code, "")

    @property
    def url(self) -> str:
        return str(getattr(self._raw, "url", "") or "")

    def json(self, **kwargs) -> Any:
        return self._raw.json(**kwargs)

    def raise_for_status(self) -> None:
        self._raw.raise_for_status()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<AdaptedResponse [{self.status_code}]>"


class _AdaptedSession:
    """curl_cffi AsyncSession 的薄包装：参数名对齐 httpx，其余原样透传。"""

    def __init__(self, session: Any, default_headers: bool = False):
        self._session = session
        self._default_headers = default_headers

    async def request(self, method: str, url: str, **kwargs) -> _AdaptedResponse:
        # httpx 叫 follow_redirects，curl_cffi 叫 allow_redirects：
        kwargs.pop("verify", None)  # verify 在建 session 时已给
        follow = kwargs.pop("follow_redirects", None)
        if follow is not None:
            kwargs.setdefault("allow_redirects", follow)
        kwargs.setdefault("default_headers", self._default_headers)
        raw = await self._session.request(method, url, **kwargs)
        return _AdaptedResponse(raw)

    async def get(self, url: str, **kwargs) -> _AdaptedResponse:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> _AdaptedResponse:
        return await self.request("POST", url, **kwargs)

    async def close(self) -> None:
        try:
            await self._session.close()
        except Exception:  # noqa: BLE001 — 关闭失败不该冒泡
            pass

    async def __aenter__(self) -> "_AdaptedSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


def make_impersonated_client(
    *,
    impersonate: Optional[str] = None,
    proxy: Optional[str] = None,
    **kwargs,
) -> Any:
    """平台业务接口用的客户端：优先 Chrome TLS 指纹，退化到 httpx。

    ``default_headers=False`` 是刻意的：只要指纹，不要 curl 自己那套头。
    curl_cffi 默认会注入 ``Accept: */*`` / ``Accept-Encoding`` 等，与调用方
    精心拼的头混在一起反而更容易自相矛盾；调用方给什么就发什么。
    """
    verify = kwargs.pop("verify", not getattr(config, "DISABLE_SSL_VERIFY", False))
    session_cls = _load_curl()
    if session_cls is None:
        kwargs.setdefault("verify", verify)
        if proxy:
            kwargs.setdefault("proxy", proxy)
        return make_async_client(**kwargs)

    profile = impersonate or getattr(config, "DY_TLS_IMPERSONATE_PROFILE", "chrome")
    session_kwargs = dict(
        impersonate=profile,
        default_headers=False,
        verify=verify,
        **kwargs,
    )
    if proxy:
        session_kwargs["proxy"] = proxy
    session = session_cls(**session_kwargs)
    return _AdaptedSession(session, default_headers=False)
