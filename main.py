import io
import sys
import time

# Force UTF-8 encoding for stdout/stderr to prevent encoding errors
# when outputting Chinese characters in non-UTF-8 terminals
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import asyncio
from typing import Optional, Type

import cmd_arg
import config
from base.base_crawler import AbstractCrawler
from database import db
from media_platform.bilibili import BilibiliCrawler
from media_platform.douyin import DouYinCrawler
from media_platform.kuaishou import KuaishouCrawler
from media_platform.tieba import TieBaCrawler
from media_platform.weibo import WeiboCrawler
from media_platform.xhs import XiaoHongShuCrawler
from media_platform.zhihu import ZhihuCrawler
from tools.async_file_writer import AsyncFileWriter
from tools.crawl_pacing import (
    BLOCKED_EXIT_CODE,
    CrawlBlocked,
    CrawlPacer,
    clear_stale_cooldown,
    ensure_platform_available,
)
from tools.xhs_safety import SearchBudgetExceeded, ensure_not_quiet_hours
from var import crawler_type_var


class CrawlerFactory:
    CRAWLERS: dict[str, Type[AbstractCrawler]] = {
        "xhs": XiaoHongShuCrawler,
        "dy": DouYinCrawler,
        "ks": KuaishouCrawler,
        "bili": BilibiliCrawler,
        "wb": WeiboCrawler,
        "tieba": TieBaCrawler,
        "zhihu": ZhihuCrawler,
    }

    @staticmethod
    def create_crawler(platform: str) -> AbstractCrawler:
        crawler_class = CrawlerFactory.CRAWLERS.get(platform)
        if not crawler_class:
            supported = ", ".join(sorted(CrawlerFactory.CRAWLERS))
            raise ValueError(f"Invalid media platform: {platform!r}. Supported: {supported}")
        return crawler_class()


crawler: Optional[AbstractCrawler] = None


def _flush_excel_if_needed() -> None:
    if config.SAVE_DATA_OPTION != "excel":
        return

    try:
        from store.excel_store_base import ExcelStoreBase

        ExcelStoreBase.flush_all()
        print("[Main] Excel files saved successfully")
    except Exception as e:
        print(f"[Main] Error flushing Excel data: {e}")


async def _generate_wordcloud_if_needed() -> None:
    if config.SAVE_DATA_OPTION not in ("json", "jsonl") or not config.ENABLE_GET_WORDCLOUD:
        return

    try:
        file_writer = AsyncFileWriter(
            platform=config.PLATFORM,
            crawler_type=crawler_type_var.get(),
        )
        await file_writer.generate_wordcloud_from_comments()
    except Exception as e:
        print(f"[Main] Error generating wordcloud: {e}")


async def main() -> None:
    global crawler

    args = await cmd_arg.parse_cmd()
    if args.init_db:
        await db.init_db(args.init_db)
        print(f"Database {args.init_db} initialized successfully.")
        return

    platform = config.PLATFORM
    try:
        ensure_platform_available(platform)
    except CrawlBlocked as blocked:
        # 平台还在冷却里：直接告诉用户要等多久，不启动浏览器、不发请求
        print(f"[CrawlGuard] {blocked.failure.to_text()}")
        raise SystemExit(BLOCKED_EXIT_CODE) from None

    if platform == "xhs":
        # 夜间静默：真人要睡觉。凌晨三点搜六个不相关话题是最明显的机器人特征。
        # 放在启动浏览器之前拒绝，一个请求都不发。
        try:
            ensure_not_quiet_hours()
        except SearchBudgetExceeded as quiet:
            print(f"[XhsQuiet] {quiet}")
            raise SystemExit(BLOCKED_EXIT_CODE) from None

    crawler = CrawlerFactory.create_crawler(platform=platform)
    started_at = time.time()
    try:
        await crawler.start()
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        raise
    except SearchBudgetExceeded as exc:
        # 额度不够不是"平台出问题"，绝不能写平台冷却（那会让账号多静置几小时，
        # 而真正该做的是明天再来 / 少给几个词）。用退出码 3 与"冷却中"区分开。
        print(f"[XhsBudget] {exc}")
        raise SystemExit(BLOCKED_EXIT_CODE) from None
    except Exception as exc:
        # 分类 + 落盘冷却：下一次采集会先被拦下，而不是重新撞墙
        failure = CrawlPacer(platform=platform).on_failure(exc)
        print(f"[CrawlGuard] {failure.to_text()}")
        raise
    else:
        # 跑通了才考虑解掉**上一次**留下的冷却。本次运行中途写下的冷却必须保留
        # ——那说明撞过墙，只是被平台客户端内部的 break 吞成了正常返回。
        clear_stale_cooldown(platform, started_at)

    _flush_excel_if_needed()

    # Generate wordcloud after crawling is complete
    # Only for JSON save mode
    await _generate_wordcloud_if_needed()


async def async_cleanup() -> None:
    global crawler
    if crawler:
        if getattr(crawler, "cdp_manager", None):
            try:
                await crawler.cdp_manager.cleanup(force=True)
            except Exception as e:
                error_msg = str(e).lower()
                if "closed" not in error_msg and "disconnected" not in error_msg:
                    print(f"[Main] Error cleaning up CDP browser: {e}")

        elif getattr(crawler, "browser_context", None):
            try:
                await crawler.browser_context.close()
            except Exception as e:
                error_msg = str(e).lower()
                if "closed" not in error_msg and "disconnected" not in error_msg:
                    print(f"[Main] Error closing browser context: {e}")

    if config.SAVE_DATA_OPTION in ("db", "sqlite"):
        await db.close()

if __name__ == "__main__":
    from tools.app_runner import run

    def _force_stop() -> None:
        c = crawler
        if not c:
            return
        cdp_manager = getattr(c, "cdp_manager", None)
        launcher = getattr(cdp_manager, "launcher", None)
        if not launcher:
            return
        try:
            launcher.cleanup()
        except Exception:
            pass

    run(main, async_cleanup, cleanup_timeout_seconds=15.0, on_first_interrupt=_force_stop)
