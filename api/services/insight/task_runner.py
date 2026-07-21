# -*- coding: utf-8 -*-
"""In-process background analysis jobs with cancel support."""

from __future__ import annotations

import threading
from typing import Callable, Dict, Optional

import hashlib


_lock = threading.Lock()
_active: Dict[str, threading.Thread] = {}
_cancel: Dict[str, threading.Event] = {}


def is_running(run_id: str) -> bool:
    thread = _active.get(run_id)
    return thread is not None and thread.is_alive()


def cancel_event(run_id: str) -> Optional[threading.Event]:
    return _cancel.get(run_id)


def _safe_thread_name(run_id: str) -> str:
    digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:10]
    return f"insight-{digest}"


def start_background(run_id: str, target: Callable[[threading.Event], None]) -> bool:
    with _lock:
        if is_running(run_id):
            return False
        event = threading.Event()
        _cancel[run_id] = event

        def wrapper() -> None:
            try:
                target(event)
            finally:
                with _lock:
                    _active.pop(run_id, None)
                    _cancel.pop(run_id, None)

        thread = threading.Thread(target=wrapper, name=_safe_thread_name(run_id), daemon=True)
        _active[run_id] = thread
        thread.start()
        return True


def request_cancel(run_id: str) -> bool:
    event = _cancel.get(run_id)
    if event is None:
        return False
    event.set()
    return True
