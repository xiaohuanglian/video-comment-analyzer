import asyncio
from typing import Optional

from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from tenacity import retry, retry_if_result, stop_after_attempt, wait_fixed

import config
from base.base_crawler import AbstractLogin
from cache.cache_factory import CacheFactory
from tools import utils
from tools.crawl_pacing import CrawlPacer
from tools.login_helper import (
    DEFAULT_LOGIN_TIMEOUT,
    has_login_cookie,
    show_qrcode_best_effort,
    wait_for_login,
)

from .exception import CaptchaError


class DouYinLogin(AbstractLogin):

    def __init__(self,
                 login_type: str,
                 browser_context: BrowserContext, # type: ignore
                 context_page: Page, # type: ignore
                 login_phone: Optional[str] = "",
                 cookie_str: Optional[str] = ""
                 ):
        config.LOGIN_TYPE = login_type
        self.browser_context = browser_context
        self.context_page = context_page
        self.login_phone = login_phone
        self.scan_qrcode_time = 60
        self.cookie_str = cookie_str

    async def _login_confirmed(self) -> bool:
        """Single, non-blocking login check (localStorage / cookie)."""
        try:
            current_cookie = await self.browser_context.cookies()
            _, cookie_dict = utils.convert_cookies(current_cookie)
            if cookie_dict.get("LOGIN_STATUS") == "1":
                return True
        except Exception:
            pass
        for page in self.browser_context.pages:
            try:
                local_storage = await page.evaluate("() => window.localStorage")
                if local_storage.get("HasUserLogin", "") == "1":
                    return True
            except Exception:
                continue
        return False

    # 600 次 × 每秒一次 = 10 分钟的轮询。这个包装从来没有被调用过（begin() 用的是
    # login_helper.wait_for_login，超时自己带），但留着就是一颗"谁 import 谁中招"
    # 的雷：对一个已经被标记的账号每分钟打 60 次登录态检查，是最标准的机器特征。
    # 改成与 wait_for_login 同量级的次数，并且每次间隔 2s。
    @retry(
        stop=stop_after_attempt(150),
        wait=wait_fixed(2),
        retry=retry_if_result(lambda value: value is False),
        reraise=True,
    )
    async def check_login_state(self) -> bool:
        return await self._login_confirmed()

    async def begin(self):
        """
            Start login douyin website.
            The slider verification is unreliable; cookie login is recommended
            when available. We never kill the process on failure — we raise a
            clear error so the Web UI can show it.
        """
        if await has_login_cookie(self.browser_context, ["LOGIN_STATUS"]):
            return

        await self.popup_login_dialog()

        if config.LOGIN_TYPE == "qrcode":
            await self.login_by_qrcode()
        elif config.LOGIN_TYPE == "phone":
            await self.login_by_mobile()
        elif config.LOGIN_TYPE == "cookie":
            await self.login_by_cookies()
        else:
            raise ValueError("[DouYinLogin.begin] Invalid Login Type Currently only supported qrcode or phone or cookie ...")

        if config.LOGIN_TYPE != "cookie":
            utils.logger.info(
                "[DouYinLogin.begin] 请在浏览器窗口中扫码/登录抖音，"
                f"等待登录（最多 {DEFAULT_LOGIN_TIMEOUT} 秒）..."
            )
            await wait_for_login(self._login_confirmed, timeout=DEFAULT_LOGIN_TIMEOUT, label="抖音登录")

        # If the page redirects to the slider verification page, try once more.
        await asyncio.sleep(6)
        try:
            current_page_title = await self.context_page.title()
            if "验证码中间页" in current_page_title:
                await self.check_page_display_slider(move_step=3, slider_level="hard")
        except CaptchaError:
            # 验证码过不去 = 平台明确拒绝这个账号：落冷却并抛回去，
            # 让 main.py 走失败分支（不 clear 冷却、退出码 3）。
            CrawlPacer(platform="dy").on_failure(
                CaptchaError("登录时遇到滑块验证且自动尝试未通过")
            )
            raise
        except Exception as exc:
            utils.logger.warning(f"[DouYinLogin.begin] slider check skipped: {exc}")

        await asyncio.sleep(3)

    async def popup_login_dialog(self):
        """If the login dialog does not pop up automatically, click the login button (best effort)."""
        dialog_selector = "xpath=//div[@id='login-panel-new']"
        try:
            await self.context_page.wait_for_selector(dialog_selector, timeout=1000 * 8)
            return
        except Exception:
            utils.logger.info("[DouYinLogin.popup_login_dialog] login dialog not auto-opened, clicking 登录 ...")
        try:
            login_button_ele = self.context_page.locator("xpath=//p[text() = '登录']")
            await login_button_ele.click(timeout=5000)
            await asyncio.sleep(0.5)
        except Exception as exc:
            utils.logger.warning(f"[DouYinLogin.popup_login_dialog] could not click login button: {exc}")

    async def login_by_qrcode(self):
        utils.logger.info("[DouYinLogin.login_by_qrcode] Begin login douyin by qrcode...")
        await show_qrcode_best_effort(
            self.context_page,
            (
                "xpath=//div[@id='animate_qrcode_container']//img",
                "#animate_qrcode_container img",
                "img[src^='data:image']",
                "canvas",
            ),
        )

    async def login_by_mobile(self):
        utils.logger.info("[DouYinLogin.login_by_mobile] Begin login douyin by mobile ...")
        mobile_tap_ele = self.context_page.locator("xpath=//li[text() = '验证码登录']")
        await mobile_tap_ele.click()
        await self.context_page.wait_for_selector("xpath=//article[@class='web-login-mobile-code']")
        mobile_input_ele = self.context_page.locator("xpath=//input[@placeholder='手机号']")
        await mobile_input_ele.fill(self.login_phone)
        await asyncio.sleep(0.5)
        send_sms_code_btn = self.context_page.locator("xpath=//span[text() = '获取验证码']")
        await send_sms_code_btn.click()

        # Check if there is slider verification
        await self.check_page_display_slider(move_step=10, slider_level="easy")
        cache_client = CacheFactory.create_cache(config.CACHE_TYPE_MEMORY)
        max_get_sms_code_time = 60 * 2  # Maximum time to get verification code is 2 minutes
        while max_get_sms_code_time > 0:
            utils.logger.info(f"[DouYinLogin.login_by_mobile] get douyin sms code from redis remaining time {max_get_sms_code_time}s ...")
            await asyncio.sleep(1)
            sms_code_key = f"dy_{self.login_phone}"
            sms_code_value = cache_client.get(sms_code_key)
            if not sms_code_value:
                max_get_sms_code_time -= 1
                continue

            sms_code_input_ele = self.context_page.locator("xpath=//input[@placeholder='请输入验证码']")
            await sms_code_input_ele.fill(value=sms_code_value.decode())
            await asyncio.sleep(0.5)
            submit_btn_ele = self.context_page.locator("xpath=//button[@class='web-login-button']")
            await submit_btn_ele.click()  # Click login
            break

    async def check_page_display_slider(self, move_step: int = 10, slider_level: str = "easy"):
        """遇到滑块验证时尝试通过；过不去就**停手**，不要反复刷。

        旧实现有三个问题叠在一起：20 次尝试、失败后点"刷新验证码"、
        而刷新**不扣尝试次数**——等于可以无限刷。对已经被标记的账号，
        每多刷一次都是在给平台补一条"这是机器"的证据。

        现在的规则：
        - 主动尝试 ``DY_SLIDER_MAX_ATTEMPTS`` 次；
        - 刷新验证码最多 ``DY_SLIDER_MAX_REFRESH`` 次，并且**计入**尝试次数；
        - 仍然过不去就抛 :class:`CaptchaError`（会走平台冷却），
          提示人去浏览器窗口里手动过。
        """
        back_selector = "#captcha-verify-image"
        try:
            await self.context_page.wait_for_selector(selector=back_selector, state="visible", timeout=20 * 1000)
        except PlaywrightTimeoutError:  # No slider verification, return directly
            return

        gap_selector = 'xpath=//*[@id="captcha_container"]/div/div[2]/img[2]'
        max_attempts = max(1, int(getattr(config, "DY_SLIDER_MAX_ATTEMPTS", 3)))
        max_refresh = max(0, int(getattr(config, "DY_SLIDER_MAX_REFRESH", 1)))
        attempts = 0
        refreshed = 0
        while True:
            if attempts >= max_attempts:
                # 抛 CaptchaError 而不是 RuntimeError：调用方能按"平台拦截"处理
                # （落冷却、停批、退出码 3），而不是当成一个普通 bug 继续跑。
                raise CaptchaError(
                    f"抖音滑块验证连续 {attempts} 次未通过：请在浏览器窗口中手动完成验证后重试。"
                    f"（已停止自动重试，避免对已被标记的账号继续加压）"
                )
            attempts += 1
            try:
                await self.move_slider(back_selector, gap_selector, move_step, slider_level)
                await asyncio.sleep(1)

                page_content = await self.context_page.content()
                if "操作过慢" in page_content or "提示重新操作" in page_content:
                    if refreshed < max_refresh:
                        refreshed += 1
                        utils.logger.info(
                            f"[DouYinLogin.check_page_display_slider] 验证失败，刷新验证码"
                            f"（{refreshed}/{max_refresh}，计入尝试次数）..."
                        )
                        await self.context_page.click(selector="//a[contains(@class, 'secsdk_captcha_refresh')]")
                    else:
                        utils.logger.warning(
                            "[DouYinLogin.check_page_display_slider] 验证失败且刷新次数已用尽"
                        )
                    continue

                await self.context_page.wait_for_selector(selector=back_selector, state="hidden", timeout=1000)
                utils.logger.info("[DouYinLogin.check_page_display_slider] slider verify success ...")
                return
            except CaptchaError:
                raise
            except Exception as e:
                utils.logger.error(
                    f"[DouYinLogin.check_page_display_slider] 第 {attempts}/{max_attempts} 次失败：{e}"
                )
                await asyncio.sleep(1)
                continue

    async def move_slider(self, back_selector: str, gap_selector: str, move_step: int = 10, slider_level="easy"):
        """Move the slider to the right to complete the verification."""

        slider_back_elements = await self.context_page.wait_for_selector(
            selector=back_selector,
            timeout=1000 * 10,
        )
        slide_back = str(await slider_back_elements.get_property("src")) # type: ignore

        gap_elements = await self.context_page.wait_for_selector(
            selector=gap_selector,
            timeout=1000 * 10,
        )
        gap_src = str(await gap_elements.get_property("src")) # type: ignore

        slide_app = utils.Slide(gap=gap_src, bg=slide_back)
        distance = slide_app.discern()

        tracks = utils.get_tracks(distance, slider_level)
        new_1 = tracks[-1] - (sum(tracks) - distance)
        tracks.pop()
        tracks.append(new_1)

        element = await self.context_page.query_selector(gap_selector)
        bounding_box = await element.bounding_box() # type: ignore

        await self.context_page.mouse.move(bounding_box["x"] + bounding_box["width"] / 2, # type: ignore
                                           bounding_box["y"] + bounding_box["height"] / 2) # type: ignore
        x = bounding_box["x"] + bounding_box["width"] / 2 # type: ignore
        await element.hover() # type: ignore
        await self.context_page.mouse.down()

        for track in tracks:
            await self.context_page.mouse.move(x + track, 0, steps=move_step)
            x += track
        await self.context_page.mouse.up()

    async def login_by_cookies(self):
        utils.logger.info("[DouYinLogin.login_by_cookies] Begin login douyin by cookie ...")
        for key, value in utils.convert_str_cookie_to_dict(self.cookie_str).items():
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': ".douyin.com",
                'path': "/"
            }])