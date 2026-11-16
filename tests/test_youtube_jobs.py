# -*- coding: utf-8 -*-
"""YouTube 采集任务：状态流转 / 并发保护（离线，不联网）。"""

from __future__ import annotations

import time
from threading import Event

import pytest

from api.services.youtube import jobs


@pytest.fixture(autouse=True)
def clean_jobs():
    jobs._JOBS.clear()
    yield
    jobs._JOBS.clear()


def _wait(job_id: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.get_job(job_id) or {}
        if job.get("status") in {"done", "error"}:
            return job
        time.sleep(0.02)
    raise AssertionError("任务没有在预期时间内结束")


def test_collect_job_completes_and_reports_progress():
    seen = {}
    release = Event()

    def fake_collect(**kwargs):
        assert release.wait(timeout=10), "测试未释放采集任务"
        seen.update(kwargs)
        kwargs["progress"]({"channel": "ch", "video_id": "v1", "rows": 7, "error": ""})
        return {"channels": [], "total": 7}

    job = jobs.start_collect(limit=1, channels=["LiamOttley"], collect_fn=fake_collect)
    try:
        assert job["status"] == "running"
    finally:
        release.set()

    done = _wait(job["id"])
    assert done["status"] == "done"
    assert done["result"] == {"channels": [], "total": 7}
    assert done["progress"]["rows"] == 7
    assert done["progress"]["done"] == 1
    assert done["finished_at"]
    assert seen["sort"] == "top"
    assert seen["limit"] == 1


def test_collect_job_records_error():
    def boom(**kwargs):
        raise RuntimeError("yt-dlp 挂了")

    job = jobs.start_collect(limit=1, collect_fn=boom)
    done = _wait(job["id"])
    assert done["status"] == "error"
    assert "yt-dlp 挂了" in done["error"]


def test_second_job_rejected_while_running():
    release = {"go": False}

    def slow(**kwargs):
        while not release["go"]:
            time.sleep(0.01)
        return {}

    job = jobs.start_collect(limit=1, collect_fn=slow)
    with pytest.raises(RuntimeError):
        jobs.start_collect(limit=1, collect_fn=slow)
    release["go"] = True
    _wait(job["id"])


def test_list_jobs_newest_first():
    jobs.start_collect(limit=1, collect_fn=lambda **kw: {})
    _wait(jobs.list_jobs()[0]["id"])
    jobs.start_collect(limit=1, collect_fn=lambda **kw: {})
    items = jobs.list_jobs()
    assert len(items) == 2
    assert items[0]["created_at"] >= items[1]["created_at"]
