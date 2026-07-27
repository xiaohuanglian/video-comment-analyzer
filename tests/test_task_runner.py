# -*- coding: utf-8 -*-
"""Background task runner tests."""

from __future__ import annotations

import threading

from api.services.insight.task_runner import is_running, reconcile_thread_state, start_background


def test_start_background_does_not_deadlock_after_reconcile():
    run_id = "deadlock-check"
    reconcile_thread_state(run_id)

    started = threading.Event()

    def job(cancel_event) -> None:  # noqa: ARG001
        started.set()

    assert start_background(run_id, job) is True
    assert started.wait(timeout=2.0)
    assert is_running(run_id) is True
