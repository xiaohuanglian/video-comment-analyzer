# -*- coding: utf-8 -*-
"""Storage boundary for local MVP and future SaaS dataset persistence."""

from typing import Protocol

from ..schemas.analysis import Dataset


class DatasetRepository(Protocol):
    async def save(self, dataset: Dataset) -> Dataset:
        """Persist a normalized dataset."""
        ...

    async def get(
        self,
        dataset_id: str,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Dataset | None:
        """Load a dataset within an optional tenant boundary."""
        ...
