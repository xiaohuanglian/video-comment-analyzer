# -*- coding: utf-8 -*-
"""YouTube 采集任务：单进程后台线程 + 状态查询。

为什么不做成 celery/队列：本机单用户、一次只跑一个采集，进程内线程足够，
重启后任务消失但**已落盘的 CSV 不丢**（断点续采靠 merge_into）。
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from . import comments

_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_MAX_KEEP = 20


def _prune() -> None:
    if len(_JOBS) <= _MAX_KEEP:
        return
    finished = sorted(
        (job for job in _JOBS.values() if job["status"] in {"done", "error"}),
        key=lambda j: j["created_at"],
    )
    for job in finished[: len(_JOBS) - _MAX_KEEP]:
        _JOBS.pop(job["id"], None)


def start_collect(
    *,
    limit: int = 3,
    channels: Optional[list[str]] = None,
    max_comments: int = comments.DEFAULT_MAX_COMMENTS,
    max_parents: Optional[int] = None,
    max_replies: Optional[int] = None,
    sort: str = "top",
    collect_fn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    running = [j for j in _JOBS.values() if j["status"] == "running"]
    if running:
        raise RuntimeError(f"已有采集在跑：{running[0]['id']}")

    job_id = uuid.uuid4().hex[:10]
    job: Dict[str, Any] = {
        "id": job_id,
        "status": "running",
        "created_at": time.time(),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": "",
        "params": {
            "limit": limit,
            "channels": channels or [],
            "max_comments": max_comments,
            "sort": sort,
        },
        "progress": {"done": 0, "total": 0, "current": "", "rows": 0},
        "result": None,
        "error": "",
    }
    with _LOCK:
        _JOBS[job_id] = job
        _prune()

    def _run() -> None:
        runner = collect_fn or comments.collect_all
        try:
            targets = comments.list_channels()
            if channels:
                wanted = {c.lower() for c in channels}
                targets = [c for c in targets if c.name.lower() in wanted]
            job["progress"]["total"] = len(targets) * max(1, limit)

            def _on_progress(event: Dict[str, Any]) -> None:
                job["progress"]["done"] += 1
                job["progress"]["rows"] += int(event.get("rows") or 0)
                job["progress"]["current"] = f"{event.get('channel')}:{event.get('video_id')}"

            result = runner(
                limit=limit,
                channels=channels,
                max_comments=max_comments,
                max_parents=max_parents,
                max_replies=max_replies,
                sort=sort,
                progress=_on_progress,
            )
            job["result"] = result
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["status"] = "error"
        finally:
            job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    threading.Thread(target=_run, daemon=True, name=f"yt-comments-{job_id}").start()
    return dict(job)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    job = _JOBS.get(job_id)
    return dict(job) if job else None


def list_jobs(limit: int = 10) -> list[Dict[str, Any]]:
    items = sorted(_JOBS.values(), key=lambda j: j["created_at"], reverse=True)[:limit]
    return [dict(j) for j in items]
