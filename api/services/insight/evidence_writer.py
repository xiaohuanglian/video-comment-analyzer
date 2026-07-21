# -*- coding: utf-8 -*-
"""Single-writer queue for evidence_cards.jsonl — workers never write concurrently."""

from __future__ import annotations

import queue
import threading
from typing import Any, Optional

from .schemas import SourceRecord
from .storage import append_evidence_card


_SENTINEL = object()


class EvidenceWriterQueue:
    """Background thread drains a queue and appends JSONL rows in order."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._q: queue.Queue = queue.Queue()
        self._errors: list[BaseException] = []
        self._thread = threading.Thread(target=self._run, name=f"evidence-writer-{run_id}", daemon=True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def put(
        self,
        source: SourceRecord,
        card: Any,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        from_cache: bool = False,
    ) -> None:
        if not self._started:
            self.start()
        self._q.put(
            {
                "source": source,
                "card": card,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "from_cache": from_cache,
            }
        )

    def close(self, timeout: Optional[float] = 120.0) -> None:
        if not self._started:
            return
        self._q.put(_SENTINEL)
        self._thread.join(timeout=timeout)
        if self._errors:
            raise self._errors[0]

    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is _SENTINEL:
                    return
                append_evidence_card(
                    self.run_id,
                    item["source"],
                    item["card"],
                    prompt_tokens=item.get("prompt_tokens") or 0,
                    completion_tokens=item.get("completion_tokens") or 0,
                    from_cache=bool(item.get("from_cache")),
                )
            except BaseException as exc:  # noqa: BLE001 — surface on close
                self._errors.append(exc)
                return
            finally:
                self._q.task_done()
