# -*- coding: utf-8 -*-
"""Coordinate browser-backed operations in the single-user MVP."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class OperationSnapshot:
    kind: Optional[str]
    started_at: Optional[str]


class OperationCoordinator:
    """Allow only one browser/profile operation at a time."""

    def __init__(self) -> None:
        self._state_lock = asyncio.Lock()
        self._kind: Optional[str] = None
        self._started_at: Optional[datetime] = None

    async def try_acquire(self, kind: str) -> bool:
        async with self._state_lock:
            if self._kind is not None:
                return False
            self._kind = kind
            self._started_at = datetime.now()
            return True

    async def release(self, kind: str) -> None:
        async with self._state_lock:
            if self._kind == kind:
                self._kind = None
                self._started_at = None

    def repair_stale(self, kind: str) -> None:
        """Synchronously clear a stale marker after the owned process exited."""
        if self._kind == kind:
            self._kind = None
            self._started_at = None

    def snapshot(self) -> OperationSnapshot:
        return OperationSnapshot(
            kind=self._kind,
            started_at=self._started_at.isoformat() if self._started_at else None,
        )


operation_coordinator = OperationCoordinator()
