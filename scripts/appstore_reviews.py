# -*- coding: utf-8 -*-
"""App Store 中国区评论采集：拿同类产品的**差评**，直读需求缺口。

## 为什么用这个源

2026-11-12 在 B 站试了三轮（品类词 / 泛痛点词 / 产品需求词），评论区产出的都是
「评价这个视频」和「陈述自己的问题」，找不到「我要一个每天几分钟听完资讯的入口」。
App Store 差评不一样：**差评本身就是需求缺口**——"太吵""太长""广告多""不支持锁屏播放"
直接对应早播的功能卖点，不需要再猜。

接口是 Apple 公开的 RSS（`itunes.apple.com/cn/rss/customerreviews`），
不需要登录、不触发平台风控，每页 50 条、最多 10 页。

用法：
  uv run python scripts/appstore_reviews.py \
      --app 876336838:喜马拉雅 --app 529092160:今日头条 --pages 3 --max-rating 2

输出：`data/appstore_reviews/<时间戳>/reviews.csv`
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

_RSS = "https://itunes.apple.com/cn/rss/customerreviews/page={page}/id={app_id}/sortby={sort}/json"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) appstore-review-collector"}

_COLUMNS = ["app", "app_id", "rating", "title", "content", "author", "updated", "version", "url"]

#: 早播的功能卖点对应的「差评关键词」——用来统计竞品到底在哪掉链子
GAP_KEYWORDS: Dict[str, str] = {
    "太吵/音效": r"(太吵|噪音|声音|音量|BGM|背景音乐|配音|刺耳)",
    "太长/时长": r"(太长|时间太长|一集.*久|拖沓|半小时|一小时)",
    "广告多": r"(广告|推广|开屏|弹窗)",
    "收费/会员": r"(收费|付费|会员|氪金|买断|订阅费|涨价)",
    "推送骚扰": r"(推送|通知|打扰|提醒太频繁)",
    "卡顿/崩溃": r"(卡顿|闪退|崩溃|卡死|打不开|加载慢)",
    "锁屏/后台": r"(锁屏|后台|息屏|不能连续播放|自动暂停)",
    "内容质量": r"(标题党|没营养|低质|刷不到想看|同质化|ai味|机器人)",
    "更新慢": r"(不更新|内容少|更新太慢|资讯旧|过时)",
    "搜索/推荐": r"(搜不到|推荐不准|算法|想看的没有)",
}


def _get_json(url: str, timeout: float = 20) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — 固定 apple 域名
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _entries(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    entry = (payload.get("feed") or {}).get("entry")
    if isinstance(entry, dict):
        return [entry]
    return entry or []


def _text(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("label") or "")
    return str(node or "")


def fetch_app(app_id: str, name: str, *, pages: int, sort: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for page in range(1, max(1, pages) + 1):
        url = _RSS.format(page=page, app_id=app_id, sort=sort)
        try:
            payload = _get_json(url)
        except (urllib.error.URLError, TimeoutError, ValueError):
            break
        entries = _entries(payload)
        if not entries:
            break
        for e in entries:
            rating = _text((e.get("im:rating") or {})).strip()
            if not rating:
                continue  # 首条通常是 app 元信息，不是评论
            rows.append(
                {
                    "app": name,
                    "app_id": app_id,
                    "rating": int(rating) if rating.isdigit() else 0,
                    "title": _text(e.get("title")).strip(),
                    "content": _text(e.get("content")).strip().replace("\n", " "),
                    "author": _text((e.get("author") or {}).get("name")).strip(),
                    "updated": _text(e.get("updated")).strip()[:10],
                    "version": _text((e.get("im:version") or {})).strip(),
                    "url": _text((e.get("link") or {}).get("attributes", {}).get("href"))
                    if isinstance(e.get("link"), dict)
                    else "",
                }
            )
        time.sleep(1)  # 对 Apple 也留点体面，虽然它不限流
    return rows


def gap_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {k: 0 for k in GAP_KEYWORDS}
    for row in rows:
        text = f"{row['title']} {row['content']}"
        for key, pattern in GAP_KEYWORDS.items():
            if re.search(pattern, text, re.IGNORECASE):
                counts[key] += 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="App Store 竞品差评采集（公开 RSS，无需登录）")
    parser.add_argument("--app", action="append", default=[], help="id:名称，可多次，如 876336838:喜马拉雅")
    parser.add_argument("--pages", type=int, default=3, help="每个 app 取几页（每页 50，默认 3）")
    parser.add_argument("--sort", default="mostrecent", choices=["mostrecent", "mosthelpful"], help="排序")
    parser.add_argument("--max-rating", type=int, default=2, help="只留评分 ≤ 该值的评论（0=全部，默认 2）")
    parser.add_argument("--out", type=str, default="", help="输出目录（默认 data/appstore_reviews/<时间戳>）")
    args = parser.parse_args()

    apps: List[tuple[str, str]] = []
    for item in args.app:
        app_id, _, name = item.partition(":")
        if app_id.strip():
            apps.append((app_id.strip(), (name or app_id).strip()))
    if not apps:
        parser.error("至少提供一个 --app id:名称")

    out_dir = Path(args.out) if args.out else Path("data") / "appstore_reviews" / time.strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows: List[Dict[str, Any]] = []
    per_app: Dict[str, int] = {}
    for app_id, name in apps:
        rows = fetch_app(app_id, name, pages=args.pages, sort=args.sort)
        kept = [r for r in rows if args.max_rating == 0 or r["rating"] <= args.max_rating]
        all_rows.extend(kept)
        per_app[name] = len(kept)
        print(f"  {name}: 抓到 {len(rows)} 条，其中 ≤{args.max_rating} 星 {len(kept)} 条")

    csv_path = out_dir / "reviews.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    gaps = gap_counts(all_rows)
    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "apps": [{"app_id": i, "name": n} for i, n in apps],
        "pages_per_app": args.pages,
        "sort": args.sort,
        "max_rating": args.max_rating,
        "total": len(all_rows),
        "per_app": per_app,
        "gap_counts": gaps,
        "csv": str(csv_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n合计 {len(all_rows)} 条 → {csv_path}")
    print("差评里被吐槽的功能缺口：")
    for key, count in gaps.items():
        if count:
            print(f"  {key}: {count} 条")


if __name__ == "__main__":
    main()
