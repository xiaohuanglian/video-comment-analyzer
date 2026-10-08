# -*- coding: utf-8 -*-
"""L2 受控小规模采集：单个 B 站视频评论（复用现有爬虫，不绕过登录/风控）。

安全边界：
- 必须任务级授权（L2 grant）才能调用（权限在 tools.execute_tool 强制）。
- 单视频、评论上限（默认 50，硬顶 100）、自动遵守现有频率控制（pacer）。
- 需要扫码登录时不尝试绕过：直接返回明确错误，让用户去旧工作台登录。
- 采回的评论以 raw_comment 信号导入（不用 LLM 打标，零模型成本），
  需要深度分析时可再走原「评论洞察」管线。
"""

from __future__ import annotations

import asyncio
import csv
import glob
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..insight.paths import DATA_DIR
from . import store
from .models import Signal, SignalSourceType, utc_now_iso

HARD_MAX_COMMENTS = 100


class CrawlLoginRequired(Exception):
    pass


def _extract_bvid(target: str) -> str:
    t = (target or "").strip()
    m = re.search(r"(BV[0-9A-Za-z]+)", t)
    if not m:
        raise ValueError(f"无法从输入解析 BV 号: {target!r}（支持 BV 号或视频链接）")
    return m.group(1)


async def _crawl_one_video(target: str, max_comments: int) -> Dict[str, Any]:
    """跑一个视频的 detail 采集（临时收紧配置后复用 BilibiliCrawler）。"""
    import config
    from media_platform.bilibili import BilibiliCrawler

    orig = {
        "count": config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
        "sub": config.ENABLE_GET_SUB_COMMENTS,
        "ctype": config.CRAWLER_TYPE,
        "ids": getattr(config, "BILI_SPECIFIED_ID_LIST", []),
    }
    crawler: Optional[BilibiliCrawler] = None
    try:
        config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = max_comments
        config.ENABLE_GET_SUB_COMMENTS = False  # 只采一级评论，控制请求量
        config.CRAWLER_TYPE = "detail"
        config.BILI_SPECIFIED_ID_LIST = [target]
        crawler = BilibiliCrawler()
        await asyncio.wait_for(crawler.start(), timeout=300)
        return {"ok": True}
    except asyncio.TimeoutError as exc:
        raise CrawlLoginRequired(
            "采集超时：很可能需要扫码登录 B 站。请先在旧工作台（/）完成一次登录后再授权采集。"
        ) from exc
    except Exception as exc:
        name = type(exc).__name__.lower()
        if "login" in name or "qrcode" in name:
            raise CrawlLoginRequired(
                f"B 站需要登录（{type(exc).__name__}）。请先在旧工作台（/）登录后再授权采集。"
            ) from exc
        raise
    finally:
        config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = orig["count"]
        config.ENABLE_GET_SUB_COMMENTS = orig["sub"]
        config.CRAWLER_TYPE = orig["ctype"]
        config.BILI_SPECIFIED_ID_LIST = orig["ids"]
        # 尽力关闭浏览器，避免残留进程
        try:
            if crawler is not None and getattr(crawler, "browser_context", None):
                await crawler.browser_context.close()
        except Exception:
            pass


def _find_new_comments_file(bvid: str, since_epoch: float) -> Optional[Path]:
    candidates: List[str] = []
    for ext in ("csv", "jsonl"):
        pattern = str(DATA_DIR / "comments" / f"*{bvid}*" / f"comments_*.{ext}")
        recent = [p for p in glob.glob(pattern) if os.path.getmtime(p) >= since_epoch - 5]
        candidates.extend(recent or glob.glob(pattern))
    if not candidates:
        return None
    return Path(max(candidates, key=os.path.getmtime))


def csv_to_signals(csv_path: Path, *, product_id: str, bvid: str, limit: int) -> List[Signal]:
    """把评论文件（csv/jsonl）直接转成 raw_comment 信号（代码级，无 LLM；幂等）。"""
    import json as _json

    existing = {s.signal_id for s in store.list_signals(product_id)}
    out: List[Signal] = []

    def rows():
        if csv_path.suffix == ".jsonl":
            with csv_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            yield _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
        else:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
                yield from csv.DictReader(fh)

    for row in rows():
        if len(out) >= limit:
            break
        content = str(row.get("content") or "").strip()
        comment_id = str(row.get("comment_id") or "").strip()
        if not content or not comment_id:
            continue
        sid = f"crawl:{bvid}:{comment_id}"
        if sid in existing:
            continue
        out.append(Signal(
                signal_id=sid,
                product_id=product_id,
                source_type=SignalSourceType.EXTERNAL_COMMENT,
                source_platform="bili",
                dataset_ref=f"crawl:{bvid}",
                evidence_refs=[comment_id],
                collected_at=utc_now_iso(),
            signal_type="raw_comment",
            need_or_problem=content[:200],
            ai_classification={"raw": True, "like_count": str(row.get("like_count", "0"))},
            confidence=0.3,
            evidence_quality="high",
            usage_rights="internal_only",
        ))
    return out


def run_bilibili_comment_crawl(product_id: str, target: str, max_comments: int, reason: str,
                               timeout: int = 320) -> Dict[str, Any]:
    """工具执行入口（同步）。返回采集与导入结果。"""
    max_comments = max(10, min(int(max_comments or 50), HARD_MAX_COMMENTS))
    bvid = _extract_bvid(target)
    started = time.time()

    try:
        asyncio.run(_crawl_one_video(target, max_comments))
    except CrawlLoginRequired as exc:
        return {"status": "login_required", "message": str(exc), "imported": 0}

    csv_path = _find_new_comments_file(bvid, started)
    if csv_path is None:
        return {"status": "no_data", "message": f"采集结束但未找到 {bvid} 的评论文件（可能评论为空或被风控）",
                "imported": 0}
    signals = csv_to_signals(csv_path, product_id=product_id, bvid=bvid, limit=max_comments)
    imported = store.add_signals(signals) if signals else 0
    if imported:
        store.record_import_batch(product_id, {
            "kind": "crawl_bilibili",
            "source": f"bilibili:{bvid}",
            "count": imported,
            "data_nature": "real",
            "note": f"L2 授权采集（理由: {reason[:80]}）；raw_comment 未打标，深度分析请走评论洞察",
        })
    return {
        "status": "ok",
        "bvid": bvid,
        "csv_path": str(csv_path.relative_to(DATA_DIR)),
        "imported": imported,
        "note": "评论为 raw 信号（confidence 0.3，未打标）；受频率控制采集，勿高频调用",
    }
