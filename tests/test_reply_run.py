# -*- coding: utf-8 -*-
"""Controlled reply run: human gate + frequency/time guardrails."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from api.services.insight.candidate_schemas import (
    OutreachDocument,
    OutreachEntry,
    ReplyControl,
)
from api.services.insight.field_mapping import parse_bilibili_targets
from api.services.insight.outreach import merge_outreach_update
from api.services.insight.reply_runner import (
    ReplyRun,
    ReplySendError,
    seconds_until_window_open,
    start_reply_run,
    stop_reply_run,
)
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import create_run, load_outreach, save_outreach


def _isolate(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for mod in (
        "api.services.insight.storage",
        "api.services.insight.run_locations",
        "api.services.insight.paths",
    ):
        monkeypatch.setattr(f"{mod}.DATA_DIR", data_dir, raising=False)
        monkeypatch.setattr(f"{mod}.RUNS_ROOT", data_dir / "analysis_runs", raising=False)
    return data_dir


def _make_run(run_id: str = "reply_run") -> RunConfig:
    config = RunConfig(
        run_id=run_id,
        name="回复测试",
        file_paths=["a.csv"],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=True,
        created_at="2026-01-01T00:00:00Z",
        storage_dir=run_id,
    )
    create_run(config, [])
    return config


def test_parse_bilibili_targets():
    assert parse_bilibili_targets("https://www.bilibili.com/video/BV1xx411c7mD#reply12345") == (
        "BV1xx411c7mD",
        "12345",
    )
    assert parse_bilibili_targets("") == ("", "")


def test_review_status_transitions_send_state():
    doc = OutreachDocument(entries=[OutreachEntry(user_key="u1", generated_draft="hi")])
    merge_outreach_update(doc, "u1", review_status="approved")
    entry = doc.entries[0]
    assert entry.review_status == "approved"
    assert entry.send_status == "queued"
    merge_outreach_update(doc, "u1", review_status="rejected")
    assert entry.send_status == "skipped"


def test_seconds_until_window_open():
    control = ReplyControl(time_window_start="09:00", time_window_end="22:00")
    assert seconds_until_window_open(control, datetime(2026, 1, 1, 8, 0)) == 3600
    assert seconds_until_window_open(control, datetime(2026, 1, 1, 12, 0)) == 0
    # after the window, waits until the next morning
    assert seconds_until_window_open(control, datetime(2026, 1, 1, 23, 0)) == 10 * 3600


def test_interval_wait_respects_minimum_gap():
    control = ReplyControl(interval_seconds=10, jitter_seconds=0)
    run = ReplyRun("r", control, ["u1"], sender=lambda **_: "ok")
    doc = OutreachDocument(last_reply_at=(datetime.now() - timedelta(seconds=3)).isoformat(timespec="seconds"))
    wait = run._interval_wait(doc, datetime.now())
    assert 6 <= wait <= 8


def test_reply_run_sends_only_approved(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    run_id = "reply_run"
    _make_run(run_id)
    sent = []

    def fake_sender(*, platform, content_id, comment_id, message):
        sent.append((content_id, comment_id, message))
        return "rpid1"

    doc = OutreachDocument(
        entries=[
            OutreachEntry(
                user_key="approved",
                generated_draft="已通过内容",
                review_status="approved",
                send_status="queued",
                platform="bili",
                target_content_id="BV1",
                target_comment_id="100",
            ),
            OutreachEntry(
                user_key="draft",
                generated_draft="未审核内容",
                platform="bili",
                target_content_id="BV2",
                target_comment_id="200",
            ),
        ]
    )
    save_outreach(run_id, doc)

    control = ReplyControl(
        interval_seconds=10,
        jitter_seconds=0,
        daily_limit=30,
        time_window_start="00:00",
        time_window_end="23:59",
    )
    assert start_reply_run(run_id, control, ["approved", "draft"], sender=fake_sender) is True
    # A second concurrent start for the same run must be rejected.
    assert start_reply_run(run_id, control, ["draft"], sender=fake_sender) is False

    deadline = time.time() + 5
    while time.time() < deadline and not _is_done(run_id):
        time.sleep(0.05)

    assert sent == [("BV1", "100", "已通过内容")]
    final = load_outreach(run_id)
    statuses = {e.user_key: e.send_status for e in final.entries}
    assert statuses["approved"] == "sent"
    assert statuses["draft"] == "pending"
    assert final.reply_status == "completed"


def test_reply_run_records_failure_and_continues(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    run_id = "reply_fail"
    _make_run(run_id)

    def flaky_sender(*, platform, content_id, comment_id, message):
        if content_id == "BV_bad":
            raise ReplySendError("平台限流")
        return "ok"

    doc = OutreachDocument(
        entries=[
            OutreachEntry(
                user_key="bad",
                generated_draft="会失败",
                review_status="approved",
                send_status="queued",
                platform="bili",
                target_content_id="BV_bad",
                target_comment_id="1",
            ),
        ]
    )
    save_outreach(run_id, doc)
    control = ReplyControl(interval_seconds=10, jitter_seconds=0, time_window_start="00:00", time_window_end="23:59")
    start_reply_run(run_id, control, ["bad"], sender=flaky_sender)
    deadline = time.time() + 5
    while time.time() < deadline and not _is_done(run_id):
        time.sleep(0.05)

    final = load_outreach(run_id)
    entry = final.entries[0]
    assert entry.send_status == "failed"
    assert "限流" in entry.send_error
    assert entry.attempts == 1


def test_stop_reply_run_is_safe_when_idle():
    assert stop_reply_run("does-not-exist") is False


def _is_done(run_id: str) -> bool:
    from api.services.insight.reply_runner import is_reply_running

    if is_reply_running(run_id):
        return False
    return load_outreach(run_id).reply_status in {"completed", "stopped", "failed"}