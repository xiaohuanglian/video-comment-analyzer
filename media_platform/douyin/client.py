import asyncio
import copy
import json
import urllib.parse
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Union

import httpx
from playwright.async_api import BrowserContext, Page

import config
from base.base_crawler import AbstractApiClient
from proxy.proxy_mixin import ProxyRefreshMixin
from tools import utils
from tools.browser_fingerprint import BrowserFingerprint, DeviceProfile, read_browser_webid
from tools.crawl_pacing import CrawlPacer, platform_slot
from tools.httpx_util import make_async_client, make_impersonated_client
from var import request_keyword_var

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool

from .exception import *
from .field import *
from .help import *

# 抖音 Argus 网关占位头值；网关当前只校验"存在"，不校验内容。
DOUYIN_ARGUS_HEADER_VALUE = "1"

#: 媒体下载（CDN 上的视频/图集）的超时下限。业务接口 20s 足够，但一个 50MB
#: 的视频在慢网络上 20s 下不来——两者不能共用一个值，否则要么接口等太久、
#: 要么视频永远下不完。
MEDIA_MIN_TIMEOUT_SEC = 60


class DouYinClient(AbstractApiClient, ProxyRefreshMixin):

    def __init__(
        self,
        timeout: Optional[float] = None,
        proxy=None,
        *,
        headers: Dict,
        playwright_page: Optional[Page],
        cookie_dict: Dict,
        proxy_ip_pool: Optional["ProxyIpPool"] = None,
        fingerprint: Optional[BrowserFingerprint] = None,
        device_profile: Optional[DeviceProfile] = None,
        webid: str = "",
    ):
        self.proxy = proxy
        # 业务接口超时来自配置（DY_REQUEST_TIMEOUT_SEC）。以前这里硬编码 60，
        # 一个挂住的请求要占着浏览器整整一分钟，期间 pacer 也没法往下走。
        self.timeout = float(timeout if timeout is not None else getattr(config, "DY_REQUEST_TIMEOUT_SEC", 20))
        # 媒体走另一个值：短视频/图集必须给够时间，别被接口的短超时连坐。
        self.media_timeout = max(self.timeout, MEDIA_MIN_TIMEOUT_SEC)
        self._pacer = CrawlPacer(platform="dy")
        self.headers = headers
        # 抖音边缘网关 ArgusSecurityPlugin 做业务前置校验：缺 x-tt-argus 头 → 403
        # "Uifid Not Found"；有 uifid 但缺该头 → "Signature Not Found"。同步上游修复。
        self.headers.setdefault("x-tt-argus", DOUYIN_ARGUS_HEADER_VALUE)
        uifid = (cookie_dict or {}).get("UIFID") or (cookie_dict or {}).get("UIFID_TEMP", "")
        if uifid:
            self.headers.setdefault("uifid", uifid)
        self._host = "https://www.douyin.com"
        self.cookie_urls = [
            "https://douyin.com",
            self._host,
            "https://creator.douyin.com",
            "https://douhot.douyin.com",
            "https://live.douyin.com",
        ]
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        # 指纹来自跑着的浏览器（见 tools/browser_fingerprint.py）。以前这里每个
        # 请求都硬报 2560×1440 / 8 核 / Chrome 125，而真实机器是 1920×1080 /
        # Chrome 157，cookie 里的 stream_recommend_feed_params 又按真实设备写死
        # ——同一账号两套设备参数，比"参数不好看"更容易被规则直接命中。
        self.fingerprint = fingerprint
        self.device_profile = device_profile
        # webid 必须整个会话稳定：以前每个请求 get_web_id() 随机一次，
        # 等于每页都在"换设备"。
        self.webid = webid or ""
        self._ms_token_warned = False
        # Initialize proxy pool (from ProxyRefreshMixin)
        self.init_proxy_pool(proxy_ip_pool)

    async def __process_req_params(
        self,
        uri: str,
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        request_method="GET",
    ):

        if not params:
            return
        headers = headers or self.headers
        # 没有浏览器也行（纯 cookie 的调用方/单测）：拿不到 localStorage 就当作
        # 没有 msToken，而不是直接 AttributeError。
        if self.playwright_page is None:
            local_storage: Dict = {}
        else:
            local_storage = await self.playwright_page.evaluate("() => window.localStorage")  # type: ignore

        fp = self.fingerprint
        device = self.device_profile
        common_params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "version_code": "190600",
            "version_name": "19.6.0",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "cookie_enabled": "true",
            "browser_language": "zh-CN",
            "browser_platform": device.platform if device and device.platform else "MacIntel",
            "browser_name": "Chrome",
            "browser_version": fp.browser_version if fp and fp.browser_version else "125.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "os_name": "Mac OS",
            "os_version": fp.os_version if fp and fp.os_version else "10.15.7",
            "cpu_core_num": str(device.hardware_concurrency) if device and device.hardware_concurrency else "8",
            "device_memory": str(device.device_memory) if device and device.device_memory else "8",
            "engine_version": fp.engine_version if fp and fp.engine_version else "109.0",
            "platform": "PC",
            "screen_width": str(device.screen_width) if device and device.screen_width else "2560",
            "screen_height": str(device.screen_height) if device and device.screen_height else "1440",
            'effective_type': '4g',
            "round_trip_time": "50",
            "webid": await self._resolve_webid(local_storage),
        }
        # msToken 拿不到就**整个参数都不发**：发空串照样是一处异常特征，
        # 而真正的 msToken 由页面脚本续期，参数缺失比参数错误更容易被容忍。
        ms_token = self._resolve_ms_token(local_storage)
        if ms_token:
            common_params["msToken"] = ms_token
        params.update(common_params)
        query_string = urllib.parse.urlencode(params)

        # 20240927 a-bogus update (JS version)
        post_data = {}
        if request_method == "POST":
            post_data = params

        if "/v1/web/general/search" not in uri:
            a_bogus = await get_a_bogus(uri, query_string, post_data, headers["User-Agent"], self.playwright_page)
            params["a_bogus"] = a_bogus

    async def _resolve_webid(self, local_storage: Dict) -> str:
        """整个会话只认一个 webid。

        优先用浏览器里真实存在的那一个（``localStorage.user_unique_id`` /
        ``byted_acrawler.user_unique_id``），其次用构造时传进来的，最后才
        生成一个并**记住**。以前每个请求 ``get_web_id()`` 一次，等于同一台
        "设备"每秒换一次身份。
        """
        if self.webid:
            return self.webid
        candidates = (
            (local_storage or {}).get("user_unique_id"),
            (local_storage or {}).get("webid"),
        )
        for value in candidates:
            text = str(value or "").strip()
            if text.isdigit():
                self.webid = text
                utils.logger.info(f"[DouYinClient] webid 取自浏览器 localStorage：{text}")
                return text
        if self.playwright_page is not None:
            try:
                browser_webid = await read_browser_webid(self.playwright_page, label="DouYinClient")
            except Exception as exc:  # noqa: BLE001 - 取不到就退回生成
                utils.logger.debug(f"[DouYinClient] 读取浏览器 webid 失败：{exc}")
                browser_webid = ""
            if browser_webid:
                self.webid = browser_webid
                utils.logger.info(f"[DouYinClient] webid 取自页面脚本：{browser_webid}")
                return browser_webid
        self.webid = get_web_id()
        utils.logger.info(f"[DouYinClient] 浏览器未提供 webid，本次会话生成并固定为 {self.webid}")
        return self.webid

    def _resolve_ms_token(self, local_storage: Dict) -> str:
        """msToken 拿不到就**不发这个参数**（空串），不要发字符串 "None"。

        旧代码 ``local_storage.get("xmst")`` 为 None 时会被 urlencode 成
        ``msToken=None``——一个永远不可能正确的值，比不带更显眼。
        """
        token = str((local_storage or {}).get("xmst") or "").strip()
        if token and token.lower() != "none":
            return token
        if not self._ms_token_warned:
            self._ms_token_warned = True
            utils.logger.warning(
                "[DouYinClient] 浏览器 localStorage 没有 msToken（xmst），本次不带该参数；"
                "若频繁返回空响应，请先在浏览器里正常刷一次抖音页面"
            )
        return ""

    async def request(self, method, url, **kwargs):
        # Check whether the proxy has expired before each request
        await self._refresh_proxy_if_expired()

        # 平台冷却软等待 + 平台并发槽位（同平台最多 N 条并发，见 tools/crawl_pacing.py）
        await self._pacer.before_request()
        try:
            async with platform_slot("dy"):
                # 业务接口走 Chrome TLS 指纹（tools/httpx_util.py）：裸 httpx 的
                # JA3/HTTP2 指纹本身就是"这是 Python 脚本"的证据。
                async with make_impersonated_client(proxy=self.proxy) as client:
                    response = await client.request(method, url, timeout=self.timeout, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 网络层失败，交给调用方分类
            raise DataFetchError(f"请求失败：{exc}") from exc

        blocked = self._classify_response(response, url)
        if blocked is not None:
            # 关键：先落冷却再抛。以前这里只把异常包成 DataFetchError 就往上抛，
            # 上层一旦 `except DataFetchError: break` 吞掉，平台冷却根本不会写盘，
            # 下一次采集照样放行（对比 xhs/client.py 每个拦截分支都先 on_failure）。
            failure = self._pacer.on_failure(blocked)
            utils.logger.error(
                f"[DouYinClient] {method} {url} 命中拦截：{blocked}；"
                f"已落平台冷却 {failure.code}"
                f"（{failure.retry_after_seconds or 0}s）"
            )
            raise blocked

        self._pacer.on_success()
        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001 - 200 但不是 JSON
            raise DataFetchError(
                f"响应不是合法 JSON：{exc}；body 前 200 字：{self._snippet(response)}"
            ) from exc

    # -- 响应判读 ---------------------------------------------------------

    @staticmethod
    def _snippet(response: Any, limit: int = 200) -> str:
        try:
            return (response.text or "")[:limit]
        except Exception:  # noqa: BLE001
            return ""

    def _classify_response(self, response: Any, url: str) -> Optional[BaseException]:
        """把一个 HTTP 响应判成"正常 / 哪一类拦截"，正常返回 None。

        判据顺序是刻意的：先看 HTTP 状态（平台明确拒绝），再看 body 形态
        （空 / 挑战页 / 业务错误码）。**不要去 JSON body 里搜"验证码"这类词**
        ——评论正文本身就可能包含这些词，那样会把一条正常评论判成风控。
        """
        status = int(getattr(response, "status_code", 0) or 0)
        text = (getattr(response, "text", "") or "").strip()
        snippet = text[:200]

        if status in (401, 403):
            # 抖音的 403 有两种：账号/接口拒绝访问，以及我们自己的签名/头校验失败
            # （"Uifid Not Found" / "Signature Not Found"）。两种都必须停手：
            # 签名已经不被接受了还继续打，就是 2026-11-11 那次事故的放大方式。
            # 区别只在文案里写清楚，方便人判断是"账号被限"还是"该修签名了"。
            return PlatformAccessError(f"HTTP {status}：{snippet}")
        if status == 429:
            return RateLimitError(f"HTTP 429 请求过于频繁：{snippet}")
        if status >= 500:
            # 服务端抖动不是账号问题：不落冷却，交给外层重试/记录
            raise DataFetchError(f"HTTP {status} 平台服务端错误：{snippet}")
        if status == 0:
            return DataFetchError(f"没有拿到 HTTP 响应：{snippet}")

        if text == "" or text == "blocked":
            # 空响应是抖音 Web 接口最典型的"不给你数据"：可能是签名失效，
            # 也可能是账号/设备被标记。两种都不该继续翻页。
            return DouYinAccountBlockedError(f"接口返回空响应或被标记 blocked（HTTP {status}）")

        if text.lstrip().startswith("<"):
            # HTML 而不是 JSON：挑战页 / 验证页 / 风控中间页
            head = text.lstrip()[:4000].lower()
            if any(marker in head for marker in ("captcha", "secsdk", "验证", "verify")):
                return CaptchaError(f"返回验证页（HTTP {status}）：{snippet}")
            return DouYinAccountBlockedError(f"返回非 JSON 页面（HTTP {status}）：{snippet}")

        # 业务错误码：只在"没有拿到任何预期数据"时才当失败，避免把
        # "这一页就是没有更多了"误判成风控。
        try:
            data = response.json()
        except Exception:  # noqa: BLE001 - 交给外层按非法 JSON 处理
            return None
        if not isinstance(data, dict):
            return None
        status_code = data.get("status_code")
        message = str(data.get("status_msg") or data.get("message") or "").strip()
        has_payload = any(
            key in data
            for key in ("data", "comments", "aweme_detail", "aweme_list", "has_more", "cursor", "user")
        )
        if status_code not in (None, 0) and not has_payload and message:
            exc = DataFetchError(f"业务错误码 {status_code}：{message}")
            # 文案里若是"风控/频繁/验证码"之类，升级成必须停手的类型
            from tools.crawl_pacing import PLATFORM_BLOCKED, RATE_LIMITED, classify_failure

            code = classify_failure(exc, platform="dy").code
            if code == PLATFORM_BLOCKED:
                return DouYinAccountBlockedError(f"业务错误码 {status_code}：{message}")
            if code == RATE_LIMITED:
                return RateLimitError(f"业务错误码 {status_code}：{message}")
            return exc
        return None


    async def get(self, uri: str, params: Optional[Dict] = None, headers: Optional[Dict] = None):
        """
        GET请求
        """
        await self.__process_req_params(uri, params, headers)
        headers = headers or self.headers
        return await self.request(method="GET", url=f"{self._host}{uri}", params=params, headers=headers)

    async def post(self, uri: str, data: dict, headers: Optional[Dict] = None):
        await self.__process_req_params(uri, data, headers)
        headers = headers or self.headers
        return await self.request(method="POST", url=f"{self._host}{uri}", data=data, headers=headers)

    async def pong(self, browser_context: BrowserContext) -> bool:
        local_storage = await self.playwright_page.evaluate("() => window.localStorage")
        if local_storage.get("HasUserLogin", "") == "1":
            return True

        _, cookie_dict = await utils.convert_browser_context_cookies(
            browser_context,
            urls=self.cookie_urls,
        )
        return cookie_dict.get("LOGIN_STATUS") == "1"

    async def update_cookies(self, browser_context: BrowserContext, urls: Optional[list[str]] = None):
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            browser_context,
            urls=urls or self.cookie_urls,
        )
        self.headers["Cookie"] = cookie_str
        self.cookie_dict = cookie_dict

    async def search_info_by_keyword(
        self,
        keyword: str,
        offset: int = 0,
        search_channel: SearchChannelType = SearchChannelType.GENERAL,
        sort_type: SearchSortType = SearchSortType.GENERAL,
        publish_time: PublishTimeType = PublishTimeType.UNLIMITED,
        search_id: str = "",
    ):
        """
        DouYin Web Search API
        :param keyword:
        :param offset:
        :param search_channel:
        :param sort_type:
        :param publish_time: ·
        :param search_id: ·
        :return:
        """
        query_params = {
            'search_channel': search_channel.value,
            'enable_history': '1',
            'keyword': keyword,
            'search_source': 'tab_search',
            'query_correct_type': '1',
            'is_filter_search': '0',
            'from_group_id': '7378810571505847586',
            'offset': offset,
            'count': '15',
            'need_filter_settings': '1',
            'list_type': 'multi',
            'search_id': search_id,
        }
        if sort_type.value != SearchSortType.GENERAL.value or publish_time.value != PublishTimeType.UNLIMITED.value:
            query_params["filter_selected"] = json.dumps({"sort_type": str(sort_type.value), "publish_time": str(publish_time.value)})
            query_params["is_filter_search"] = 1
            query_params["search_source"] = "tab_search"
        referer_url = f"https://www.douyin.com/search/{keyword}?aid=f594bbd9-a0e2-4651-9319-ebe3cb6298c1&type=general"
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=':/')
        return await self.get("/aweme/v1/web/general/search/single/", query_params, headers=headers)

    async def get_video_by_id(self, aweme_id: str) -> Any:
        """
        DouYin Video Detail API
        :param aweme_id:
        :return:
        """
        # detail 接口要求 uifid 与 s_v_web_id 成套出现，缺一则 403 "Uifid Not Found"
        s_v_web_id = (self.cookie_dict or {}).get("s_v_web_id", "")
        params = {
            "aweme_id": aweme_id,
            "uifid": (self.cookie_dict or {}).get("UIFID") or (self.cookie_dict or {}).get("UIFID_TEMP", ""),
            "verifyFp": s_v_web_id,
            "fp": s_v_web_id,
        }
        headers = copy.copy(self.headers)
        del headers["Origin"]
        res = await self.get("/aweme/v1/web/aweme/detail/", params, headers)
        return res.get("aweme_detail", {})

    async def get_aweme_comments(self, aweme_id: str, cursor: int = 0):
        """get note comments

        """
        uri = "/aweme/v1/web/comment/list/"
        params = {"aweme_id": aweme_id, "cursor": cursor, "count": 20, "item_type": 0}
        keywords = request_keyword_var.get()
        referer_url = "https://www.douyin.com/search/" + keywords + '?aid=3a3cec5a-9e27-4040-b6aa-ef548c2c1138&publish_time=0&sort_type=0&source=search_history&type=general'
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=':/')
        return await self.get(uri, params)

    async def get_sub_comments(self, aweme_id: str, comment_id: str, cursor: int = 0):
        """
            获取子评论
        """
        uri = "/aweme/v1/web/comment/list/reply/"
        params = {
            'comment_id': comment_id,
            "cursor": cursor,
            "count": 20,
            "item_type": 0,
            "item_id": aweme_id,
        }
        keywords = request_keyword_var.get()
        referer_url = "https://www.douyin.com/search/" + keywords + '?aid=3a3cec5a-9e27-4040-b6aa-ef548c2c1138&publish_time=0&sort_type=0&source=search_history&type=general'
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=':/')
        return await self.get(uri, params)

    async def get_aweme_all_comments(
        self,
        aweme_id: str,
        crawl_interval: float = 1.0,
        is_fetch_sub_comments=False,
        callback: Optional[Callable] = None,
        max_count: int = 10,
    ):
        """
        获取帖子的所有评论，包括子评论
        :param aweme_id: 帖子ID
        :param crawl_interval: 抓取间隔
        :param is_fetch_sub_comments: 是否抓取子评论
        :param callback: 回调函数，用于处理抓取到的评论
        :param max_count: 一次帖子爬取的最大评论数量
        :return: 评论列表
        """
        result = []
        comments_has_more = 1
        comments_cursor = 0
        empty_pages = 0
        page_index = 0
        while comments_has_more and len(result) < max_count:
            try:
                comments_res = await self.get_aweme_comments(aweme_id, comments_cursor)
            except ABORT_EXCEPTIONS:
                # 账号级拦截必须往上抛：这里要是吞成 break，main.py 会把这次
                # 采集当成"跑通了"并清掉刚落的冷却（2026-11-11 的教训）。
                raise
            except Exception as exc:  # noqa: BLE001 - 保留已抓部分，记录原因后退出
                utils.logger.warning(
                    f"[DouYinClient.get_aweme_all_comments] aweme_id={aweme_id} 第 {page_index + 1} 页获取失败：{exc}；"
                    f"保留已抓 {len(result)} 条并停止翻页"
                )
                break
            page_index += 1
            comments_has_more = comments_res.get("has_more", 0)
            comments_cursor = comments_res.get("cursor", 0)
            comments = comments_res.get("comments") or []
            if not comments:
                # 风控或翻页卡住时平台可能返回空页：退避重试几次后退出，避免空转打爆接口
                empty_pages += 1
                await self._pacer.sleep("empty comment page")
                if empty_pages >= 3:
                    utils.logger.warning(
                        f"[DouYinClient.get_aweme_all_comments] aweme_id={aweme_id} "
                        f"连续 {empty_pages} 页无评论，停止翻页（可能触发风控或已无更多评论）"
                    )
                    break
                continue
            empty_pages = 0
            if len(result) + len(comments) > max_count:
                comments = comments[:max_count - len(result)]
            result.extend(comments)
            if callback:  # If there is a callback function, execute the callback function
                await callback(aweme_id, comments)

            await self._pacer.sleep("after aweme comment page")
            if not is_fetch_sub_comments:
                continue
            # Get secondary reviews
            for comment in comments:
                reply_comment_total = comment.get("reply_comment_total")

                if reply_comment_total > 0:
                    comment_id = comment.get("cid")
                    sub_comments_has_more = 1
                    sub_comments_cursor = 0
                    empty_sub_pages = 0

                    while sub_comments_has_more:
                        try:
                            sub_comments_res = await self.get_sub_comments(aweme_id, comment_id, sub_comments_cursor)
                        except ABORT_EXCEPTIONS:
                            raise
                        except Exception as exc:  # noqa: BLE001
                            utils.logger.warning(
                                f"[DouYinClient.get_aweme_all_comments] aweme_id={aweme_id} 子评论获取失败：{exc}；跳过该条"
                            )
                            break
                        sub_comments_has_more = sub_comments_res.get("has_more", 0)
                        sub_comments_cursor = sub_comments_res.get("cursor", 0)
                        sub_comments = sub_comments_res.get("comments") or []

                        if not sub_comments:
                            empty_sub_pages += 1
                            await self._pacer.sleep("empty sub-comment page")
                            if empty_sub_pages >= 3:
                                break
                            continue
                        empty_sub_pages = 0
                        result.extend(sub_comments)
                        if callback:  # If there is a callback function, execute the callback function
                            await callback(aweme_id, sub_comments)
                        await self._pacer.sleep("after sub-comment page")
        return result

    async def get_user_info(self, sec_user_id: str):
        uri = "/aweme/v1/web/user/profile/other/"
        params = {
            "sec_user_id": sec_user_id,
            "publish_video_strategy_type": 2,
            "personal_center_strategy": 1,
        }
        return await self.get(uri, params)

    async def get_user_aweme_posts(self, sec_user_id: str, max_cursor: str = "") -> Dict:
        uri = "/aweme/v1/web/aweme/post/"
        params = {
            "sec_user_id": sec_user_id,
            "count": 18,
            "max_cursor": max_cursor,
            "locate_query": "false",
            "publish_video_strategy_type": 2,
        }
        return await self.get(uri, params)

    async def get_all_user_aweme_posts(self, sec_user_id: str, callback: Optional[Callable] = None):
        posts_has_more = 1
        max_cursor = ""
        result = []
        page_index = 0
        while posts_has_more == 1:
            if page_index:
                # 这条循环以前一页接一页地打，没有任何等待——创作者主页作品
                # 上千条时会变成最密集的一段请求。
                await self._pacer.sleep("after creator aweme page")
            page_index += 1
            aweme_post_res = await self.get_user_aweme_posts(sec_user_id, max_cursor)
            posts_has_more = aweme_post_res.get("has_more", 0)
            max_cursor = aweme_post_res.get("max_cursor")
            aweme_list = aweme_post_res.get("aweme_list") if aweme_post_res.get("aweme_list") else []
            utils.logger.info(f"[DouYinClient.get_all_user_aweme_posts] get sec_user_id:{sec_user_id} video len : {len(aweme_list)}")
            if callback:
                await callback(aweme_list)
            result.extend(aweme_list)
        return result

    async def get_aweme_media(self, url: str) -> Union[bytes, None]:
        """下载图片/视频。

        这一层走普通 httpx 而**不是** TLS 指纹客户端：媒体在 CDN 上，风控判定
        不在这一跳；而且这里要处理大文件流，curl_cffi 的适配层没必要背这个包袱。
        """
        async with make_async_client(proxy=self.proxy) as client:
            try:
                response = await client.request("GET", url, timeout=self.media_timeout, follow_redirects=True)
                response.raise_for_status()
                if not response.reason_phrase == "OK":
                    utils.logger.error(f"[DouYinClient.get_aweme_media] request {url} err, res:{response.text[:200]}")
                    return None
                else:
                    return response.content
            except httpx.HTTPError as exc:  # some wrong when call httpx.request method, such as connection error, client error, server error or response status code is not 2xx
                utils.logger.error(f"[DouYinClient.get_aweme_media] {exc.__class__.__name__} for {url} - {exc}")  # Keep the original exception type name for developers to debug
                return None

    async def resolve_short_url(self, short_url: str) -> str:
        """
        解析抖音短链接,获取重定向后的真实URL
        Args:
            short_url: 短链接,如 https://v.douyin.com/iF12345ABC/
        Returns:
            重定向后的完整URL
        """
        async with make_async_client(proxy=self.proxy, follow_redirects=False) as client:
            try:
                utils.logger.info(f"[DouYinClient.resolve_short_url] Resolving short URL: {short_url}")
                response = await client.get(short_url, timeout=10)

                # Short links usually return a 302 redirect
                if response.status_code in [301, 302, 303, 307, 308]:
                    redirect_url = response.headers.get("Location", "")
                    utils.logger.info(f"[DouYinClient.resolve_short_url] Resolved to: {redirect_url}")
                    return redirect_url
                else:
                    utils.logger.warning(f"[DouYinClient.resolve_short_url] Unexpected status code: {response.status_code}")
                    return ""
            except Exception as e:
                utils.logger.error(f"[DouYinClient.resolve_short_url] Failed to resolve short URL: {e}")
                return ""
