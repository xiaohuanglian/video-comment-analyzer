# -*- coding: utf-8 -*-
# @Time    : 2023/12/2 18:44
# @Desc    : bilibili login implementation class

import asyncio
import functools
from typing import Optional

from playwright.async_api import BrowserContext, Page
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed

import config
from base.base_crawler import AbstractLogin
from tools import utils

BILIBILI_LOGIN_URL = "https://passport.bilibili.com/login"
LOGIN_WAIT_SECONDS = 300
# Selectors are tried in order; keep several because Bilibili rewrites markup.
QRCODE_IMAGE_SELECTORS = (
    "img[src^='data:image']",
    ".login-scan-box img",
    ".qrcode-img",
    "#login_qr_guide img",
)


class BilibiliLogin(AbstractLogin):
    def __init__(self,
                 login_type: str,
                 browser_context: BrowserContext,
                 context_page: Page,
                 login_phone: Optional[str] = "",
                 cookie_str: str = ""
                 ):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.cookie_str = cookie_str

    async def begin(self):
        """Start login bilibili"""
        utils.logger.info("[BilibiliLogin.begin] Begin login Bilibili ...")
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError(
                "[BilibiliLogin.begin] Invalid Login Type Currently only supported qrcode or phone or cookie ...")

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self) -> bool:
        """
            Check if the current login status is successful and return True otherwise return False
            retry decorator will retry 20 times if the return value is False, and the retry interval is 1 second
            if max retry times reached, raise RetryError
        """
        current_cookie = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookie)
        if cookie_dict.get("SESSDATA", "") or cookie_dict.get("DedeUserID"):
            return True
        return False

    async def login_by_qrcode(self):
        """Log in via Bilibili's passport page.

        We no longer click the homepage login button (its DOM changes Often and
        caused hard 30s timeouts). Instead we open the dedicated login page and
        wait until a login cookie appears. When the browser is visible the user
        can scan / log in there directly; we also try to render the QR code in
        the terminal as a best-effort convenience.
        """
        utils.logger.info("[BilibiliLogin.login_by_qrcode] Begin login bilibili by qrcode ...")

        if await self._has_login_cookie():
            return

        try:
            await self.context_page.goto(
                BILIBILI_LOGIN_URL, wait_until="domcontentloaded", timeout=60000
            )
        except Exception as exc:  # noqa: BLE001 - best effort; user can log in manually
            utils.logger.warning(
                f"[BilibiliLogin.login_by_qrcode] open login page failed: {exc}; "
                "please log in in the opened browser window"
            )

        await self._show_qrcode_if_possible()
        utils.logger.info(
            "[BilibiliLogin.login_by_qrcode] 请在打开的浏览器窗口中扫码/登录 B 站，"
            f"等待登录（最多 {LOGIN_WAIT_SECONDS} 秒）..."
        )
        await self._wait_for_login()
        utils.logger.info(
            "[BilibiliLogin.login_by_qrcode] Login successful, wait 3 seconds for redirect ..."
        )
        await asyncio.sleep(3)

    async def _has_login_cookie(self) -> bool:
        current_cookie = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookie)
        return bool(cookie_dict.get("SESSDATA") or cookie_dict.get("DedeUserID"))

    async def _show_qrcode_if_possible(self) -> None:
        base64_qrcode_img = ""
        for selector in QRCODE_IMAGE_SELECTORS:
            try:
                base64_qrcode_img = await utils.find_login_qrcode(self.context_page, selector=selector)
            except Exception:
                base64_qrcode_img = ""
            if base64_qrcode_img:
                break
        if not base64_qrcode_img:
            try:
                base64_qrcode_img = await utils.find_qrcode_img_from_canvas(self.context_page, selector="canvas")
            except Exception:
                base64_qrcode_img = ""
        if not base64_qrcode_img:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, functools.partial(utils.show_qrcode, base64_qrcode_img))
        except Exception as exc:  # noqa: BLE001 - terminal display is optional
            utils.logger.warning(f"[BilibiliLogin.login_by_qrcode] show qrcode failed: {exc}")

    async def _wait_for_login(self) -> None:
        deadline = asyncio.get_running_loop().time() + LOGIN_WAIT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            if await self._has_login_cookie():
                return
            await asyncio.sleep(2)
        raise RuntimeError(
            "B 站登录超时：请在打开的浏览器窗口中完成登录后重试"
            "（若浏览器未弹出，可设置环境变量 BILI_QRCODE=... 或使用 cookie 登录）"
        )

    async def login_by_mobile(self):
        pass

    async def login_by_cookies(self):
        utils.logger.info("[BilibiliLogin.login_by_qrcode] Begin login bilibili by cookie ...")
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': ".bilibili.com",
                'path': "/"
            }])
