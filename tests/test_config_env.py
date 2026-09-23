# -*- coding: utf-8 -*-
"""Config env overrides used by the Web UI crawler subprocess."""

from __future__ import annotations

import importlib

import config.base_config as bc


def test_env_bool_parsing(monkeypatch):
    for raw, expected in (("1", True), ("true", True), ("yes", True), ("on", True),
                          ("0", False), ("false", False), ("no", False), ("off", False)):
        monkeypatch.setenv("VCA_TEST_FLAG", raw)
        assert bc._env_bool("VCA_TEST_FLAG", True) is expected
    monkeypatch.delenv("VCA_TEST_FLAG", raising=False)
    assert bc._env_bool("VCA_TEST_FLAG", True) is True
    assert bc._env_bool("VCA_TEST_FLAG", False) is False


def test_cdp_connect_existing_honours_env(monkeypatch):
    monkeypatch.setenv("CDP_CONNECT_EXISTING", "0")
    reloaded = importlib.reload(bc)
    try:
        assert reloaded.CDP_CONNECT_EXISTING is False
    finally:
        monkeypatch.delenv("CDP_CONNECT_EXISTING", raising=False)
        importlib.reload(bc)