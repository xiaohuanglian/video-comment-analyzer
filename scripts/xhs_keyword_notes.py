# -*- coding: utf-8 -*-
"""小红书「只要笔记、不要评论」的关键词取数。

为什么单独写这个脚本（而不是 `main.py --type search`）：
`main.py` 的搜索流程对**每篇笔记**再发一次 feed 详情请求、并默认抓评论，
一篇笔记一条请求，凑 100 篇就是 100+ 次详情请求。这里只需要「关键词下有哪些笔记」，
搜索接口的返回里已经带了标题、作者、点赞数、note_id 与 xsec_token，
所以每词只发 1 次搜索请求（page_size=20），完全不打开笔记、不碰评论接口。

用法：
  uv run python scripts/xhs_keyword_notes.py \
      --keyword 刷手机无聊 --keyword 信息过载 --total 100 --per-keyword 8

前提：本机小红书登录态（browser_data/cdp_xhs_user_data_dir）。
脚本默认自己拉起带调试端口的浏览器（复用该 profile），不依赖事先手动开浏览器。
输出：data/xhs_search/<时间戳>/notes.csv + notes.json + manifest.json
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 先于 config 导入设置：默认 CDP_CONNECT_EXISTING=True 会去找已开的浏览器，
# 这里要让 CDPBrowserManager 自己用持久化 profile 启动一个。
os.environ.setdefault("CDP_CONNECT_EXISTING", "0")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

# CDPBrowserManager 用 config.PLATFORM 挑持久化 profile（browser_data/cdp_<p>_user_data_dir）。
# 不设就是默认的 "dy"，会拿抖音的 profile 去连小红书——登录态当然没有，pong 直接 False。
config.PLATFORM = "xhs"
config.CRAWLER_TYPE = "search"

from tenacity import RetryError  # noqa: E402

from media_platform.xhs.client import XiaoHongShuClient  # noqa: E402
from media_platform.xhs.exception import CaptchaError, PlatformAccessError  # noqa: E402
from media_platform.xhs.fingerprint import read_browser_fingerprint  # noqa: E402
from media_platform.xhs.help import get_search_id  # noqa: E402
from tools import utils  # noqa: E402
from tools.cdp_browser import CDPBrowserManager  # noqa: E402
from tools.crawl_pacing import (  # noqa: E402
    ERROR_HINTS,
    PLATFORM_BLOCKED,
    classify_failure,
    compute_crawl_interval,
    ensure_platform_available,
    format_duration,
    record_platform_failure,
)
from tools.xhs_safety import (  # noqa: E402
    SearchBudgetExceeded,
    ensure_batch_allowed,
    ensure_not_quiet_hours,
    plan_keywords,
    search_budget,
)

_INDEX_URL = "https://www.rednote.com" if config.XHS_INTERNATIONAL else "https://www.xiaohongshu.com"
_PAGE_SIZE = 20  # 小红书搜索接口固定上限

_COLUMNS = [
    "keyword",
    "note_id",
    "title",
    "author",
    "author_id",
    "note_type",
    "liked_count",
    "collected_count",
    "comment_count",
    "xsec_token",
    "url",
    "cover_url",
]


def _card_of(item: Dict[str, Any]) -> Dict[str, Any]:
    return item.get("note_card") or {}


_QUERY_CARD_TYPES = {"rec_query", "hot_query"}  # 搜索页的"推荐词/热搜词"卡片，不是笔记


def _note_row(keyword: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从搜索结果条目里取「一条笔记」需要的字段；取不到 id 的直接丢。

    两类要滤掉：
    - ``model_type`` 是 rec_query / hot_query 的条目是搜索联想词卡片（有 id 有标题，
      长得像笔记），留着会让"100 条笔记"里混进十几个词条；
    - 没有 ``display_title`` 的图集笔记，标题其实在 ``desc`` 第一行，直接回落到 desc。
    """
    if str(item.get("model_type") or "") in _QUERY_CARD_TYPES:
        return None
    note_id = str(item.get("id") or "").strip()
    if not note_id:
        return None
    card = _card_of(item)
    if not card:
        return None
    token = str(item.get("xsec_token") or "")
    user = card.get("user") or {}
    interact = card.get("interact_info") or {}
    cover = card.get("cover") or {}
    desc = str(card.get("desc") or "").strip()
    title = str(card.get("display_title") or card.get("title") or "").strip()
    if not title:
        title = desc.splitlines()[0].strip() if desc else ""
    note_type = str(card.get("type") or "")
    return {
        "keyword": keyword,
        "note_id": note_id,
        "title": title[:120],
        "author": str(user.get("nickname") or user.get("nick_name") or "").strip(),
        "author_id": str(user.get("user_id") or ""),
        "note_type": note_type,
        "liked_count": str(interact.get("liked_count") or ""),
        "collected_count": str(interact.get("collected_count") or ""),
        "comment_count": str(interact.get("comment_count") or ""),
        "xsec_token": token,
        "url": (
            f"{_INDEX_URL}/explore/{note_id}?xsec_token={token}&xsec_source=pc_search"
            if token
            else f"{_INDEX_URL}/explore/{note_id}"
        ),
        "cover_url": str(cover.get("url_default") or cover.get("url") or ""),
    }


async def _build_client(page: Any) -> XiaoHongShuClient:
    cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
        page.context, urls=[_INDEX_URL]
    )
    # UA / sec-ch-ua 从活着的浏览器读，别写常量：2026-11-11 事故复盘时发现
    # 同一个会话里 UA 说 Chrome/137、sec-ch-ua 说 v=136、浏览器本身是别的版本，
    # 这种自相矛盾比"间隔短"更容易被规则直接命中。
    fingerprint = await read_browser_fingerprint(page, label="XhsFingerprint")
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "no-cache",
        "content-type": "application/json;charset=UTF-8",
        "origin": _INDEX_URL,
        "pragma": "no-cache",
        "referer": f"{_INDEX_URL}/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "Cookie": cookie_str,
    }
    headers.update(fingerprint.headers())
    return XiaoHongShuClient(
        headers=headers,
        playwright_page=page,
        cookie_dict=cookie_dict,
    )


def _root_cause(exc: BaseException) -> BaseException:
    """剥掉 tenacity 的 RetryError 包装，拿到真正的异常。

    客户端方法带 ``@retry``，失败时抛的是 ``RetryError``，它的 message 是
    ``RetryError[<Future ...>]``——直接拿去报错既读不出原因，``classify_failure``
    也认不出错误码，只能给出 code=None。
    """
    seen: set[int] = set()
    cur: BaseException = exc
    while True:
        nxt = cur.__cause__ or cur.__context__
        if isinstance(cur, RetryError):
            try:
                nxt = cur.last_attempt.exception() or nxt
            except Exception:  # noqa: BLE001 — 取不到就退回 cause
                pass
        if nxt is None or id(nxt) in seen or nxt is cur:
            return cur
        seen.add(id(cur))
        cur = nxt


def _failure_row(exc: BaseException, **extra: Any) -> Dict[str, Any]:
    root = _root_cause(exc)
    failure = classify_failure(root, platform="xhs")
    if not failure.message:
        failure.message = f"{type(root).__name__}: {root}"[:300]
    return {**extra, **failure.to_dict()}


async def collect(
    keywords: List[str],
    *,
    per_keyword: int,
    total: int,
    out_dir: Path,
) -> Dict[str, Any]:
    ensure_platform_available("xhs")  # 平台冷却中直接抛 CrawlBlocked
    # 单批上限是硬约束，但词表可能比上限长。不报错、也不永远只搜前 N 个，
    # 而是按日期轮转取一批（`plan_keywords`），剩下的记进 manifest 下次再搜。
    keywords, deferred = plan_keywords(keywords)
    if deferred:
        utils.logger.info(
            f"[xhs_notes] 本次只搜 {len(keywords)} 个词（单批上限），其余 {len(deferred)} 个未执行：{deferred}"
        )
    # 批前拒绝：今日额度不够就在发第一个请求之前拒绝，而不是跑到一半才砍。
    # （2026-11-11 就是打到第 10 个词才发现被拦，前面 9 次请求等于白送。）
    ensure_not_quiet_hours()
    ensure_batch_allowed(len(keywords))

    from playwright.async_api import async_playwright

    manager = CDPBrowserManager()
    pool: Dict[str, List[Dict[str, Any]]] = {}
    failures: List[Dict[str, Any]] = []
    aborted = False
    pong = False

    async with async_playwright() as playwright:
        context = await manager.launch_and_connect(playwright, None, None, headless=config.CDP_HEADLESS)
        page = await context.new_page()
        try:
            await page.goto(_INDEX_URL, wait_until="domcontentloaded", timeout=30000)
            client = await _build_client(page)
            try:
                pong = bool(await client.pong())
            except Exception as exc:  # noqa: BLE001 — 登录校验失败不阻塞搜索，最后统一报
                failures.append(_failure_row(exc, stage="pong"))

            if not pong:
                # 登录态不可用时继续搜只会白白多打 12 次请求，还会给自己攒风控分。
                failures.append(
                    {
                        "stage": "login",
                        "code": "NEED_LOGIN",
                        "message": "小红书登录态失效（pong 未通过），未发起任何搜索请求",
                        "hint": (
                            f"用 --user-data-dir=browser_data/cdp_xhs_user_data_dir 打开浏览器，"
                            f"登录小红书后重跑（{_INDEX_URL}）"
                        ),
                    }
                )

            for i, keyword in enumerate(keywords):
                if not pong:
                    pool[keyword] = []
                    continue
                if i:
                    base, jitter = compute_crawl_interval("xhs", "search")
                    await asyncio.sleep(base + random.uniform(0, jitter))
                utils.logger.info(f"[xhs_notes] 搜索「{keyword}」")
                # 记账要在请求**之前**：请求可能超时/被拦，但次数已经消耗了
                search_budget().consume(1)
                try:
                    res = await client.get_note_by_keyword(
                        keyword=keyword,
                        search_id=get_search_id(),
                        page=1,
                        page_size=_PAGE_SIZE,
                    )
                    items = (res or {}).get("items") or []
                    rows = [r for r in (_note_row(keyword, it) for it in items) if r]
                    pool[keyword] = rows
                    utils.logger.info(f"[xhs_notes] 「{keyword}」返回 {len(rows)} 条")
                except Exception as exc:  # noqa: BLE001 — 单个关键词失败不该中断整批
                    failure = _failure_row(exc, stage="search", keyword=keyword)
                    failures.append(failure)
                    pool[keyword] = []
                    utils.logger.warning(
                        f"[xhs_notes] 「{keyword}」失败：{failure['error']['message']}"
                    )
                    # 撞到平台风控就停手：已经证明平台在拦我们了，继续打剩下的
                    # 关键词只会加重标记（2026-11-11 那批就是这么把账号打异常的）。
                    if failure["error"]["code"] == PLATFORM_BLOCKED or isinstance(
                        _root_cause(exc), (CaptchaError, PlatformAccessError)
                    ):
                        record_platform_failure("xhs", _root_cause(exc))
                        rest = keywords[i + 1 :]
                        failures.append(
                            {
                                "stage": "aborted",
                                "code": PLATFORM_BLOCKED,
                                "message": (
                                    f"「{keyword}」撞到平台风控验证码，已中止本批；"
                                    f"剩余 {len(rest)} 个关键词未执行"
                                ),
                                "hint": ERROR_HINTS[PLATFORM_BLOCKED],
                                "skipped_keywords": rest,
                            }
                        )
                        for skipped in rest:
                            pool[skipped] = []
                        aborted = True
                        utils.logger.error(
                            f"[xhs_notes] 平台风控拦截，中止本批（剩 {len(rest)} 个关键词未执行）"
                        )
                        break
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
            await manager.cleanup()

    # 分配：先每词取 per_keyword，再按关键词顺序补齐到 total；跨词按 note_id 去重
    picked: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def take(keyword: str, limit: int) -> int:
        taken = 0
        for row in pool.get(keyword, []):
            if taken >= limit or len(picked) >= total:
                break
            if row["note_id"] in seen:
                continue
            seen.add(row["note_id"])
            picked.append(row)
            taken += 1
        return taken

    for keyword in keywords:
        take(keyword, per_keyword)
    if len(picked) < total:
        for keyword in keywords:
            if len(picked) >= total:
                break
            take(keyword, total - len(picked))

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "notes.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(picked)
    (out_dir / "notes.json").write_text(
        json.dumps(picked, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    by_keyword = {k: len(v) for k, v in pool.items()}
    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "keywords": keywords,
        "per_keyword": per_keyword,
        "target_total": total,
        "saved_total": len(picked),
        "fetched_per_keyword": by_keyword,
        "logged_in": pong,
        "aborted": aborted,
        "deferred_keywords": deferred,
        "failures": failures,
        "csv": str(csv_path),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return manifest


async def _run_collect(
    keywords: List[str],
    *,
    per_keyword: int,
    total: int,
    out_dir: Path,
) -> Dict[str, Any]:
    """包一层，把「额度/单批超限」翻译成人话，而不是让异常直接冒到栈上。"""
    try:
        return await collect(
            keywords,
            per_keyword=per_keyword,
            total=total,
            out_dir=out_dir,
        )
    except SearchBudgetExceeded as exc:
        print(f"\n[拒绝开工] {exc}")
        if exc.retry_after_seconds:
            print(f"（约 {format_duration(exc.retry_after_seconds)} 后恢复额度）")
        sys.exit(3)


def main() -> None:
    parser = argparse.ArgumentParser(description="小红书关键词取笔记（不抓评论、不打开笔记）")
    parser.add_argument("--keyword", action="append", default=[], help="搜索关键词（可多次）")
    parser.add_argument("--per-keyword", type=int, default=8, help="每个关键词至少取几条（默认 8）")
    parser.add_argument("--total", type=int, default=100, help="总条数上限（默认 100）")
    parser.add_argument("--out", type=str, default="", help="输出目录（默认 data/xhs_search/<时间戳>）")
    args = parser.parse_args()

    if not args.keyword:
        parser.error("至少提供一个 --keyword")
    out_dir = Path(args.out) if args.out else Path("data") / "xhs_search" / time.strftime("%Y%m%d_%H%M%S")

    manifest = asyncio.run(
        _run_collect(
            args.keyword,
            per_keyword=max(1, args.per_keyword),
            total=max(1, args.total),
            out_dir=out_dir,
        )
    )

    print("\n各关键词返回条数：")
    for keyword, count in manifest["fetched_per_keyword"].items():
        print(f"  {keyword}: {count}")
    print(f"\n已保存 {manifest['saved_total']} 条（目标 {manifest['target_total']}）→ {manifest['csv']}")
    print(f"登录态：{'已登录' if manifest['logged_in'] else '未确认（pong 未通过）'}")
    if manifest["failures"]:
        print("\n失败项：")
        for item in manifest["failures"]:
            error = item.get("error") or {}
            where = item.get("keyword") or item.get("stage")
            print(f"  [{error.get('code')}] {where}: {error.get('message')}")
            if error.get("hint"):
                print(f"       → {error['hint']}")
        sys.exit(3)
    if manifest.get("aborted"):
        print("\n本批因平台风控中止，剩余关键词未执行；冷却已写入 cache/crawl_guard/cooldowns.json。")
    if manifest["saved_total"] == 0:
        print("\n一条都没拿到：多半是登录态失效，请先在该 profile 里登录小红书后重跑。")
        sys.exit(3)


if __name__ == "__main__":
    main()
