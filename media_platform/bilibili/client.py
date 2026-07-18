# -*- coding: utf-8 -*-
# @Time    : 2023/12/2 18:44
# @Desc    : bilibili request client
import asyncio
import json
import random
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlencode

import httpx
from playwright.async_api import BrowserContext, Page
from tools.httpx_util import make_async_client

import config
from base.base_crawler import AbstractApiClient
from proxy.proxy_mixin import ProxyRefreshMixin
from tools.crawler_util import safe_int
from tools import utils

if TYPE_CHECKING:
    from proxy.proxy_ip_pool import ProxyIpPool

from .exception import DataFetchError
from .field import CommentOrderType, SearchOrderType
from .help import BilibiliSign
from tools.crawl_pacing import CrawlPacer, is_rate_limited


class BilibiliClient(AbstractApiClient, ProxyRefreshMixin):

    def __init__(
        self,
        timeout=60,  # For media crawling, Bilibili long videos need a longer timeout
        proxy=None,
        *,
        headers: Dict[str, str],
        playwright_page: Page,
        cookie_dict: Dict[str, str],
        proxy_ip_pool: Optional["ProxyIpPool"] = None,
    ):
        self.proxy = proxy
        self.timeout = timeout
        self.headers = headers
        self._host = "https://api.bilibili.com"
        self.cookie_urls = ["https://www.bilibili.com"]
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        # Initialize proxy pool (from ProxyRefreshMixin)
        self.init_proxy_pool(proxy_ip_pool)
        self._pacer = CrawlPacer(platform="bili")

    async def _read_local_storage(self) -> Dict:
        try:
            return await self.playwright_page.evaluate("() => Object.fromEntries(Object.entries(localStorage))")
        except Exception as exc:
            utils.logger.warning(
                f"[BilibiliClient] localStorage read failed: {exc}, reloading bilibili.com"
            )
            await self.playwright_page.goto(
                "https://www.bilibili.com",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            return await self.playwright_page.evaluate("() => Object.fromEntries(Object.entries(localStorage))")

    async def ensure_session_page(self) -> None:
        """Keep the Playwright tab on Bilibili so signed API calls stay valid."""
        url = self.playwright_page.url or ""
        if "bilibili.com" in url:
            return
        await self.playwright_page.goto(
            "https://www.bilibili.com",
            wait_until="domcontentloaded",
            timeout=60000,
        )

    async def request(self, method, url, **kwargs) -> Any:
        # Check if proxy has expired before each request
        await self._refresh_proxy_if_expired()

        async with make_async_client(proxy=self.proxy) as client:
            response = await client.request(method, url, timeout=self.timeout, **kwargs)
        try:
            data: Dict = response.json()
        except json.JSONDecodeError:
            utils.logger.error(f"[BilibiliClient.request] Failed to decode JSON from response. status_code: {response.status_code}, response_text: {response.text}")
            raise DataFetchError(f"Failed to decode JSON, content: {response.text}")
        if data.get("code") != 0:
            code = data.get("code")
            message = str(data.get("message", "unkonw error"))
            raise DataFetchError(
                message,
                code=code,
                rate_limited=is_rate_limited(code, message),
            )
        else:
            self._pacer.on_success()
            return data.get("data", {})

    async def pre_request_data(self, req_data: Dict) -> Dict:
        """
        Send request to sign request parameters
        Need to get wbi_img_urls parameter from localStorage, value as follows:
        https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png-https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png
        :param req_data:
        :return:
        """
        if not req_data:
            return {}
        img_key, sub_key = await self.get_wbi_keys()
        return BilibiliSign(img_key, sub_key).sign(req_data)

    async def get_wbi_keys(self) -> Tuple[str, str]:
        """
        Get the latest img_key and sub_key
        :return:
        """
        local_storage = await self._read_local_storage()
        wbi_img_urls = local_storage.get("wbi_img_urls", "")
        if not wbi_img_urls:
            img_url_from_storage = local_storage.get("wbi_img_url")
            sub_url_from_storage = local_storage.get("wbi_sub_url")
            if img_url_from_storage and sub_url_from_storage:
                wbi_img_urls = f"{img_url_from_storage}-{sub_url_from_storage}"
        if wbi_img_urls and "-" in wbi_img_urls:
            img_url, sub_url = wbi_img_urls.split("-")
        else:
            resp = await self.request(method="GET", url=self._host + "/x/web-interface/nav")
            img_url: str = resp['wbi_img']['img_url']
            sub_url: str = resp['wbi_img']['sub_url']
        img_key = img_url.rsplit('/', 1)[1].split('.')[0]
        sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
        return img_key, sub_key

    async def get(self, uri: str, params=None, enable_params_sign: bool = True) -> Dict:
        final_uri = uri
        if enable_params_sign:
            params = await self.pre_request_data(params)
        if isinstance(params, dict):
            final_uri = (f"{uri}?"
                         f"{urlencode(params)}")
        return await self.request(method="GET", url=f"{self._host}{final_uri}", headers=self.headers)

    async def post(self, uri: str, data: dict) -> Dict:
        data = await self.pre_request_data(data)
        json_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        return await self.request(method="POST", url=f"{self._host}{uri}", data=json_str, headers=self.headers)

    async def pong(self) -> bool:
        """get a note to check if login state is ok"""
        utils.logger.info("[BilibiliClient.pong] Begin pong bilibili...")
        ping_flag = False
        try:
            check_login_uri = "/x/web-interface/nav"
            response = await self.get(check_login_uri)
            if response.get("isLogin"):
                utils.logger.info("[BilibiliClient.pong] Use cache login state get web interface successfull!")
                ping_flag = True
        except Exception as e:
            utils.logger.error(f"[BilibiliClient.pong] Pong bilibili failed: {e}, and try to login again...")
            ping_flag = False
        return ping_flag

    async def update_cookies(self, browser_context: BrowserContext, urls: Optional[list[str]] = None):
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            browser_context,
            urls=urls or self.cookie_urls,
        )
        self.headers["Cookie"] = cookie_str
        self.cookie_dict = cookie_dict

    async def search_video_by_keyword(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        order: SearchOrderType = SearchOrderType.DEFAULT,
        pubtime_begin_s: int = 0,
        pubtime_end_s: int = 0,
    ) -> Dict:
        """
        KuaiShou web search api
        :param keyword: Search keyword
        :param page: Page number for pagination
        :param page_size: Number of items per page
        :param order: Sort order for search results, default is comprehensive sorting
        :param pubtime_begin_s: Publish time start timestamp
        :param pubtime_end_s: Publish time end timestamp
        :return:
        """
        uri = "/x/web-interface/wbi/search/type"
        post_data = {
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "order": order.value,
            "pubtime_begin_s": pubtime_begin_s,
            "pubtime_end_s": pubtime_end_s
        }
        return await self.get(uri, post_data)

    async def get_video_info(self, aid: Union[int, None] = None, bvid: Union[str, None] = None) -> Dict:
        """
        Bilibli web video detail api, choose one parameter between aid and bvid
        :param aid: Video aid
        :param bvid: Video bvid
        :return:
        """
        if not aid and not bvid:
            raise ValueError("Please provide at least one parameter: aid or bvid")

        uri = "/x/web-interface/view/detail"
        params = dict()
        if aid:
            params.update({"aid": aid})
        else:
            params.update({"bvid": bvid})
        return await self.get(uri, params, enable_params_sign=False)

    async def get_video_play_url(self, aid: int, cid: int) -> Dict:
        """
        Bilibli web video play url api
        :param aid: Video aid
        :param cid: cid
        :return:
        """
        if not aid or not cid or aid <= 0 or cid <= 0:
            raise ValueError("aid and cid must exist")
        uri = "/x/player/wbi/playurl"
        qn_value = getattr(config, "BILI_QN", 80)
        params = {
            "avid": aid,
            "cid": cid,
            "qn": qn_value,
            "fourk": 1,
            "fnval": 1,
            "platform": "pc",
        }

        return await self.get(uri, params, enable_params_sign=True)

    async def get_video_media(self, url: str) -> Union[bytes, None]:
        # Follow CDN 302 redirects and treat any 2xx as success (some endpoints return 206)
        async with make_async_client(proxy=self.proxy, follow_redirects=True) as client:
            try:
                response = await client.request("GET", url, timeout=self.timeout, headers=self.headers)
                response.raise_for_status()
                if 200 <= response.status_code < 300:
                    return response.content
                utils.logger.error(
                    f"[BilibiliClient.get_video_media] Unexpected status {response.status_code} for {url}"
                )
                return None
            except httpx.HTTPError as exc:  # some wrong when call httpx.request method, such as connection error, client error, server error or response status code is not 2xx
                utils.logger.error(f"[BilibiliClient.get_video_media] {exc.__class__.__name__} for {exc.request.url} - {exc}")  # Keep original exception type name for developer debugging
                return None

    async def get_video_comments(
        self,
        video_id: str,
        order_mode: CommentOrderType = CommentOrderType.DEFAULT,
        next: int = 0,
    ) -> Dict:
        """get video comments
        :param video_id: Video ID
        :param order_mode: Sort order
        :param next: Comment page selection
        :return:
        """
        uri = "/x/v2/reply/wbi/main"
        post_data = {"oid": video_id, "mode": order_mode.value, "type": 1, "ps": 20, "next": next}
        return await self.get(uri, post_data)

    async def get_video_all_comments(
        self,
        video_id: str,
        crawl_interval: float = 1.0,
        is_fetch_sub_comments=False,
        callback: Optional[Callable] = None,
        max_count: int = 10,
        order_mode: CommentOrderType = CommentOrderType.DEFAULT,
        existing_comment_ids: Optional[set[str]] = None,
        resume_next: Optional[int] = None,
        on_page_complete: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """
        get video all comments include sub comments
        :param video_id:
        :param crawl_interval:
        :param is_fetch_sub_comments:
        :param callback:
        max_count: Maximum number of comments to crawl per note
        order_mode: Comment sort order for this pass
        existing_comment_ids: IDs already saved on disk (dedupe + resume baseline)
        resume_next: Pagination cursor to resume from
        on_page_complete: Optional hook after each page for checkpointing

        :return: crawl stats dict
        """
        known_ids = set(existing_comment_ids or [])
        baseline_count = len(known_ids)
        result: List[Dict] = []
        is_end = False
        next_page = 0 if resume_next is None else resume_next
        max_retries = 3
        stopped_reason = "is_end"
        sub_extra = float(getattr(config, "BILI_SUB_COMMENT_DELAY_SEC", 0))
        max_empty_pages = int(getattr(config, "BILI_MAX_EMPTY_COMMENT_PAGES", 25))
        empty_page_streak = 0
        while not is_end and (baseline_count + len(result)) < max_count:
            comments_res = None
            for attempt in range(max_retries):
                try:
                    comments_res = await self.get_video_comments(video_id, order_mode, next_page)
                    break
                except DataFetchError as e:
                    if attempt < max_retries - 1:
                        utils.logger.warning(
                            f"[BilibiliClient.get_video_all_comments] Retrying video_id {video_id} "
                            f"(Attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        await self._pacer.sleep_on_error(attempt, rate_limited=e.rate_limited)
                    else:
                        utils.logger.error(
                            f"[BilibiliClient.get_video_all_comments] Max retries reached for "
                            f"video_id: {video_id}. Stopping this pass. Error: {e}"
                        )
                        is_end = True
                        stopped_reason = "error"
                        break
            if not comments_res:
                stopped_reason = "empty_response"
                break

            cursor_info: Dict = comments_res.get("cursor")
            if not cursor_info:
                utils.logger.warning(
                    f"[BilibiliClient.get_video_all_comments] Could not find 'cursor' in response "
                    f"for video_id: {video_id}. Stopping this pass."
                )
                stopped_reason = "missing_cursor"
                break

            comment_list: List[Dict] = comments_res.get("replies", [])

            if "is_end" not in cursor_info or "next" not in cursor_info:
                utils.logger.warning(
                    f"[BilibiliClient.get_video_all_comments] 'is_end' or 'next' not in cursor "
                    f"for video_id: {video_id}. Assuming end of comments."
                )
                is_end = True
            else:
                is_end = cursor_info.get("is_end")
                next_page = cursor_info.get("next")

            if not isinstance(is_end, bool):
                utils.logger.warning(
                    f"[BilibiliClient.get_video_all_comments] 'is_end' is not a boolean for "
                    f"video_id: {video_id}. Assuming end of comments."
                )
                is_end = True

            new_comments = [
                comment
                for comment in comment_list
                if str(comment.get("rpid")) not in known_ids
            ]
            remaining = max_count - baseline_count - len(result)
            if remaining <= 0:
                stopped_reason = "max_count"
                break
            if len(new_comments) > remaining:
                new_comments = new_comments[:remaining]
                stopped_reason = "max_count"

            if not new_comments:
                empty_page_streak += 1
                if empty_page_streak >= max_empty_pages:
                    utils.logger.info(
                        f"[BilibiliClient.get_video_all_comments] {max_empty_pages} consecutive "
                        f"pages with no new comments for video_id={video_id}, stopping pass."
                    )
                    stopped_reason = "no_new_comments"
                    break
            else:
                empty_page_streak = 0

            if is_fetch_sub_comments:
                for comment in new_comments:
                    comment_id = comment["rpid"]
                    if comment.get("rcount", 0) > 0:
                        await self.get_video_all_level_two_comments(
                            video_id,
                            comment_id,
                            order_mode,
                            10,
                            crawl_interval,
                            callback,
                        )
                        if sub_extra > 0:
                            await asyncio.sleep(sub_extra + random.uniform(0, 1))
            if callback and new_comments:
                await callback(video_id, new_comments)
            await self._pacer.sleep("after comment page")

            for comment in new_comments:
                known_ids.add(str(comment.get("rpid")))
            result.extend(new_comments)

            if on_page_complete:
                on_page_complete(
                    {
                        "next_page": next_page,
                        "is_end": is_end,
                        "new_count": len(result),
                        "total_saved": len(known_ids),
                        "order_mode": order_mode.value,
                        "stopped_reason": stopped_reason if is_end else "running",
                    }
                )

            if stopped_reason == "max_count":
                break

        if (baseline_count + len(result)) >= max_count:
            stopped_reason = "max_count"

        return {
            "new_count": len(result),
            "total_saved": len(known_ids),
            "stopped_reason": stopped_reason,
            "is_end": is_end,
            "next_page": next_page,
            "order_mode": order_mode.value,
        }

    async def get_video_all_level_two_comments(
        self,
        video_id: str,
        level_one_comment_id: int,
        order_mode: CommentOrderType,
        ps: int = 10,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
    ) -> Dict:
        """
        get video all level two comments for a level one comment
        :param video_id: Video ID
        :param level_one_comment_id: Level one comment ID
        :param order_mode:
        :param ps: Number of comments per page
        :param crawl_interval:
        :param callback:
        :return:
        """

        pn = 1
        while True:
            result = await self.get_video_level_two_comments(video_id, level_one_comment_id, pn, ps, order_mode)
            comment_list: List[Dict] = result.get("replies", [])
            if callback:
                await callback(video_id, comment_list)
            await self._pacer.sleep("after level-2 comment page")
            if (int(result["page"]["count"]) <= pn * ps):
                break

            pn += 1

    async def get_video_level_two_comments(
        self,
        video_id: str,
        level_one_comment_id: int,
        pn: int,
        ps: int,
        order_mode: CommentOrderType,
    ) -> Dict:
        """get video level two comments
        :param video_id: Video ID
        :param level_one_comment_id: Level one comment ID
        :param order_mode: Sort order

        :return:
        """
        uri = "/x/v2/reply/reply"
        post_data = {
            "oid": video_id,
            "mode": order_mode.value,
            "type": 1,
            "ps": ps,
            "pn": pn,
            "root": level_one_comment_id,
        }
        result = await self.get(uri, post_data)
        return result

    async def get_creator_videos(self, creator_id: str, pn: int, ps: int = 30, order_mode: SearchOrderType = SearchOrderType.LAST_PUBLISH) -> Dict:
        """get all videos for a creator
        :param creator_id: Creator ID
        :param pn: Page number
        :param ps: Number of videos per page
        :param order_mode: Sort order

        :return:
        """
        uri = "/x/space/wbi/arc/search"
        post_data = {
            "mid": creator_id,
            "pn": pn,
            "ps": ps,
            "order": order_mode.value if isinstance(order_mode, SearchOrderType) else order_mode,
        }
        return await self.get(uri, post_data)

    @staticmethod
    def _resolve_fetch_order(fetch_order: str) -> SearchOrderType:
        mapping = {
            "default": SearchOrderType.DEFAULT,
            "pubdate": SearchOrderType.LAST_PUBLISH,
            "click": SearchOrderType.MOST_CLICK,
            "dm": SearchOrderType.MOST_DANMU,
            "stow": SearchOrderType.MOST_MARK,
        }
        return mapping.get(fetch_order, SearchOrderType.DEFAULT)

    async def fetch_creator_video_catalog(
        self,
        creator_id: str,
        scan_all: bool = True,
        max_videos: int = 500,
        fetch_order: str = "default",
    ) -> tuple[List[Dict], int, bool]:
        """
        Paginate creator uploads and collect video metadata with comment counts.

        fetch_order only controls API page traversal order. Final ranking is always
        by comment_count after all requested videos are collected.
        """
        videos: List[Dict] = []
        pn = 1
        ps = 30
        total_videos = 0
        scan_complete = False
        order_mode = self._resolve_fetch_order(fetch_order)

        while True:
            if not scan_all and max_videos > 0 and len(videos) >= max_videos:
                break

            result = None
            for attempt in range(3):
                try:
                    await self.ensure_session_page()
                    result = await self.get_creator_videos(creator_id, pn, ps, order_mode=order_mode)
                    break
                except DataFetchError as exc:
                    if exc.rate_limited and attempt < 2:
                        await self._pacer.sleep_on_error(attempt, rate_limited=True)
                        continue
                    raise
            if result is None:
                raise DataFetchError("无法读取创作者视频列表，请稍后重试")
            vlist = result.get("list", {}).get("vlist", [])
            page_info = result.get("page", {})
            if total_videos == 0:
                total_videos = int(page_info.get("count", 0) or 0)

            if not vlist:
                scan_complete = True
                break

            for video in vlist:
                bvid = video.get("bvid", "")
                videos.append(
                    {
                        "bvid": bvid,
                        "aid": str(video.get("aid", "")),
                        "title": video.get("title", ""),
                        "comment_count": safe_int(video.get("comment")),
                        "play_count": safe_int(video.get("play")),
                        "danmaku_count": safe_int(video.get("video_review")),
                        "created": safe_int(video.get("created")),
                        "url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
                    }
                )
                if not scan_all and max_videos > 0 and len(videos) >= max_videos:
                    break
                if scan_all and max_videos > 0 and len(videos) >= max_videos:
                    break

            page_count = int(page_info.get("count", 0) or 0)
            if page_count <= pn * ps:
                scan_complete = True
                break
            if not scan_all and max_videos > 0 and len(videos) >= max_videos:
                break
            if scan_all and max_videos > 0 and len(videos) >= max_videos:
                break

            pn += 1
            await self._pacer.sleep("creator video catalog page")

        if scan_all and max_videos > 0 and len(videos) >= max_videos and total_videos > len(videos):
            scan_complete = False

        return videos, total_videos, scan_complete

    async def get_creator_info(self, creator_id: int) -> Dict:
        """
        get creator info
        :param creator_id: Creator ID
        """
        uri = "/x/space/wbi/acc/info"
        post_data = {
            "mid": creator_id,
        }
        return await self.get(uri, post_data)

    async def get_creator_fans(
        self,
        creator_id: int,
        pn: int,
        ps: int = 24,
    ) -> Dict:
        """
        get creator fans
        :param creator_id: Creator ID
        :param pn: Start page number
        :param ps: Number of items per page
        :return:
        """
        uri = "/x/relation/fans"
        post_data = {
            'vmid': creator_id,
            "pn": pn,
            "ps": ps,
            "gaia_source": "main_web",
        }
        return await self.get(uri, post_data)

    async def get_creator_followings(
        self,
        creator_id: int,
        pn: int,
        ps: int = 24,
    ) -> Dict:
        """
        get creator followings
        :param creator_id: Creator ID
        :param pn: Start page number
        :param ps: Number of items per page
        :return:
        """
        uri = "/x/relation/followings"
        post_data = {
            "vmid": creator_id,
            "pn": pn,
            "ps": ps,
            "gaia_source": "main_web",
        }
        return await self.get(uri, post_data)

    async def get_creator_dynamics(self, creator_id: int, offset: str = ""):
        """
        get creator comments
        :param creator_id: Creator ID
        :param offset: Parameter required for sending request
        :return:
        """
        uri = "/x/polymer/web-dynamic/v1/feed/space"
        post_data = {
            "offset": offset,
            "host_mid": creator_id,
            "platform": "web",
        }

        return await self.get(uri, post_data)

    async def get_creator_all_fans(
        self,
        creator_info: Dict,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
        max_count: int = 100,
    ) -> List:
        """
        get creator all fans
        :param creator_info:
        :param crawl_interval:
        :param callback:
        :param max_count: Maximum number of fans to crawl for a creator

        :return: List of creator fans
        """
        creator_id = creator_info["id"]
        result = []
        pn = config.START_CONTACTS_PAGE
        while len(result) < max_count:
            fans_res: Dict = await self.get_creator_fans(creator_id, pn=pn)
            fans_list: List[Dict] = fans_res.get("list", [])

            pn += 1
            if len(result) + len(fans_list) > max_count:
                fans_list = fans_list[:max_count - len(result)]
            if callback:  # If there is a callback function, execute it
                await callback(creator_info, fans_list)
            await asyncio.sleep(crawl_interval)
            if not fans_list:
                break
            result.extend(fans_list)
        return result

    async def get_creator_all_followings(
        self,
        creator_info: Dict,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
        max_count: int = 100,
    ) -> List:
        """
        get creator all followings
        :param creator_info:
        :param crawl_interval:
        :param callback:
        :param max_count: Maximum number of followings to crawl for a creator

        :return: List of creator followings
        """
        creator_id = creator_info["id"]
        result = []
        pn = config.START_CONTACTS_PAGE
        while len(result) < max_count:
            followings_res: Dict = await self.get_creator_followings(creator_id, pn=pn)
            followings_list: List[Dict] = followings_res.get("list", [])

            pn += 1
            if len(result) + len(followings_list) > max_count:
                followings_list = followings_list[:max_count - len(result)]
            if callback:  # If there is a callback function, execute it
                await callback(creator_info, followings_list)
            await asyncio.sleep(crawl_interval)
            if not followings_list:
                break
            result.extend(followings_list)
        return result

    async def get_creator_all_dynamics(
        self,
        creator_info: Dict,
        crawl_interval: float = 1.0,
        callback: Optional[Callable] = None,
        max_count: int = 20,
    ) -> List:
        """
        get creator all followings
        :param creator_info:
        :param crawl_interval:
        :param callback:
        :param max_count: Maximum number of dynamics to crawl for a creator

        :return: List of creator dynamics
        """
        creator_id = creator_info["id"]
        result = []
        offset = ""
        has_more = True
        while has_more and len(result) < max_count:
            dynamics_res = await self.get_creator_dynamics(creator_id, offset)
            dynamics_list: List[Dict] = dynamics_res["items"]
            has_more = dynamics_res["has_more"]
            offset = dynamics_res["offset"]
            if len(result) + len(dynamics_list) > max_count:
                dynamics_list = dynamics_list[:max_count - len(result)]
            if callback:
                await callback(creator_info, dynamics_list)
            await asyncio.sleep(crawl_interval)
            result.extend(dynamics_list)
        return result
