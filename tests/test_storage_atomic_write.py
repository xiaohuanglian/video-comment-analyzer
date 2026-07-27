# -*- coding: utf-8 -*-
"""Storage atomic write concurrency tests."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from api.services.insight.storage import _write_json


def test_concurrent_write_json_does_not_race(tmp_path):
    path = tmp_path / "progress.json"
    errors: list[BaseException] = []

    def writer(i: int) -> None:
        try:
            for j in range(40):
                _write_json(path, {"i": i, "j": j, "payload": "x" * 200})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(writer, range(8)))

    assert not errors, errors
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.strip().startswith("{")
