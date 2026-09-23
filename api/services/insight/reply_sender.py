# -*- coding: utf-8 -*-
"""Platform reply senders for the controlled reply run.

Only called by ``reply_runner`` for entries the human explicitly approved.
Senders raise :class:`ReplySendError` with a user-readable reason so the run can
record ``send_error`` and continue with the remaining entries.

Credentials are read from the environment (``VCA_OUTREACH_COOKIE``) or the
existing crawler ``config.COOKIES`` value. We deliberately do not persist
platform cookies in run artifacts.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

import httpx


class ReplySendError(Exception):
    """Raised when a reply could not be delivered."""


_BILIBILI_REPLY_ADD = "https://api.bilibili.com/x/v2/reply/add"
_BILIBILI_VIEW = "https://api.bilibili.com/x/web-interface/view"
_BILIBILI_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_BILIBILI_CODE_MESSAGES = {
    -101: "平台账号未登录（Cookie 失效）",
    -102: "平台账号被封禁",
    -400: "请求参数有误",
    -403: "无权限回复（可能被拉黑或该评论不可回复）",
    -404: "目标评论不存在或已删除",
    -509: "请求过于频繁，被平台限流",
    -503: "平台限流，请降低发送频率",
    12002: "评论内容包含敏感词",
    12006: "评论被折叠/需要验证",
    12008: "回复间隔太短，请加大最小间隔",
    12015: "需要绑定手机号",
    12016: "该评论不可回复",
    12025: "账号等级不足，无法发送",
}


def _cookie_string() -> str:
    for key in ("VCA_OUTREACH_COOKIE", "COOKIES"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    try:
        from config import base_config  # type: ignore

        return str(getattr(base_config, "COOKIES", "") or "").strip()
    except Exception:
        return ""


def _csrf_from_cookie(cookie: str) -> str:
    for part in cookie.split(";"):
        name, _, value = part.strip().partition("=")
        if name == "bili_jct" and value:
            return value
    return ""


def _headers(cookie: str, referer: str = "") -> dict:
    headers = {
        "User-Agent": _BILIBILI_UA,
        "Cookie": cookie,
        "Origin": "https://www.bilibili.com",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def _resolve_bilibili_aid(client: httpx.Client, content_id: str, headers: dict) -> int:
    content_id = str(content_id or "").strip()
    if not content_id:
        raise ReplySendError("缺少目标视频 id，无法回复")
    if content_id.isdigit():
        return int(content_id)
    response = client.get(_BILIBILI_VIEW, params={"bvid": content_id}, headers=headers)
    try:
        data = response.json()
    except ValueError as exc:
        raise ReplySendError("获取视频信息失败（返回非 JSON）") from exc
    if data.get("code") != 0:
        raise ReplySendError(f"获取视频信息失败：{data.get('message') or data.get('code')}")
    aid = (data.get("data") or {}).get("aid")
    if not aid:
        raise ReplySendError("获取视频 aid 失败")
    return int(aid)


def send_bilibili_reply(*, content_id: str, comment_id: str, message: str, cookie: str = "") -> str:
    """Post a public reply and return the platform reply id (if any)."""
    cookie = cookie or _cookie_string()
    if not cookie:
        raise ReplySendError("未配置 B 站登录 Cookie（设置环境变量 VCA_OUTREACH_COOKIE）")
    csrf = _csrf_from_cookie(cookie)
    if not csrf:
        raise ReplySendError("B 站 Cookie 缺少 bili_jct，无法发送")
    comment_id = str(comment_id or "").strip()
    if not comment_id:
        raise ReplySendError("缺少目标评论 id，无法回复")

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        aid = _resolve_bilibili_aid(client, content_id, _headers(cookie))
        referer = f"https://www.bilibili.com/video/{content_id}"
        response = client.post(
            _BILIBILI_REPLY_ADD,
            data={
                "oid": aid,
                "type": 1,
                "message": message,
                "root": comment_id,
                "parent": comment_id,
                "csrf": csrf,
            },
            headers=_headers(cookie, referer),
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise ReplySendError("发送失败（平台返回非 JSON，可能被风控拦截）") from exc
    code = data.get("code")
    if code != 0:
        reason = _BILIBILI_CODE_MESSAGES.get(code) or data.get("message") or f"错误码 {code}"
        raise ReplySendError(reason)
    reply = (data.get("data") or {}).get("rpid_str") or (data.get("data") or {}).get("rpid")
    return str(reply or "")


_SENDERS: dict[str, Callable[..., str]] = {
    "bili": send_bilibili_reply,
    "bilibili": send_bilibili_reply,
}


def platform_capability(platform: str) -> bool:
    return (platform or "").strip().lower() in _SENDERS


def send_reply(
    *,
    platform: str,
    content_id: str,
    comment_id: str,
    message: str,
    cookie: Optional[str] = None,
) -> str:
    key = (platform or "").strip().lower()
    sender = _SENDERS.get(key)
    if sender is None:
        raise ReplySendError(f"平台「{platform or '未知'}」暂不支持自动回复，请改为手动复制发送")
    return sender(content_id=content_id, comment_id=comment_id, message=message, cookie=cookie or "")