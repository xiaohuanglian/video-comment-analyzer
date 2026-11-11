# -*- coding: utf-8 -*-
"""重算「热评竞争强度」的语料基线。

`api/services/outreach/hot_comment.py` 里的 `PLAY_TIERS` 中位数是硬编码的实测值，
不是拍脑袋的。这个脚本用来复现那组数字——语料构成变了（换了账号、换了领域、
采集口径改了），中位数就该重算。

    uv run python scripts/hot_comment_stats.py

输出：
1. 播放档 × 根评论最高赞的分位与中位数（这是 `PLAY_TIERS` 的来源）
2. 子回复占比、零子回复的根评论比例（回答「回每条评论值不值」）
3. 评论相对视频发布时间的到达分布（回答「热评窗口是不是发布后 24h」）
4. 竞争空白视频占比（top1 远低于同档中位）
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
#: 语料分布在两个目录：批量采集（data/comments）与回复通道自己采的
#: （data/automation/comments）。两边采到的是不同批次，合并后才是完整样本。
COMMENT_DIRS = (
    PROJECT_ROOT / "data" / "comments",
    PROJECT_ROOT / "data" / "automation" / "comments",
)

#: 与 hot_comment.PLAY_TIERS 保持同一组分档（上限不含）
TIERS: tuple[tuple[int | None, str], ...] = (
    (1_000, "冷启动(<1k)"),
    (5_000, "小流量(1k-5k)"),
    (20_000, "中流量(5k-2w)"),
    (50_000, "中高流量(2w-5w)"),
    (200_000, "高流量(5w-20w)"),
    (1_000_000, "大流量(20w-100w)"),
    (None, "爆款(>100w)"),
)

import re  # noqa: E402

_WAN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*[wW万]\s*\+?\s*$")


def parse_count(value: Any) -> int:
    """'5305' / '10万+' / '1.2w' / 5305 → int；解析不出返回 0。"""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value or "").strip()
    if not text:
        return 0
    m = _WAN.match(text)
    if m:
        return int(float(m.group(1)) * 10_000)
    try:
        return max(0, int(float(re.sub(r"[^0-9.]", "", text) or 0)))
    except (TypeError, ValueError):
        return 0


def iter_jsonl(directory: Path, prefix: str) -> Iterable[dict[str, Any]]:
    """逐行读 jsonl。用 split("\\n") 而不是 splitlines：正文里可能带 U+2028，
    splitlines 会把它当换行，把一行 JSON 从中间劈开（读数据的老坑）。"""
    for path in sorted(directory.glob(f"{prefix}_*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def tier_of(play: int) -> str:
    for upper, label in TIERS:
        if upper is None or play < upper:
            return label
    return TIERS[-1][1]


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def main() -> int:
    videos: dict[str, dict[str, Any]] = {}
    raw_comments: list[dict[str, Any]] = []
    for directory in COMMENT_DIRS:
        if not directory.exists():
            continue
        for row in iter_jsonl(directory, "contents"):
            vid = str(row.get("video_id") or "")
            if vid and vid not in videos:
                videos[vid] = row
        raw_comments.extend(iter_jsonl(directory, "comments"))
    # 按 comment_id 去重：采集中途会切排序再采一遍（默认热序 → 时间序），
    # 同一批评论会跨 jsonl 文件（甚至跨目录）重复落盘。不去重的话根评论点赞被
    # 算两遍、分档中位数跟着失真（第一版 PLAY_TIERS 就是这么错的）。
    by_id: dict[str, dict[str, Any]] = {}
    for row in raw_comments:
        cid = str(row.get("comment_id") or "")
        if cid and cid not in by_id:
            by_id[cid] = row
    comments = list(by_id.values())
    if not videos or not comments:
        print(f"没有语料：{COMMENT_DIRS}", file=sys.stderr)
        return 1
    dup = len(raw_comments) - len(comments)
    if dup:
        print(f"（已按 comment_id 去重：读入 {len(raw_comments):,} 行，重复 {dup:,} 行）")

    roots = [c for c in comments if str(c.get("parent_comment_id") or "0") in ("0", "")]
    subs = [c for c in comments if str(c.get("parent_comment_id") or "0") not in ("0", "")]
    print(f"评论 {len(comments):,} 条（根 {len(roots):,} / 子 {len(subs):,}）· 视频 {len(videos):,} 个")

    # ---- 1. 播放档 × top1 赞 ----
    # top1 赞是我们采到的那批根评论里的最大值。**不要按覆盖率过滤**——实测抽样
    # 对比平台真热序（reply/main?mode=3），语料 top1 与真值的比值中位 1.00，
    # 采得少的视频只是样本少，不是 top1 偏低。真正不可信的是「采到 0–4 条」，
    # 界面上单独提示即可（这一点由 hot_comment.hot_comment_min_sample 把关）。
    by_vid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in roots:
        by_vid[str(c.get("video_id") or "")].append(c)
    by_tier: dict[str, list[int]] = defaultdict(list)
    by_tier_good: dict[str, list[int]] = defaultdict(list)
    coverage: dict[str, list[float]] = defaultdict(list)
    sample_buckets: dict[str, int] = defaultdict(int)
    for vid, video in videos.items():
        tops = [parse_count(c.get("like_count")) for c in by_vid.get(vid) or []]
        top1 = max(tops) if tops else 0
        reported = parse_count(video.get("video_comment"))
        label = tier_of(parse_count(video.get("video_play_count")))
        if reported:
            coverage[label].append(len(tops) / reported)
        n = len(tops)
        sample_buckets["0-4" if n < 5 else "5-19" if n < 20 else "20-99" if n < 100 else "100+"] += 1
        by_tier[label].append(top1)
        if n >= 5:
            by_tier_good[label].append(top1)

    print("\n[1] 播放档 → 根评论最高赞（全量，不按覆盖率过滤）")
    print(
        f"{'档位':<18}{'视频':>6}{'p25':>7}{'中位':>7}{'p75':>7}{'最大':>9}"
        f"{'覆盖率':>8}{'n≥5':>6}{'中位(采足)':>11}"
    )
    medians: dict[str, int] = {}
    for _, label in TIERS:
        values = by_tier.get(label) or []
        good = by_tier_good.get(label) or []
        cov = coverage.get(label) or []
        cov_text = f"{statistics.median(cov):.0%}" if cov else "-"
        if not values:
            print(f"{label:<18}{0:>6}{cov_text:>8}")
            continue
        # PLAY_TIERS 用「采样充足」那部分的中位：样本少的视频 top1 系统性偏低
        med = int(statistics.median(good)) if good else int(statistics.median(values))
        medians[label] = med
        print(
            f"{label:<18}{len(values):>6}{pct(values, 0.25):>7.0f}{int(statistics.median(values)):>7}"
            f"{pct(values, 0.75):>7.0f}{max(values):>9}{cov_text:>8}"
            f"{len(good):>6}{med:>11}"
        )
    buckets = " / ".join(f"{k}: {sample_buckets.get(k, 0)}" for k in ("0-4", "5-19", "20-99", "100+"))
    print(f"\n每视频采样到的根评论条数：{buckets}")
    print("  → 采到 0–4 条时 top1 不可信（实测六成判断是错的），代码里由"
          " hot_comment_min_sample 兜住，判 unknown_coverage 不动手")
    print("\n可粘贴进 hot_comment.PLAY_TIERS 的中位数（取「采样充足」列）：")
    print("    " + ", ".join(f'("{label}", {medians.get(label, 0)})' for _, label in TIERS))

    # ---- 2. 子回复结构 ----
    # 注意：这一项**不是**平台真相，是我们采集覆盖率的函数。楼中楼是单独一页
    # 接口，早期采集没翻，所以「零子回复」比例会被严重高估。这里同时打印覆盖率，
    # 看的人自己判断可信度。
    root_ids = {str(r.get("comment_id") or "") for r in roots}
    subs_of_root = [c for c in subs if str(c.get("parent_comment_id") or "") in root_ids]
    videos_with_subs = len({str(c.get("video_id") or "") for c in subs})
    reply_counts: dict[str, int] = defaultdict(int)
    for c in subs:
        reply_counts[str(c.get("parent_comment_id") or "")] += 1
    zero = sum(1 for r in roots if reply_counts.get(str(r.get("comment_id") or ""), 0) == 0)
    print("\n[2] 子回复结构（受采集覆盖率限制，仅供参考）")
    print(f"  采到过子回复的视频：{videos_with_subs}/{len(videos)}（其余视频的子回复根本没采集）")
    print(f"  子回复占全部评论：{len(subs) / max(1, len(comments)):.1%}（直接挂在根下的 {len(subs_of_root):,}）")
    print(f"  零子回复的根评论：{zero:,}/{len(roots):,}（{zero / max(1, len(roots)):.1%}）")
    print("  → 覆盖率低于 80% 时，这个比例只能当下界，不能当「评论没人回」的证据")

    # ---- 3. 到达时间 ----
    gaps: list[float] = []
    for c in comments:
        try:
            t = int(c.get("create_time") or 0)
        except (TypeError, ValueError):
            continue
        # 脏数据：有 year 58743 这种越界时间戳，做时间判断必须过滤
        if not (1e9 < t < 2_000_000_000):
            continue
        video = videos.get(str(c.get("video_id") or ""))
        if not video:
            continue
        try:
            born = int(video.get("create_time") or 0)
        except (TypeError, ValueError):
            continue
        if not (1e9 < born < 2_000_000_000) or t < born:
            continue
        gaps.append((t - born) / 3600)
    if gaps:
        print("\n[3] 评论相对发布的到达时间（小时）")
        print(f"  n={len(gaps):,}  p10={pct(gaps, .1):.0f}  p25={pct(gaps, .25):.0f}  "
              f"中位={pct(gaps, .5):.0f}  p75={pct(gaps, .75):.0f}  p90={pct(gaps, .9):.0f}")
        for h in (6, 24, 48, 72, 168):
            share = sum(1 for g in gaps if g <= h) / len(gaps)
            print(f"  {h:>4}h 内：{share:.1%}")

    # ---- 4. 竞争空白 ----
    blank = total = 0
    for vid, video in videos.items():
        play = parse_count(video.get("video_play_count"))
        label = tier_of(play)
        med = medians.get(label, 0)
        if med <= 0:
            continue
        tops = [parse_count(c.get("like_count")) for c in roots if str(c.get("video_id") or "") == vid]
        top1 = max(tops) if tops else 0
        total += 1
        if top1 < med / 4:
            blank += 1
    if total:
        print("\n[4] 竞争空白（top1 < 同档中位 1/4）")
        print(f"  {blank}/{total}（{blank / total:.1%}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
