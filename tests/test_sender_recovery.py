# -*- coding: utf-8 -*-
"""卡在 `sending` 的回复必须能被救回来。

背景（2026-11-11 审计）：
`mark_sending()` 之后如果进程被杀、浏览器崩溃或机器休眠，
条目会永远停在 `sending`：
- `next_approved()` 只挑 `approved`，它发不出去；
- 旧 funnel 只统计 5 种状态，它连数都不算，界面上完全消失。

结果是「批准过的回复凭空不见了」，用户既不知道发生了什么，也没法重试。
现在启动时会把超时的 sending 退回 `approved`，并在 funnel 里可见。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from api.services.outreach import reply_automation as auto
from api.services.outreach.reply_automation import AutomationStore


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "auto.json"
    s = AutomationStore(path=path, platform="bili")
    s.save()
    return s


def _item(item_id: str, status: str, *, sending_at: str | None = None) -> dict:
    item = {
        "id": item_id,
        "status": status,
        "commenter": "某人",
        "comment_text": "请问怎么做",
        "video_id": "BV1",
        "video_title": "示例",
        "comment_id": f"c-{item_id}",
        "draft": "可以看看这个",
        "attempts": 0,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if sending_at is not None:
        item["sending_at"] = sending_at
    return item


def test_stale_sending_item_is_recovered(store):
    """卡住 2 小时的 sending 应退回 approved。"""
    stale = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    store.add_items([_item("a", "sending", sending_at=stale)])

    recovered = auto.reconcile_stuck_sending(store, older_than_hours=1)
    assert recovered == 1

    item = next(i for i in store.items if i["id"] == "a")
    assert item["status"] == "approved", "超时的 sending 必须退回待发"
    assert item["sending_at"] == ""
    assert "中断" in item["note"]


def test_fresh_sending_item_is_left_alone(store):
    """刚开始发送的条目不能被打断（否则会重复发送）。"""
    fresh = datetime.now().isoformat(timespec="seconds")
    store.add_items([_item("b", "sending", sending_at=fresh)])

    assert auto.reconcile_stuck_sending(store, older_than_hours=1) == 0
    assert next(i for i in store.items if i["id"] == "b")["status"] == "sending"


def test_sending_without_timestamp_is_treated_as_stale(store):
    """旧数据没有 sending_at：无法证明它还在进行，按中断处理。"""
    store.add_items([_item("c", "sending")])
    assert auto.reconcile_stuck_sending(store) == 1
    assert next(i for i in store.items if i["id"] == "c")["status"] == "approved"


def test_reconcile_is_persisted(store, tmp_path):
    """恢复结果必须落盘，否则重启又回到卡死状态。"""
    stale = (datetime.now() - timedelta(hours=5)).isoformat(timespec="seconds")
    store.add_items([_item("d", "sending", sending_at=stale)])
    auto.reconcile_stuck_sending(store)

    on_disk = json.loads((tmp_path / "auto.json").read_text(encoding="utf-8"))
    saved = next(i for i in on_disk["items"] if i["id"] == "d")
    assert saved["status"] == "approved"


def test_other_statuses_untouched(store):
    store.add_items(
        [
            _item("e", "sent"),
            _item("f", "rejected"),
            _item("g", "pending_review"),
            _item("h", "approved"),
        ]
    )
    assert auto.reconcile_stuck_sending(store) == 0
    statuses = {i["id"]: i["status"] for i in store.items}
    assert statuses == {
        "e": "sent",
        "f": "rejected",
        "g": "pending_review",
        "h": "approved",
    }


def test_next_approved_picks_recovered_item(store):
    """恢复后必须真的能被发送循环选中。"""
    stale = (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds")
    store.add_items([_item("i", "sending", sending_at=stale)])
    auto.reconcile_stuck_sending(store)

    picked = store.next_approved()
    assert picked is not None and picked["id"] == "i"


def test_mark_sending_records_timestamp(store):
    """没有时间戳就没法判断是否中断——这里是预防回归。"""
    store.add_items([_item("j", "approved")])
    item = next(i for i in store.items if i["id"] == "j")
    store.mark_sending(item)
    assert item["sending_at"], "mark_sending 必须记录 sending_at"


def test_funnel_counts_sending():
    """funnel 不统计 sending 时，卡住的条目在界面里彻底不可见。"""


    class FakeStore:
        platform = "bili"
        config = {"enabled": False}
        items = [
            {"id": "1", "status": "pending_review"},
            {"id": "2", "status": "sending"},
            {"id": "3", "status": "sent"},
        ]

        def can_send_now(self):
            return False, "未启用"

        def sender_state(self):
            return {}

        _state = {"stats": {}, "cycle": {}, "sender": {}}

    import api.routers.automation as automation_router

    funnel = automation_router._funnel(FakeStore())  # type: ignore[arg-type]
    assert "sending" in funnel
    assert funnel["sending"] == 1


def test_stop_background_tasks_is_graceful(monkeypatch):
    """关闭时先置位 stop event，超时才 cancel——不硬杀正在跑的采集。"""
    started = asyncio.Event()

    async def fake_loop(stop=None):
        started.set()
        while stop is not None and not stop.is_set():
            await asyncio.sleep(0.01)

    monkeypatch.setattr(auto, "automation_loop", fake_loop)
    monkeypatch.setattr(auto, "sender_loop", fake_loop)

    async def scenario():
        auto._tasks.clear()
        auto.start_background_tasks()
        assert len(auto._tasks) == 2
        await asyncio.wait_for(started.wait(), timeout=2)
        await auto.stop_background_tasks(timeout=2)
        assert auto._tasks == []

    asyncio.run(scenario())
