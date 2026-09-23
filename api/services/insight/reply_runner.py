# -*- coding: utf-8 -*-
"""Controlled reply run: send human-approved drafts with rate/time guardrails.

Design boundaries
-----------------
* Only entries with ``review_status == "approved"`` and non-empty final content
  are ever sent. Nothing here generates or edits text.
* The run is always started explicitly by the user and can be stopped any time.
* Frequency is bounded by a minimum interval + jitter; a daily cap and an
  allowed time window are enforced. Waiting respects the stop signal.
* Sending itself is delegated to ``reply_sender`` so it can be faked in tests.
"""

from __future__ import annotations

import random
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from .candidate_schemas import OutreachDocument, ReplyControl
from .reply_sender import ReplySendError, send_reply

Sender = Callable[..., str]


def _now() -> datetime:
    return datetime.now()


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _today_str(value: Optional[datetime] = None) -> str:
    return (value or _now()).strftime("%Y-%m-%d")


def _minutes(value: str) -> int:
    try:
        hh, mm = str(value).split(":", 1)
        return max(0, min(23, int(hh))) * 60 + max(0, min(59, int(mm)))
    except (ValueError, AttributeError):
        return 0


def seconds_until_window_open(control: ReplyControl, now: Optional[datetime] = None) -> int:
    """Seconds to wait before sending is allowed again (0 = currently allowed)."""
    now = now or _now()
    start, end = control.window_minutes
    current = now.hour * 60 + now.minute
    if start <= end:
        if start <= current <= end:
            return 0
        if current < start:
            target = now.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
        else:
            target = (now + timedelta(days=1)).replace(
                hour=start // 60, minute=start % 60, second=0, microsecond=0
            )
    else:  # overnight window, e.g. 22:00–06:00
        if current >= start or current <= end:
            return 0
        target = now.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
    return max(0, int((target - now).total_seconds()))


def _reset_daily_if_needed(doc: OutreachDocument, now: datetime) -> None:
    today = _today_str(now)
    if doc.replies_today_date != today:
        doc.replies_today_date = today
        doc.replies_sent_today = 0


class ReplyRun:
    def __init__(
        self,
        run_id: str,
        control: ReplyControl,
        user_keys: List[str],
        *,
        sender: Optional[Sender] = None,
    ) -> None:
        self.run_id = run_id
        self.control = control
        self.user_keys = list(user_keys)
        self.sender: Sender = sender or send_reply
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name=f"reply-run-{self.run_id}", daemon=True)
        self.thread.start()

    def is_alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def stop(self) -> None:
        self.stop_event.set()

    # -- internals ---------------------------------------------------------
    def _save(self, doc: OutreachDocument) -> None:
        from .storage import save_outreach

        doc.updated_at = _iso()
        save_outreach(self.run_id, doc)

    def _find(self, doc: OutreachDocument, user_key: str):
        return next((e for e in doc.entries if e.user_key == user_key), None)

    def _send_one(self, entry) -> None:
        self.sender(
            platform=entry.platform,
            content_id=entry.target_content_id,
            comment_id=entry.target_comment_id,
            message=entry.final_content,
        )

    def _wait(self, seconds: float) -> bool:
        """Sleep unless stopped. Returns False when a stop was requested."""
        if seconds <= 0:
            return not self.stop_event.is_set()
        return not self.stop_event.wait(seconds)

    def _loop(self) -> None:
        from .storage import load_outreach

        try:
            doc = load_outreach(self.run_id)
            doc.reply_control = self.control
            _reset_daily_if_needed(doc, _now())
            doc.reply_status = "running"
            doc.reply_started_at = _iso()
            doc.reply_finished_at = ""
            doc.reply_message = "已启动受控回复，等待发送窗口…"
            self._save(doc)

            for user_key in self.user_keys:
                if self.stop_event.is_set():
                    break

                doc = load_outreach(self.run_id)
                doc.reply_control = self.control
                now = _now()
                _reset_daily_if_needed(doc, now)

                if doc.replies_sent_today >= self.control.daily_limit:
                    self._finish(
                        doc,
                        "stopped",
                        f"已达当日上限 {self.control.daily_limit} 条，剩余回复请次日继续",
                    )
                    return

                entry = self._find(doc, user_key)
                if entry is None or entry.review_status != "approved" or not entry.final_content:
                    continue
                if entry.send_status == "sent":
                    continue

                wait = seconds_until_window_open(self.control, now)
                if wait > 0:
                    doc.reply_message = (
                        f"当前不在允许时段（{self.control.time_window_start}–{self.control.time_window_end}），"
                        f"等待约 {wait // 60} 分钟后继续"
                    )
                    self._save(doc)
                    if not self._wait(min(wait, 3600)):
                        self._finish(load_outreach(self.run_id), "stopped", "已手动停止")
                        return
                    continue  # re-check window/limit after sleeping

                wait = self._interval_wait(doc, now)
                if wait > 0:
                    doc.reply_message = f"遵守发送间隔，等待 {int(wait)} 秒…"
                    self._save(doc)
                    if not self._wait(wait):
                        self._finish(load_outreach(self.run_id), "stopped", "已手动停止")
                        return

                # Re-load right before sending so human edits/rejections win.
                doc = load_outreach(self.run_id)
                doc.reply_control = self.control
                entry = self._find(doc, user_key)
                if entry is None or entry.review_status != "approved" or not entry.final_content:
                    continue
                if entry.send_status == "sent":
                    continue

                entry.send_status = "sending"
                entry.attempts = int(entry.attempts or 0) + 1
                doc.reply_message = f"正在回复 {entry.username or user_key}…"
                self._save(doc)

                try:
                    self._send_one(entry)
                except ReplySendError as exc:
                    entry.send_status = "failed"
                    entry.send_error = str(exc)[:400]
                except Exception as exc:  # noqa: BLE001 - surface to user, keep going
                    entry.send_status = "failed"
                    entry.send_error = f"未预期错误：{exc}"[:400]
                else:
                    entry.send_status = "sent"
                    entry.send_error = ""
                    entry.sent_at = _iso()
                    doc.replies_sent_today = int(doc.replies_sent_today or 0) + 1
                    doc.last_reply_at = entry.sent_at
                    self._mark_candidate_contacted(user_key)

                self._save(doc)

            self._finish(load_outreach(self.run_id), "completed", "全部已审核回复已处理完成")
        except Exception as exc:  # noqa: BLE001 - never kill the server thread silently
            try:
                doc = load_outreach(self.run_id)
                self._finish(doc, "failed", f"回复任务异常终止：{exc}"[:400])
            except Exception:
                pass

    def _interval_wait(self, doc: OutreachDocument, now: datetime) -> float:
        if not doc.last_reply_at:
            return 0.0
        try:
            last = datetime.fromisoformat(doc.last_reply_at)
        except (TypeError, ValueError):
            return 0.0
        base = self.control.interval_seconds + random.randint(0, max(0, self.control.jitter_seconds))
        elapsed = (now - last).total_seconds()
        return max(0.0, base - elapsed)

    def _mark_candidate_contacted(self, user_key: str) -> None:
        try:
            from .candidates import merge_candidate_updates
            from .storage import load_candidates, save_candidates

            candidates = load_candidates(self.run_id)
            if merge_candidate_updates(candidates, user_key=user_key, contact_status="contacted"):
                save_candidates(self.run_id, candidates)
        except Exception:
            pass

    def _finish(self, doc: OutreachDocument, status: str, message: str) -> None:
        doc.reply_status = status
        doc.reply_message = message
        doc.reply_finished_at = _iso()
        self._save(doc)


# --- process-wide registry ---------------------------------------------------

_runs: Dict[str, ReplyRun] = {}
_registry_lock = threading.Lock()


def get_reply_run(run_id: str) -> Optional[ReplyRun]:
    return _runs.get(run_id)


def is_reply_running(run_id: str) -> bool:
    run = _runs.get(run_id)
    return bool(run and run.is_alive())


def start_reply_run(
    run_id: str,
    control: ReplyControl,
    user_keys: List[str],
    *,
    sender: Optional[Sender] = None,
) -> bool:
    """Start a run; returns False if one is already active for this run id."""
    with _registry_lock:
        existing = _runs.get(run_id)
        if existing and existing.is_alive():
            return False
        run = ReplyRun(run_id, control, user_keys, sender=sender)
        _runs[run_id] = run
        run.start()
        return True


def stop_reply_run(run_id: str) -> bool:
    run = _runs.get(run_id)
    if not run or not run.is_alive():
        return False
    run.stop()
    return True