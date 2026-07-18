# -*- coding: utf-8 -*-

import asyncio
import re
from typing import Callable, Dict, List, Optional
from urllib.parse import quote

from playwright.async_api import async_playwright

import config
from media_platform.bilibili import BilibiliCrawler
from media_platform.bilibili.help import parse_creator_info_from_url as parse_bili_creator
from media_platform.douyin import DouYinCrawler
from media_platform.douyin.help import parse_creator_info_from_url as parse_dy_creator
from media_platform.kuaishou import KuaishouCrawler
from media_platform.kuaishou.help import parse_creator_info_from_url as parse_ks_creator
from media_platform.tieba import TieBaCrawler
from media_platform.weibo import WeiboCrawler
from media_platform.xhs import XiaoHongShuCrawler
from media_platform.xhs.help import parse_creator_info_from_url as parse_xhs_creator
from media_platform.zhihu import ZhihuCrawler
from model.m_zhihu import ZhihuCreator
from tools.crawler_util import safe_int
from tools import utils
from .platform_capabilities import get_platform_capabilities

_rank_lock = asyncio.Lock()

CRAWLER_MAP = {
    "bili": BilibiliCrawler,
    "dy": DouYinCrawler,
    "ks": KuaishouCrawler,
    "xhs": XiaoHongShuCrawler,
    "wb": WeiboCrawler,
    "zhihu": ZhihuCrawler,
    "tieba": TieBaCrawler,
}


def _cap_catalog(catalog: List[Dict], scan_all: bool, max_videos: int) -> tuple[List[Dict], bool]:
    scan_complete = True
    if max_videos > 0 and len(catalog) >= max_videos:
        catalog = catalog[:max_videos]
        if scan_all:
            scan_complete = False
    return catalog, scan_complete


def _finalize_rank(
    platform: str,
    creator_id: str,
    creator_name: str,
    catalog: List[Dict],
    top_n: int,
    *,
    total_videos: int = 0,
    scan_complete: bool = True,
    scan_all: bool = True,
    fetch_order: str = "default",
) -> dict:
    capabilities = get_platform_capabilities(platform)
    metric_label = capabilities.get("engagement_metric", "平台互动")
    ranked = sorted(catalog, key=lambda item: safe_int(item.get("comment_count")), reverse=True)
    top_videos: List[Dict] = []
    for index, item in enumerate(ranked[:top_n], start=1):
        video_id = str(item.get("video_id") or item.get("bvid") or "")
        bvid = str(item.get("bvid") or "")
        top_videos.append(
            {
                "rank": index,
                "video_id": video_id,
                "title": item.get("title") or "",
                "comment_count": safe_int(item.get("comment_count")),
                "play_count": safe_int(item.get("play_count")),
                "url": item.get("url") or "",
                "id_label": item.get("id_label") or bvid or video_id,
                "metric_label": metric_label,
                "bvid": bvid,
                "aid": str(item.get("aid") or ""),
                "created": item.get("created"),
            }
        )
    return {
        "platform": platform,
        "creator_id": creator_id,
        "creator_name": creator_name,
        "total_videos": total_videos or len(catalog),
        "total_scanned": len(catalog),
        "scan_complete": scan_complete,
        "scan_all": scan_all,
        "fetch_order": fetch_order,
        "capabilities": capabilities,
        "top_videos": top_videos,
    }


def _parse_weibo_creator_id(creator_url: str) -> str:
    raw = creator_url.strip()
    match = re.search(r"weibo\.com/(?:u/)?(\d+)", raw)
    if match:
        return match.group(1)
    if raw.isdigit():
        return raw
    raise ValueError("无法解析微博用户 ID，请填写主页链接（如 https://weibo.com/u/1234567890）")


def _parse_zhihu_url_token(creator_url: str) -> str:
    raw = creator_url.strip().rstrip("/")
    if "zhihu.com/people/" in raw:
        return raw.split("/people/")[-1].split("?")[0]
    token = raw.split("/")[-1].split("?")[0]
    if not token:
        raise ValueError("无法解析知乎用户标识，请填写主页链接（如 https://www.zhihu.com/people/xxx）")
    return token


def _xhs_note_url(note: Dict) -> str:
    note_id = note.get("note_id") or ""
    xsec_token = note.get("xsec_token") or ""
    xsec_source = note.get("xsec_source") or "pc_user"
    if not note_id:
        return ""
    query = f"xsec_token={quote(xsec_token)}&xsec_source={quote(xsec_source)}" if xsec_token else ""
    base = f"https://www.xiaohongshu.com/explore/{note_id}"
    return f"{base}?{query}" if query else base


async def _with_temp_max_notes(max_videos: int, scan_all: bool, fn: Callable):
    old_max = config.CRAWLER_MAX_NOTES_COUNT
    if scan_all and max_videos <= 0:
        config.CRAWLER_MAX_NOTES_COUNT = 999999
    elif max_videos > 0:
        config.CRAWLER_MAX_NOTES_COUNT = max_videos
    try:
        return await fn()
    finally:
        config.CRAWLER_MAX_NOTES_COUNT = old_max


async def _rank_bili(
    crawler: BilibiliCrawler,
    creator_url: str,
    top_n: int,
    scan_all: bool,
    max_videos: int,
    fetch_order: str,
) -> dict:
    creator_info = parse_bili_creator(creator_url)
    profile = await crawler.bili_client.get_creator_info(int(creator_info.creator_id))
    catalog_raw, total_videos, scan_complete = await crawler.bili_client.fetch_creator_video_catalog(
        creator_info.creator_id,
        scan_all=scan_all,
        max_videos=max_videos,
        fetch_order=fetch_order,
    )
    catalog, scan_complete = _cap_catalog(catalog_raw, scan_all, max_videos)
    for entry in catalog:
        entry["video_id"] = entry.get("bvid") or entry.get("aid") or ""
        entry["id_label"] = entry.get("bvid") or entry.get("video_id") or ""
    return _finalize_rank(
        "bili",
        creator_info.creator_id,
        profile.get("name", ""),
        catalog,
        top_n,
        total_videos=total_videos,
        scan_complete=scan_complete,
        scan_all=scan_all,
        fetch_order=fetch_order,
    )


async def _rank_dy(crawler: DouYinCrawler, creator_url: str, top_n: int, scan_all: bool, max_videos: int) -> dict:
    creator_info = parse_dy_creator(creator_url)
    user_id = creator_info.sec_user_id
    profile = await crawler.dy_client.get_user_info(user_id)
    creator_name = (profile.get("user") or {}).get("nickname") or ""

    async def collect():
        return await crawler.dy_client.get_all_user_aweme_posts(user_id)

    posts = await _with_temp_max_notes(max_videos, scan_all, collect)
    catalog: List[Dict] = []
    for aweme in posts:
        stats = aweme.get("statistics") or {}
        aweme_id = str(aweme.get("aweme_id") or "")
        catalog.append(
            {
                "video_id": aweme_id,
                "title": (aweme.get("desc") or "")[:200],
                "comment_count": safe_int(stats.get("comment_count")),
                "play_count": safe_int(stats.get("play_count")),
                "url": f"https://www.douyin.com/video/{aweme_id}" if aweme_id else "",
                "id_label": aweme_id,
            }
        )
    catalog, scan_complete = _cap_catalog(catalog, scan_all, max_videos)
    return _finalize_rank("dy", user_id, creator_name, catalog, top_n, scan_complete=scan_complete, scan_all=scan_all)


async def _rank_xhs(crawler: XiaoHongShuCrawler, creator_url: str, top_n: int, scan_all: bool, max_videos: int) -> dict:
    creator_info = parse_xhs_creator(creator_url)
    profile = await crawler.xhs_client.get_creator_info(
        user_id=creator_info.user_id,
        xsec_token=creator_info.xsec_token,
        xsec_source=creator_info.xsec_source,
    )
    creator_name = (profile or {}).get("basicInfo", {}).get("nickname") or (profile or {}).get("nickname") or ""

    async def collect():
        return await crawler.xhs_client.get_all_notes_by_creator(
            user_id=creator_info.user_id,
            xsec_token=creator_info.xsec_token,
            xsec_source=creator_info.xsec_source,
        )

    notes = await _with_temp_max_notes(max_videos, scan_all, collect)
    catalog: List[Dict] = []
    for note in notes:
        interact = note.get("interact_info") or {}
        note_id = str(note.get("note_id") or "")
        url = _xhs_note_url(note)
        catalog.append(
            {
                "video_id": url or note_id,
                "title": (note.get("display_title") or note.get("title") or "")[:200],
                "comment_count": safe_int(interact.get("comment_count")),
                "play_count": safe_int(interact.get("liked_count")),
                "url": url,
                "id_label": note_id,
            }
        )
    catalog, scan_complete = _cap_catalog(catalog, scan_all, max_videos)
    return _finalize_rank("xhs", creator_info.user_id, creator_name, catalog, top_n, scan_complete=scan_complete, scan_all=scan_all)


async def _rank_ks(crawler: KuaishouCrawler, creator_url: str, top_n: int, scan_all: bool, max_videos: int) -> dict:
    creator_info = parse_ks_creator(creator_url)
    user_id = creator_info.user_id
    profile = await crawler.ks_client.get_creator_info(user_id) or {}
    creator_name = profile.get("user_name") or profile.get("userName") or ""

    async def collect():
        return await crawler.ks_client.get_all_videos_by_creator(user_id)

    videos = await _with_temp_max_notes(max_videos, scan_all, collect)
    catalog: List[Dict] = []
    for feed in videos:
        photo = feed.get("photo") or {}
        video_id = str(photo.get("id") or "")
        catalog.append(
            {
                "video_id": video_id,
                "title": (photo.get("caption") or "")[:200],
                "comment_count": safe_int(photo.get("commentCount")),
                "play_count": safe_int(photo.get("viewCount")),
                "url": f"https://www.kuaishou.com/short-video/{video_id}" if video_id else "",
                "id_label": video_id,
            }
        )
    catalog, scan_complete = _cap_catalog(catalog, scan_all, max_videos)
    return _finalize_rank("ks", user_id, creator_name, catalog, top_n, scan_complete=scan_complete, scan_all=scan_all)


async def _rank_wb(crawler: WeiboCrawler, creator_url: str, top_n: int, scan_all: bool, max_videos: int) -> dict:
    user_id = _parse_weibo_creator_id(creator_url)
    info_res = await crawler.wb_client.get_creator_info_by_id(creator_id=user_id)
    creator_name = (info_res.get("userInfo") or {}).get("screen_name") or ""
    container_id = f"107603{user_id}"

    async def collect():
        return await crawler.wb_client.get_all_notes_by_creator_id(
            creator_id=user_id,
            container_id=container_id,
            crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
        )

    cards = await _with_temp_max_notes(max_videos, scan_all, collect)
    catalog: List[Dict] = []
    for card in cards:
        mblog = card.get("mblog") or {}
        if not mblog:
            continue
        mid = str(mblog.get("id") or "")
        catalog.append(
            {
                "video_id": mid,
                "title": (mblog.get("text") or "")[:200],
                "comment_count": safe_int(mblog.get("comments_count")),
                "play_count": safe_int(mblog.get("reposts_count")),
                "url": f"https://weibo.com/{user_id}/{mid}" if mid else "",
                "id_label": mid,
            }
        )
    catalog, scan_complete = _cap_catalog(catalog, scan_all, max_videos)
    return _finalize_rank("wb", user_id, creator_name, catalog, top_n, scan_complete=scan_complete, scan_all=scan_all)


async def _rank_zhihu(crawler: ZhihuCrawler, creator_url: str, top_n: int, scan_all: bool, max_videos: int) -> dict:
    url_token = _parse_zhihu_url_token(creator_url)
    creator: Optional[ZhihuCreator] = await crawler.zhihu_client.get_creator_info(url_token)
    if not creator:
        raise ValueError(f"未找到知乎用户：{url_token}")
    creator_name = creator.user_nickname or url_token

    async def collect_all():
        answers = await crawler.zhihu_client.get_all_anwser_by_creator(
            creator, crawl_interval=config.CRAWLER_MAX_SLEEP_SEC
        )
        articles = await crawler.zhihu_client.get_all_articles_by_creator(
            creator, crawl_interval=config.CRAWLER_MAX_SLEEP_SEC
        )
        videos = await crawler.zhihu_client.get_all_videos_by_creator(
            creator, crawl_interval=config.CRAWLER_MAX_SLEEP_SEC
        )
        return answers + articles + videos

    contents = await _with_temp_max_notes(max_videos, scan_all, collect_all)
    catalog: List[Dict] = []
    for content in contents:
        catalog.append(
            {
                "video_id": content.content_url or content.content_id,
                "title": (content.title or content.desc or content.content_text or "")[:200],
                "comment_count": safe_int(content.comment_count),
                "play_count": safe_int(content.voteup_count),
                "url": content.content_url or "",
                "id_label": content.content_id,
            }
        )
    catalog, scan_complete = _cap_catalog(catalog, scan_all, max_videos)
    return _finalize_rank("zhihu", url_token, creator_name, catalog, top_n, scan_complete=scan_complete, scan_all=scan_all)


async def _rank_tieba(crawler: TieBaCrawler, creator_url: str, top_n: int, scan_all: bool, max_videos: int) -> dict:
    creator = await crawler.tieba_client.get_creator_info_by_url(creator_url)
    creator_name = creator.user_nickname or creator.user_link or creator_url
    max_note_count = 0 if scan_all else (max_videos or 500)
    if scan_all and max_videos > 0:
        max_note_count = max_videos

    notes = await crawler.tieba_client.get_all_notes_by_creator_url(
        creator_url=creator_url,
        crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
        max_note_count=max_note_count,
    )
    catalog: List[Dict] = []
    for note in notes:
        catalog.append(
            {
                "video_id": note.note_url or note.note_id,
                "title": (note.title or "")[:200],
                "comment_count": safe_int(note.total_replay_num),
                "play_count": 0,
                "url": note.note_url or "",
                "id_label": note.note_id,
            }
        )
    scan_complete = max_note_count <= 0 or len(catalog) < max_note_count
    catalog, scan_complete = _cap_catalog(catalog, scan_all, max_videos)
    portrait = crawler.tieba_client._extract_creator_portrait(creator_url)
    return _finalize_rank(
        "tieba",
        portrait or creator_name,
        creator_name,
        catalog,
        top_n,
        scan_complete=scan_complete,
        scan_all=scan_all,
    )


HANDLERS = {
    "bili": _rank_bili,
    "dy": _rank_dy,
    "xhs": _rank_xhs,
    "ks": _rank_ks,
    "wb": _rank_wb,
    "zhihu": _rank_zhihu,
    "tieba": _rank_tieba,
}


async def rank_creator_videos_by_comments(
    platform: str,
    creator_url: str,
    top_n: int = 10,
    scan_all: bool = True,
    max_videos: int = 0,
    fetch_order: str = "default",
) -> dict:
    platform = (platform or "").strip().lower()
    handler = HANDLERS.get(platform)
    if not handler:
        supported = "、".join(sorted(HANDLERS))
        raise ValueError(f"平台「{platform}」暂不支持创作者评论排行，当前支持：{supported}")

    crawler_cls = CRAWLER_MAP[platform]
    async with _rank_lock:
        config.PLATFORM = platform
        config.LOGIN_TYPE = config.LOGIN_TYPE or "qrcode"
        crawler = crawler_cls()
        async with async_playwright() as playwright:
            await crawler.setup_session(playwright)
            try:
                utils.logger.info(
                    f"[CreatorRank] platform={platform}, url={creator_url}, top_n={top_n}"
                )
                if platform == "bili":
                    return await handler(
                        crawler, creator_url, top_n, scan_all, max_videos, fetch_order
                    )
                return await handler(crawler, creator_url, top_n, scan_all, max_videos)
            finally:
                await crawler.close()
