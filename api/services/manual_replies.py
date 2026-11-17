"""Human reply shortlist. Its persistent records never enter the automated sender."""
from __future__ import annotations

import asyncio
import hashlib
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from api.services.json_store import JsonListStore
from api.services.outreach import reply_automation as auto
from api.services.outreach.reply_campaign import make_campaign

ROOT = Path(__file__).resolve().parents[2] / "data" / "manual_replies"
PLATFORMS = {"bili": "B 站", "dy": "抖音", "xhs": "小红书"}
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.RLock()
_tasks: set[asyncio.Task] = set()


def records(platform: str) -> JsonListStore:
    if platform not in PLATFORMS:
        raise ValueError("仅支持 B 站、抖音、小红书")
    return JsonListStore(ROOT / f"{platform}.json")


def reply_location(item: dict[str, Any]) -> dict[str, str]:
    """Use platform links, never apply Bilibili anchors to Douyin/Xiaohongshu."""
    platform = item["platform"]
    domains = {"bili": ("bilibili.com",), "dy": ("douyin.com",), "xhs": ("xiaohongshu.com", "xhslink.com")}
    url = ""
    for value in (item.get("comment_url"), item.get("video_url")):
        candidate = str(value or "")
        parsed = urlsplit(candidate)
        host = parsed.hostname or ""
        if parsed.scheme in ("http", "https") and any(host == domain or host.endswith("." + domain) for domain in domains[platform]):
            url = candidate
            break
    vid = quote(str(item.get("video_id") or ""), safe="")
    cid = quote(str(item.get("comment_id") or ""), safe="")
    if platform == "bili":
        if not url and vid:
            url = f"https://www.bilibili.com/video/{vid if vid.startswith('BV') else 'av' + vid}"
        if url:
            url = url.split("#", 1)[0] + f"#reply{cid}"
        hint = "打开原视频评论区；若未定位到评论，可按昵称和评论原文查找。"
    elif platform == "dy":
        url = url or (f"https://www.douyin.com/video/{vid}" if vid else "")
        hint = "打开抖音原视频后，展开评论区，按昵称和评论原文查找；链接不保证直达该评论。"
    else:
        url = url or (f"https://www.xiaohongshu.com/explore/{vid}" if vid else "")
        hint = "打开原笔记，按昵称和评论原文查找；访问令牌失效时需重新登录或重新采集。"
    return {"reply_url": url, "location_hint": hint}


def job_status(platform: str) -> dict[str, Any]:
    records(platform)
    with _lock:
        return dict(_jobs.get(platform, {"running": False, "phase": "idle", "message": "尚未开始筛选"}))


def list_items(platform: str, status: str, profile_id: str, offset: int, limit: int) -> dict[str, Any]:
    rows = [row for row in records(platform).load() if not profile_id or row.get("profile_id") == profile_id]
    counts = {key: sum(row.get("status") == key for row in rows) for key in ("pending", "done", "skipped")}
    selected = [row for row in rows if row.get("status") == status]
    selected.sort(key=lambda row: (-float(row.get("worth") or 0), -float(row.get("like_count") or 0), row["id"]))
    return {"items": selected[offset:offset + limit], "total": len(selected), "counts": counts, "job": job_status(platform)}


def mark(platform: str, item_id: str, status: str) -> dict[str, Any]:
    def update(rows):
        for row in rows:
            if row["id"] == item_id:
                row["status"] = status
                row["marked_at"] = datetime.now().isoformat(timespec="seconds")
                if status == "done":
                    for other in rows:
                        if other.get("comment_id") == row["comment_id"] and other.get("status") == "pending":
                            other["status"] = "done"
                            other["marked_at"] = row["marked_at"]
                return dict(row)
        raise KeyError(item_id)
    return records(platform).read_modify_write(update)


def _set_job(platform: str, **patch) -> None:
    with _lock:
        _jobs[platform] = {**_jobs.get(platform, {}), **patch}


def _read_sources(platform: str):
    rows_a, videos_a = auto.read_collected(auto.BULK_COMMENT_DIR, platform=platform)
    rows_b, videos_b = auto.read_collected(auto.comment_dir_for(platform), platform=platform)
    unique = {str(row.get("comment_id")): row for row in rows_a + rows_b if row.get("comment_id")}
    return list(unique.values()), {**videos_a, **videos_b}


async def screen(platform: str, mode: str, campaign: dict | None, limit: int, days: int) -> None:
    """Persist only reviewed targets, no drafting, approval or sending side effects."""
    try:
        _set_job(platform, phase="reading", message="正在读取本平台已采集的评论…")
        rows, videos = await asyncio.to_thread(_read_sources, platform)
        if not rows:
            raise ValueError(f"没有找到{PLATFORMS[platform]}的评论，请先到“采集评论”采一批。")
        profile_id = (campaign or {}).get("profile_id", "")
        existing = records(platform).load()
        processed = {str(row["comment_id"]) for row in existing if row.get("status") == "done" or row.get("profile_id", "") == profile_id}
        # Also exclude already sent / approved comments in the original workflow.
        sender = auto.get_store(platform)
        processed.update(str(row.get("comment_id")) for row in sender.items if row.get("status") in ("approved", "sending", "sent"))
        cfg = {**sender.config, "enabled": False, "hot_comment_enabled": False,
               "freshness_b_hours": days * 24, "_defer_video_cap": True,
               "_semantic_recall": mode == "ai", "max_new_candidates_per_cycle": len(rows)}
        cfg["_replied_users"] = dict(sender._state.get("replied_users") or {})
        # Normalize all platforms' timestamps, including old Bilibili date strings.
        rows = [{**row, "create_time": auto._normalize_ts(row.get("create_time"))} for row in rows]
        pool, funnel = auto.build_candidates(rows, videos, cfg, processed, platform=platform)
        pool.sort(key=lambda row: (-row.get("like_count", 0), row.get("age_hours", 0)))
        # Round-robin videos so one large thread cannot consume the AI budget.
        buckets: dict[str, list[dict]] = {}
        for row in pool:
            buckets.setdefault(row["video_id"], []).append(row)
        balanced = []
        while buckets:
            for key in list(buckets):
                balanced.append(buckets[key].pop(0))
                if not buckets[key]:
                    del buckets[key]
        budget = min(len(balanced), max(50, limit * 3), 300) if mode == "ai" else len(balanced)
        selected = []
        examined = 0
        failures = 0
        for offset in range(0, budget, 25):
            batch = balanced[offset:min(offset + 25, budget)]
            if mode == "ai":
                _set_job(platform, phase="screening", message=f"AI 已评估 {examined} 条，已入选 {len(selected)} 条…")
                kept, stats = await auto.llm_screen_candidates(batch, threshold=6, campaign=campaign)
                failures += stats.get("llm_failed", 0)
            else:
                kept = batch
            examined += len(batch)
            selected.extend(kept[:max(0, limit - len(selected))])
            if len(selected) >= limit:
                break
        now = datetime.now().isoformat(timespec="seconds")
        additions = []
        for row in selected:
            key = hashlib.sha256(f"{platform}:{profile_id}:{row['comment_id']}".encode()).hexdigest()[:24]
            row = {**row, "id": f"manual_{key}", "status": "pending", "mode": mode,
                   "profile_id": profile_id, "profile_name": (campaign or {}).get("profile_name", "规则初筛"),
                   "reply_goal": (campaign or {}).get("reply_goal", ""), "created_at": now,
                   "comment_text": next((str(r.get("content") or "") for r in rows if str(r.get("comment_id")) == row["comment_id"]), row["comment_text"])}
            row.update(reply_location(row))
            additions.append(row)
        def merge(saved):
            known = {row["id"] for row in saved}
            fresh = [row for row in additions if row["id"] not in known]
            saved.extend(fresh)
            return len(fresh)
        added = records(platform).read_modify_write(merge)
        _set_job(platform, phase="completed", message=f"筛选完成，新增 {added} 条待回复评论。", summary={
            "comments": len(rows), "eligible": len(pool), "examined": examined, "added": added,
            "not_examined": max(0, len(pool) - examined), "model_failures": failures, "funnel": funnel,
            "mode": mode, "profile_id": profile_id,
        })
    except Exception as exc:  # noqa: BLE001 - background failures must be visible to the user
        _set_job(platform, phase="failed", message=f"筛选未完成：{str(exc)[:300]}")
    finally:
        _set_job(platform, running=False)


def start(platform: str, mode: str, profile_id: str, goal: str, limit: int, days: int) -> dict[str, Any]:
    records(platform)
    campaign = make_campaign(profile_id, goal, "recommend") if mode == "ai" else None
    with _lock:
        if _jobs.get(platform, {}).get("running"):
            raise RuntimeError("本平台已有筛选任务，等待完成后再试。")
        _jobs[platform] = {"running": True, "phase": "starting", "message": "筛选已开始…", "profile_id": profile_id if mode == "ai" else "", "mode": mode}
    task = asyncio.create_task(screen(platform, mode, campaign, limit, days))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job_status(platform)
