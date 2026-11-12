# -*- coding: utf-8 -*-
"""B 站「用户在哪里」选片：搜三类词 → 探针抓少量评论 → 按需求语言判定 → 出全量名单。

## 为什么不是「按标题相关性选片」

2026-11-12 踩过的坑：按「标题含 新闻/资讯/AI/播报」选片，选出的是**话题消费型**视频
（AI 主播上岗、黄仁勋、沈逸时评）。那些评论区在吵立场，坐着的是围观者，不是
「想在通勤时用听代替刷手机」的人；而日更竞品号（新闻速递/AI日报）评论区常常只有
1–20 条，是空的。

所以判据换成：**这条视频的评论里，有没有人在说需求语言**。
先每片探 50 条热门评论，命中够数才花钱全量。

## 三类关键词（对应三类「可能坐着我们用户」的视频）

1. `audio` 音频替代品：播客推荐 / 播客App / 听书推荐 / 音频软件
2. `brief` 短资讯产品：新闻早报 / 一分钟新闻 / AI播报 / 新闻简报
3. `voice` 语音问答：AI语音助手 / 语音对话AI / AI问答 / 智能音箱
4. `habit` 信息获取方式：高效获取信息 / 信息差 / 行业资讯 / 每天看新闻

**不含泛痛点词**（戒手机/注意力/信息过载）——那类大盘的评论者是在陈述自己的问题，
不是在找一个「每天几分钟听完资讯」的入口；用它选片会把样本带偏到"注意力困难人群"。

## 输出（`data/bili_audience/<时间戳>/`）

- `audience.csv`：全部候选 + 探针结果 + 判定（pass/reject）
- `probe.json`：每个视频的命中条数、占比、命中的原话样例
- 通过判定的视频 id 直接拿去跑 `main.py --type detail ... --get_comment true` 做全量

用法：
  uv run python scripts/bili_audience_pick.py            # 用默认三族词
  uv run python scripts/bili_audience_pick.py --extra-keyword 早间新闻
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

os.environ.setdefault("CDP_CONNECT_EXISTING", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

config.PLATFORM = "bili"
config.CRAWLER_TYPE = "search"

from tenacity import RetryError  # noqa: E402

from media_platform.bilibili.client import BilibiliClient  # noqa: E402
from media_platform.bilibili.field import CommentOrderType, SearchOrderType  # noqa: E402
from tools import utils  # noqa: E402
from tools.cdp_browser import CDPBrowserManager  # noqa: E402
from tools.crawl_pacing import (  # noqa: E402
    classify_failure,
    compute_crawl_interval,
    ensure_platform_available,
)

_INDEX_URL = "https://www.bilibili.com"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

#: 关键词族与需求语言按 preset 切换：
#: - `tool`   ：资讯/新闻类**工具**的测评与吐槽。评论区才会出现"哪个好用/能推送吗/会员多少钱/
#:              我卸了"，也就是真的在产品层面比较的人（本轮采用）
#: - `product`：音频/短资讯/AI 助手这类产品内容（上一轮跑过，评论区多聊内容本身，命中率低）
PRESETS: Dict[str, Dict[str, Any]] = {
    "tool": {
        "keywords": {
            "newsapp": ["新闻App", "资讯App", "新闻聚合", "早报App"],
            "tool": ["RSS订阅", "资讯订阅", "稍后读", "信息管理工具"],
            "voiceapp": ["语音助手App", "AI简报", "AI播报App", "听新闻App"],
        },
        "need": {
            "产品评价": (
                r"(好用|难用|卸载|广告|会员|推送|多端|同步|锁屏|离线|占用|卡顿|界面|体验|"
                r"在哪下|怎么下|支持|功能|免费|收费|付费|替代|换掉|弃用|不更新)"
            ),
            "场景": r"(通勤|上下班|路上|开车|地铁|公交|骑车|做家务|洗碗|做饭|睡前|洗漱|散步|走路)",
            "形式偏好": (
                r"(几分钟|一分钟|三分钟|5分钟|五分钟|十分钟|太长|太吵|倍速|语速|短一点|短点|"
                r"不要看|不用看|只听|光听|连续播放|自动播放|自动更新|背景音)"
            ),
        },
    },
    "product": {
        "keywords": {
            "audio": ["播客推荐", "播客App", "听书推荐", "音频软件"],
            "brief": ["新闻早报", "一分钟新闻", "AI播报", "新闻简报"],
            "voice": ["AI语音助手", "语音对话AI", "AI问答", "智能音箱"],
            "habit": ["高效获取信息", "信息差", "行业资讯", "每天看新闻"],
        },
        "need": {
            "求产品": (
                r"((求|想|有没有|推荐|哪个|什么|在哪|用啥|用什么).{0,8}"
                r"(app|软件|播客|栏目|频道|节目|工具|小程序|平台|网站))"
            ),
            "场景": r"(通勤|上下班|路上|开车|地铁|公交|骑车|做家务|洗碗|做饭|睡前|洗漱|散步|走路)",
            "形式偏好": (
                r"(几分钟|一分钟|三分钟|5分钟|五分钟|十分钟|太长|太吵|倍速|语速|"
                r"短一点|短点|不要看|不用看|只听|光听|连续播放|自动播放|自动更新|背景音)"
            ),
            "付费获取": r"(多少钱|免费|会员|在哪下|怎么下|求链接|求个链接)",
        },
    },
}

_NEED_GROUPS: Dict[str, str] = {}
_NEED_RE = re.compile(r"$^")  # 空正则，_use_preset 之后才有内容


def _use_preset(name: str) -> Dict[str, List[str]]:
    """切换 preset：返回关键词族，并把需求语言写进模块级供 _hit_groups 使用。"""
    global _NEED_GROUPS, _NEED_RE
    preset = PRESETS[name]
    _NEED_GROUPS = dict(preset["need"])
    _NEED_RE = re.compile("|".join(f"(?P<g{i}>{p})" for i, p in enumerate(_NEED_GROUPS.values())))
    return {k: list(v) for k, v in preset["keywords"].items()}


#: 明显跑题的标题（音乐/游戏/鬼畜），探针前就丢掉，省请求
_DROP_TITLE = ("minecraft", "我的世界", "歌单", "bgm", "鬼畜", "游戏实况", "直播回放")


def _clean_title(raw: Any) -> str:
    return str(raw or "").replace('<em class="keyword">', "").replace("</em>", "").strip()


def _hit_groups(text: str) -> List[str]:
    names = list(_NEED_GROUPS.keys())
    if not names:
        return []
    out = set()
    # 评论里 App/APP/app 混着写，正则用小写，这里统一降成小写再匹配
    for m in _NEED_RE.finditer((text or "").lower()):
        for i, name in enumerate(names):
            if m.group(f"g{i}"):
                out.add(name)
    return sorted(out)


def _root_error(exc: BaseException) -> BaseException:
    cur: BaseException = exc
    seen: set[int] = set()
    while True:
        nxt = cur.__cause__ or cur.__context__
        if isinstance(cur, RetryError):
            try:
                nxt = cur.last_attempt.exception() or nxt
            except Exception:  # noqa: BLE001
                pass
        if nxt is None or nxt is cur or id(nxt) in seen:
            return cur
        seen.add(id(cur))
        cur = nxt


async def _build_client(page: Any) -> BilibiliClient:
    cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
        page.context, urls=[_INDEX_URL]
    )
    return BilibiliClient(
        headers={
            "User-Agent": _USER_AGENT,
            "Cookie": cookie_str,
            "Origin": _INDEX_URL,
            "Referer": _INDEX_URL,
            "Content-Type": "application/json;charset=UTF-8",
        },
        playwright_page=page,
        cookie_dict=cookie_dict,
    )


async def run(
    keywords: Dict[str, List[str]],
    *,
    per_family_hot: int,
    per_family_recent: int,
    recent_days: int,
    recent_min_play: int,
    recent_min_comments: int,
    probe_size: int,
    need_threshold: int,
    out_dir: Path,
) -> Dict[str, Any]:
    ensure_platform_available("bili")

    from playwright.async_api import async_playwright

    manager = CDPBrowserManager()
    candidates: Dict[str, Dict[str, Any]] = {}
    failures: List[Dict[str, Any]] = []
    probes: List[Dict[str, Any]] = []

    async with async_playwright() as playwright:
        context = await manager.launch_and_connect(playwright, None, None, headless=config.CDP_HEADLESS)
        page = await context.new_page()
        try:
            await page.goto(_INDEX_URL, wait_until="domcontentloaded", timeout=30000)
            client = await _build_client(page)

            # ---- 阶段 1：三类词各搜一遍（综合 + 最新），收候选 ----
            first = True
            for family, words in keywords.items():
                for keyword in words:
                    for order in (SearchOrderType.DEFAULT, SearchOrderType.LAST_PUBLISH):
                        if not first:
                            base, jitter = compute_crawl_interval("bili")
                            await asyncio.sleep(base + jitter)
                        first = False
                        try:
                            res = await client.search_video_by_keyword(
                                keyword=keyword, page=1, page_size=20, order=order
                            )
                            for item in res.get("result") or []:
                                title = _clean_title(item.get("title"))
                                bvid = str(item.get("bvid") or "").strip()
                                if not bvid or any(d in title.lower() for d in _DROP_TITLE):
                                    continue
                                candidates.setdefault(
                                    bvid,
                                    {
                                        "family": family,
                                        "keyword": keyword,
                                        "bvid": bvid,
                                        "aid": int(item.get("aid") or 0),
                                        "title": title,
                                        "author": str(item.get("author") or ""),
                                        "play": int(item.get("play") or 0),
                                        "like": int(item.get("like") or 0),
                                        "comments": int(item.get("review") or 0),
                                        "pubdate": int(item.get("pubdate") or 0),
                                        "url": f"{_INDEX_URL}/video/{bvid}",
                                    },
                                )
                            utils.logger.info(
                                f"[audience] {family}/{keyword}/{order.name}: 候选累计 {len(candidates)}"
                            )
                        except Exception as exc:  # noqa: BLE001
                            root = _root_error(exc)
                            failure = classify_failure(root, platform="bili")
                            failures.append(
                                {"stage": "search", "keyword": keyword, **failure.to_dict()}
                            )
                            utils.logger.warning(f"[audience] 搜索 {keyword} 失败：{failure.message or root}")

            rows = list(candidates.values())
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / "candidates.csv", "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["family", "keyword", "bvid", "aid", "title", "author",
                                "play", "like", "comments", "pubdate", "url"],
                )
                writer.writeheader()
                for r in rows:
                    writer.writerow({k: r.get(k, "") for k in writer.fieldnames})

            cutoff = int(time.time()) - recent_days * 86400
            picked_hot: List[Dict[str, Any]] = []
            picked_recent: List[Dict[str, Any]] = []
            taken: set[str] = set()

            # 按族配额取样：不按族配额时，最热的那一族会把名额全占掉
            # （2026-11-12 实测：按总点赞取前 10，4 个通过的全是 pain 族大盘，
            #   scene/alt 一个都没进候选，族群覆盖直接塌掉）。
            for family in keywords:
                fam = [r for r in rows if r["family"] == family]
                hot = sorted([r for r in fam if r["like"] > 0], key=lambda r: r["like"], reverse=True)
                for r in hot[:per_family_hot]:
                    if r["bvid"] not in taken:
                        r["group"] = "hot"
                        picked_hot.append(r)
                        taken.add(r["bvid"])
                recent_pool = [
                    r
                    for r in fam
                    if r["pubdate"] >= cutoff
                    and r["bvid"] not in taken
                    and (r["comments"] >= recent_min_comments or r["play"] >= recent_min_play)
                ]
                recent_pool.sort(key=lambda r: r["pubdate"], reverse=True)
                for r in recent_pool[:per_family_recent]:
                    r["group"] = "recent"
                    picked_recent.append(r)
                    taken.add(r["bvid"])

            targets = picked_hot + picked_recent

            # ---- 阶段 2：探针——每片只抓前 probe_size 条热门评论 ----
            for i, row in enumerate(targets):
                base, jitter = compute_crawl_interval("bili")
                await asyncio.sleep(base + jitter)
                texts: List[str] = []

                # 默认参数绑定 texts：闭包直接引用循环变量会被下一轮覆盖（ruff B023）
                async def _sink(
                    video_id: str,
                    comments: List[Dict[str, Any]],
                    _texts: List[str] = texts,
                ) -> None:
                    for c in comments or []:
                        msg = (c.get("content") or {}).get("message") or ""
                        if msg:
                            _texts.append(msg)

                try:
                    await client.get_video_all_comments(
                        video_id=row["aid"],
                        crawl_interval=compute_crawl_interval("bili")[0],
                        is_fetch_sub_comments=False,
                        callback=_sink,
                        max_count=probe_size,
                        order_mode=CommentOrderType.DEFAULT,
                    )
                    fetched = len(texts)
                except Exception as exc:  # noqa: BLE001
                    root = _root_error(exc)
                    failure = classify_failure(root, platform="bili")
                    failures.append({"stage": "probe", "bvid": row["bvid"], **failure.to_dict()})
                    fetched = len(texts)
                    utils.logger.warning(f"[audience] 探针 {row['bvid']} 失败：{failure.message or root}")

                matched = []
                groups: Dict[str, int] = {}
                for text in texts:
                    hits = _hit_groups(text)
                    if hits:
                        matched.append({"text": text[:120], "groups": hits})
                        for g in hits:
                            groups[g] = groups.get(g, 0) + 1
                ratio = (len(matched) / fetched) if fetched else 0.0
                verdict = "pass" if (len(matched) >= need_threshold or ratio >= 0.10) else "reject"
                probes.append(
                    {
                        "group": row["group"],
                        "family": row["family"],
                        "keyword": row["keyword"],
                        "bvid": row["bvid"],
                        "aid": row["aid"],
                        "title": row["title"],
                        "author": row["author"],
                        "play": row["play"],
                        "like": row["like"],
                        "comments": row["comments"],
                        "pubdate": time.strftime("%Y-%m-%d", time.localtime(row["pubdate"]))
                        if row["pubdate"]
                        else "",
                        "url": row["url"],
                        "probe_fetched": fetched,
                        "need_matched": len(matched),
                        "need_ratio": round(ratio, 3),
                        "groups": groups,
                        "verdict": verdict,
                        "samples": matched[:5],
                    }
                )
                utils.logger.info(
                    f"[audience] 探针 {i + 1}/{len(targets)} {row['bvid']}: "
                    f"{fetched} 条评论，需求语言 {len(matched)} 条 → {verdict}"
                )
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
            await manager.cleanup()

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "audience.csv"
    columns = [
        "verdict",
        "group",
        "family",
        "keyword",
        "bvid",
        "aid",
        "title",
        "author",
        "play",
        "like",
        "comments",
        "pubdate",
        "probe_fetched",
        "need_matched",
        "need_ratio",
        "url",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for p in probes:
            writer.writerow({k: p.get(k, "") for k in columns})

    passed = [p for p in probes if p["verdict"] == "pass"]
    result = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "keywords": keywords,
        "per_family_hot": per_family_hot,
        "per_family_recent": per_family_recent,
        "recent_min_play": recent_min_play,
        "recent_min_comments": recent_min_comments,
        "recent_days": recent_days,
        "probe_size": probe_size,
        "need_threshold": need_threshold,
        "candidate_total": len(candidates),
        "probed_total": len(probes),
        "passed_total": len(passed),
        "passed_bvids": [p["bvid"] for p in passed],
        "estimated_comments": sum(p["comments"] for p in passed),
        "probes": probes,
        "failures": failures,
    }
    (out_dir / "probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="B 站「用户在哪里」选片：探针判定评论区是否坐着我们的用户")
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default="tool",
        help="关键词族组合：tool=资讯工具测评（默认）/ product=音频与短资讯产品",
    )
    parser.add_argument("--extra-keyword", action="append", default=[], help="额外关键词（可多次，归入第一族）")
    parser.add_argument("--per-family-hot", type=int, default=3, help="每族取几个高赞（默认 3）")
    parser.add_argument("--per-family-recent", type=int, default=3, help="每族取几个最近（默认 3）")
    parser.add_argument("--recent-min-play", type=int, default=20000, help="最近组播放门槛（默认 2 万）")
    parser.add_argument("--recent-min-comments", type=int, default=30, help="最近组评论门槛（默认 30）")
    parser.add_argument("--recent-days", type=int, default=30, help="「最近」窗口（默认 30 天）")
    parser.add_argument("--probe-size", type=int, default=50, help="每个视频探多少条评论（默认 50）")
    parser.add_argument("--need-threshold", type=int, default=5, help="命中多少条需求语言算通过（默认 5）")
    parser.add_argument("--out", type=str, default="", help="输出目录（默认 data/bili_audience/<时间戳>）")
    args = parser.parse_args()

    keywords = _use_preset(args.preset)
    if args.extra_keyword:
        first = next(iter(keywords))
        keywords[first] = keywords[first] + list(args.extra_keyword)

    out_dir = Path(args.out) if args.out else Path("data") / "bili_audience" / time.strftime("%Y%m%d_%H%M%S")
    result = asyncio.run(
        run(
            keywords,
            per_family_hot=max(1, args.per_family_hot),
            per_family_recent=max(1, args.per_family_recent),
            recent_days=max(1, args.recent_days),
            recent_min_play=max(0, args.recent_min_play),
            recent_min_comments=max(0, args.recent_min_comments),
            probe_size=max(10, args.probe_size),
            need_threshold=max(1, args.need_threshold),
            out_dir=out_dir,
        )
    )

    print(f"\n候选 {result['candidate_total']} → 探针 {result['probed_total']} → 通过 {result['passed_total']}")
    for p in result["probes"]:
        flag = "PASS" if p["verdict"] == "pass" else "    "
        groups = ",".join(f"{k}{v}" for k, v in (p["groups"] or {}).items()) or "-"
        print(
            f"  [{flag}] {p['group']:<6} {p['family']:<5} 需求语言 {p['need_matched']:>2}/{p['probe_fetched']:<3} "
            f"({p['need_ratio']:.0%}) [{groups}] {p['author'][:8]:<8} | {p['title'][:34]} | {p['bvid']}"
        )
    print(f"\n全量名单已写入：{out_dir / 'probe.json'}")
    print(f"这些视频评论区大盘合计约 {result['estimated_comments']} 条")
    if result["failures"]:
        print("\n失败项：")
        for f in result["failures"]:
            print(f"  [{f['error']['code']}] {f.get('keyword') or f.get('bvid')}: {f['error']['message']}")
        sys.exit(3)


if __name__ == "__main__":
    main()
