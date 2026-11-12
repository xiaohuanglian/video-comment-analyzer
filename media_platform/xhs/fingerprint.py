# -*- coding: utf-8 -*-
"""小红书请求指纹：让 HTTP 头的 UA / sec-ch-ua 与浏览器里的那个「人」一致。

## 为什么需要这个模块

2026-11-11 事故之后核对请求头，发现同一次会话里三处版本号互不相同：

- 浏览器上下文 UA（``core.py`` 旧 ``:57``）写死 ``Chrome/126.0.0.0``
- HTTP 客户端 ``user-agent`` 写死 ``Chrome/137.0.0.0``
- 同一个 dict 里 ``sec-ch-ua`` 写 ``v="136"``，``sec-ch-ua-platform`` 写 ``"Windows"``

也就是说：**UA 说自己是 Mac 上的 Chrome 126，客户端声称自己是 Chrome 137，
而 Client Hints 又说自己是 Windows 上的 Chrome 136**。这是一眼可辨的机器人特征，
比"间隔短"更容易被规则直接命中——真人不可能同时是这三台机器。

修法不是再挑一个"更真"的常量（那只是把矛盾换个位置），而是**从真正跑着的
浏览器里读**：``navigator.userAgent`` 与 ``navigator.userAgentData`` 是浏览器
自己报的值，拿它填 HTTP 头，两者天然同源。

## 拿不到 userAgentData 时怎么办

Firefox/Safari 没有 ``navigator.userAgentData``，此时从 UA 字符串里反推
Chrome 大版本与平台；反推不出来就**不伪造** ``sec-ch-ua*``（缺头比错头安全）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from tools import utils

#: 从 UA 里抠 Chrome/Edge 的大版本号，例如 ``Chrome/137.0.0.0`` → ``137``
_CHROME_VERSION_RE = re.compile(r"(?:Chrome|Chromium|Edg)/(\d+)")
#: 从 UA 里判断平台，顺序不能反（Android 的 UA 里同时含 "Linux"）
_PLATFORM_HINTS = (
    ("Android", '"Android"'),
    ("iPhone", '"iOS"'),
    ("iPad", '"iOS"'),
    ("Macintosh", '"macOS"'),
    ("CrOS", '"Chrome OS"'),
    ("Windows", '"Windows"'),
    ("Linux", '"Linux"'),
)

#: 读指纹的 JS：浏览器自报什么就返回什么，不做任何加工。
_READ_JS = """
() => {
  const ua = navigator.userAgent || "";
  const d = navigator.userAgentData || null;
  return {
    userAgent: ua,
    platform: d && d.platform ? d.platform : "",
    mobile: d && typeof d.mobile === "boolean" ? d.mobile : null,
    brands: d && Array.isArray(d.brands) ? d.brands.map(b => ({brand: b.brand, version: b.version})) : []
  };
}
"""


@dataclass(frozen=True)
class BrowserFingerprint:
    """一次会话里应当被所有请求共用的那组头。"""

    user_agent: str
    sec_ch_ua: str = ""
    sec_ch_ua_platform: str = ""
    sec_ch_ua_mobile: str = "?0"
    source: str = "browser"  # browser / derived / unknown

    def headers(self) -> Dict[str, str]:
        """要注入 HTTP 客户端的头。空值不注入——缺头好过错头。"""
        out: Dict[str, str] = {}
        if self.user_agent:
            out["user-agent"] = self.user_agent
        if self.sec_ch_ua:
            out["sec-ch-ua"] = self.sec_ch_ua
        if self.sec_ch_ua_platform:
            out["sec-ch-ua-platform"] = self.sec_ch_ua_platform
        if self.sec_ch_ua_mobile:
            out["sec-ch-ua-mobile"] = self.sec_ch_ua_mobile
        return out

    def describe(self) -> str:
        return (
            f"ua={self.user_agent[:60]}… sec-ch-ua={self.sec_ch_ua or '(无)'} "
            f"platform={self.sec_ch_ua_platform or '(无)'} source={self.source}"
        )


def _format_brands(brands: Any) -> str:
    """把 ``userAgentData.brands`` 拼成 Client Hints 的格式，保持浏览器给的顺序。"""
    parts = []
    for item in brands or []:
        if not isinstance(item, dict):
            continue
        brand = str(item.get("brand") or "").strip()
        version = str(item.get("version") or "").strip()
        if brand:
            parts.append(f'"{brand}";v="{version}"')
    return ", ".join(parts)


def _platform_from_ua(ua: str) -> str:
    for needle, value in _PLATFORM_HINTS:
        if needle in ua:
            return value
    return ""


def derive_from_user_agent(ua: str) -> BrowserFingerprint:
    """没有 ``navigator.userAgentData`` 时从 UA 串反推。

    反推不出来的字段留空（不注入），因为编一个和服务端认为的浏览器不一致的
    Client Hints，比不带这个头更容易被识别。
    """
    ua = (ua or "").strip()
    if not ua:
        return BrowserFingerprint(user_agent="", source="unknown")
    mobile = "?1" if ("Mobile" in ua and "iPad" not in ua) else "?0"
    version = ""
    match = _CHROME_VERSION_RE.search(ua)
    if match:
        version = match.group(1)
    sec_ch_ua = ""
    if version:
        # 只用 Chromium 品牌占位：不谎称 Google Chrome 的确切 GREASE 列表，
        # 但版本号必须与 UA 一致，这是关键。
        sec_ch_ua = f'"Chromium";v="{version}", "Not.A/Brand";v="99"'
    return BrowserFingerprint(
        user_agent=ua,
        sec_ch_ua=sec_ch_ua,
        sec_ch_ua_platform=_platform_from_ua(ua),
        sec_ch_ua_mobile=mobile,
        source="derived",
    )


async def read_browser_fingerprint(page: Any) -> BrowserFingerprint:
    """从活着的浏览器页面读指纹；页面不可用/JS 失败时退回 UA 反推。

    这里**不抛异常**：指纹拿不到不该让采集任务起不来，但会打日志，
    免得又出现"以为在用真实指纹、其实用的是常量"的静默降级。
    """
    raw: Optional[Dict[str, Any]] = None
    try:
        raw = await page.evaluate(_READ_JS)
    except Exception as exc:  # noqa: BLE001 — 页面可能已关闭 / 是 about:blank
        utils.logger.warning(f"[XhsFingerprint] 读取浏览器指纹失败，退回 UA 反推：{exc}")

    if not isinstance(raw, dict) or not raw.get("userAgent"):
        # 页面读不到就退到 playwright 自己能拿到的 UA（仍然比写死常量真）
        ua = ""
        try:
            ua = str(await page.evaluate("() => navigator.userAgent") or "")
        except Exception:  # noqa: BLE001
            ua = ""
        fp = derive_from_user_agent(ua)
        utils.logger.warning(f"[XhsFingerprint] 使用反推指纹：{fp.describe()}")
        return fp

    brands = _format_brands(raw.get("brands"))
    platform = str(raw.get("platform") or "")
    if platform:
        platform_header = f'"{platform}"'
    else:
        platform_header = _platform_from_ua(str(raw.get("userAgent") or ""))

    mobile_raw = raw.get("mobile")
    mobile = "?1" if mobile_raw is True else "?0"

    fp = BrowserFingerprint(
        user_agent=str(raw["userAgent"]),
        sec_ch_ua=brands,
        sec_ch_ua_platform=platform_header,
        sec_ch_ua_mobile=mobile,
        source="browser",
    )
    utils.logger.info(f"[XhsFingerprint] 指纹已从浏览器读取：{fp.describe()}")
    return fp


def fingerprint_mismatches(headers: Dict[str, str], fp: BrowserFingerprint) -> list[str]:
    """检查一组待发请求头是否与浏览器指纹矛盾，返回人类可读的差异列表。

    这是防回归用的：以后再有人手写常量，测试/日志能立刻指出来，
    而不是等账号被打成异常才回头查。
    """
    problems: list[str] = []
    if fp.user_agent and headers.get("user-agent") and headers["user-agent"] != fp.user_agent:
        problems.append(f"user-agent 与浏览器不一致：{headers['user-agent']} != {fp.user_agent}")
    for key, want in (
        ("sec-ch-ua", fp.sec_ch_ua),
        ("sec-ch-ua-platform", fp.sec_ch_ua_platform),
        ("sec-ch-ua-mobile", fp.sec_ch_ua_mobile),
    ):
        if not want:
            continue
        got = headers.get(key)
        if got and got != want:
            problems.append(f"{key} 与浏览器不一致：{got} != {want}")
    return problems
