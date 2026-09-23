import asyncio
from typing import Optional

from playwright.async_api import BrowserContext, Page
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed

import config
from base.base_crawler import AbstractLogin
from cache.cache_factory import CacheFactory
from tools import utils
from tools.login_helper import (
    DEFAULT_LOGIN_TIMEOUT,
    has_login_cookie,
    show_qrcode_best_effort,
    wait_for_login,
)


class XiaoHongShuLogin(AbstractLogin):

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

    async def _login_confirmed(self, no_logged_in_session: str) -> bool:
        """Single, non-blocking login check (UI element or cookie change)."""
        # 1. Priority check: the "Me" (profile) entry in the sidebar.
        try:
            user_profile_selector = "xpath=//a[contains(@href, '/user/profile/')]//span[text()='我']"
            if await self.context_page.is_visible(user_profile_selector, timeout=500):
                return True
        except Exception:
            pass

        # 2. CAPTCHA notice (informational only).
        try:
            if "请通过验证" in await self.context_page.content():
                utils.logger.info("[XiaoHongShuLogin] 出现验证码，请在浏览器窗口中手动完成验证")
        except Exception:
            pass

        # 3. Cookie fallback: web_session appeared or changed.
        try:
            current_cookie = await self.browser_context.cookies()
            _, cookie_dict = utils.convert_cookies(current_cookie)
            return bool(cookie_dict.get("web_session")) and cookie_dict.get("web_session") != no_logged_in_session
        except Exception:
            return False

    @retry(stop=stop_after_attempt(600), wait=wait_fixed(1), retry=retry_if_result(lambda value: value is False))
    async def check_login_state(self, no_logged_in_session: str) -> bool:
        return await self._login_confirmed(no_logged_in_session)

    async def begin(self):
        """Start login xiaohongshu"""
        utils.logger.info("[XiaoHongShuLogin.begin] Begin login xiaohongshu ...")
        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("[XiaoHongShuLogin.begin] Invalid Login Type Currently only supported qrcode or phone or cookies ...")

    async def login_by_mobile(self):
        """Login xiaohongshu by mobile"""
        utils.logger.info("[XiaoHongShuLogin.login_by_mobile] Begin login xiaohongshu by mobile ...")
        await asyncio.sleep(1)
        try:
            login_button_ele = await self.context_page.wait_for_selector(
                selector="xpath=//*[@id='app']/div[1]/div[2]/div[1]/ul/div[1]/button",
                timeout=5000
            )
            await login_button_ele.click()
            element = await self.context_page.wait_for_selector(
                selector='xpath=//div[@class="login-container"]//div[@class="other-method"]/div[1]',
                timeout=5000
            )
            await element.click()
        except Exception:
            utils.logger.info("[XiaoHongShuLogin.login_by_mobile] have not found mobile button icon and keep going ...")

        await asyncio.sleep(1)
        login_container_ele = await self.context_page.wait_for_selector("div.login-container")
        input_ele = await login_container_ele.query_selector("label.phone > input")
        await input_ele.fill(self.login_phone)
        await asyncio.sleep(0.5)

        send_btn_ele = await login_container_ele.query_selector("label.auth-code > span")
        await send_btn_ele.click()  # Click to send verification code
        sms_code_input_ele = await login_container_ele.query_selector("label.auth-code > input")
        submit_btn_ele = await login_container_ele.query_selector("div.input-container > button")
        cache_client = CacheFactory.create_cache(config.CACHE_TYPE_MEMORY)
        max_get_sms_code_time = 60 * 2
        no_logged_in_session = ""
        while max_get_sms_code_time > 0:
            utils.logger.info(f"[XiaoHongShuLogin.login_by_mobile] get sms code from redis remaining time {max_get_sms_code_time}s ...")
            await asyncio.sleep(1)
            sms_code_key = f"xhs_{self.login_phone}"
            sms_code_value = cache_client.get(sms_code_key)
            if not sms_code_value:
                max_get_sms_code_time -= 1
                continue

            current_cookie = await self.browser_context.cookies()
            _, cookie_dict = utils.convert_cookies(current_cookie)
            no_logged_in_session = cookie_dict.get("web_session")

            await sms_code_input_ele.fill(value=sms_code_value.decode())
            await asyncio.sleep(0.5)
            agree_privacy_ele = self.context_page.locator("xpath=//div[@class='agreements']//*[local-name()='svg']")
            await agree_privacy_ele.click()
            await asyncio.sleep(0.5)
            await submit_btn_ele.click()
            break

        await wait_for_login(
            lambda: self._login_confirmed(no_logged_in_session),
            timeout=DEFAULT_LOGIN_TIMEOUT,
            label="小红书登录",
        )
        await asyncio.sleep(3)

    async def login_by_qrcode(self):
        """Login xiaohongshu by a robust QR flow (login page + cookie polling)."""
        utils.logger.info("[XiaoHongShuLogin.login_by_qrcode] Begin login xiaohongshu by qrcode ...")
        if await has_login_cookie(self.browser_context, ["web_session"]):
            return

        current_cookie = await self.browser_context.cookies()
        _, cookie_dict = utils.convert_cookies(current_cookie)
        no_logged_in_session = cookie_dict.get("web_session")

        # 登录弹窗不一定会自动出现：点一下登录按钮（失败也不致命）。
        try:
            await self.context_page.locator(
                "xpath=//*[@id='app']/div[1]/div[2]/div[1]/ul/div[1]/button"
            ).click(timeout=4000)
        except Exception:
            pass

        await show_qrcode_best_effort(
            self.context_page,
            (
                "xpath=//img[@class='qrcode-img']",
                ".qrcode-img",
                "img[src^='data:image']",
                "canvas",
            ),
        )
        utils.logger.info(
            "[XiaoHongShuLogin.login_by_qrcode] 请扫码登录小红书（也可直接在浏览器窗口中登录），"
            f"等待登录（最多 {DEFAULT_LOGIN_TIMEOUT} 秒）..."
        )
        await wait_for_login(
            lambda: self._login_confirmed(no_logged_in_session),
            timeout=DEFAULT_LOGIN_TIMEOUT,
            label="小红书登录",
        )
        utils.logger.info("[XiaoHongShuLogin.login_by_qrcode] Login successful")
        await asyncio.sleep(3)

    async def login_by_cookies(self):
        """login xiaohongshu website by cookies"""
        utils.logger.info("[XiaoHongShuLogin.login_by_cookies] Begin login xiaohongshu by cookie ...")
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            if key != "web_session":  # Only set web_session cookie attribute
                continue
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': ".rednote.com" if config.XHS_INTERNATIONAL else ".xiaohongshu.com",
                'path': "/"
            }])