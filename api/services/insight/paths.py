# -*- coding: utf-8 -*-
"""Shared filesystem paths for insight module."""

from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = APP_DIR / "data"
RUNS_ROOT = DATA_DIR / "analysis_runs"
RUN_INDEX_PATH = DATA_DIR / ".insight_run_index.json"
INSIGHT_SUBDIR = ".insight"
