# -*- coding: utf-8 -*-
"""费用台账:记录工具运行产生的所有 LLM 消耗。

定位:**只记账,不限制**——用户明确要求只看消耗情况,不做任何限额拦截。
存储:data/costs/ledger.jsonl(逐条追加,永不覆盖)。
计价:环境变量 LLM_PRICE_IN_PER_1M / LLM_PRICE_OUT_PER_1M(元/百万 tokens,默认 0=未计价);
      未计价时统计 tokens 与调用次数,配了价格后历史记录按当前价格回算费用。
台账写入失败绝不影响业务(静默吞掉)。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COSTS_DIR = PROJECT_ROOT / "data" / "costs"
LEDGER_FILE = COSTS_DIR / "ledger.jsonl"

_lock = threading.Lock()

ENV_PRICE_IN = "LLM_PRICE_IN_PER_1M"
ENV_PRICE_OUT = "LLM_PRICE_OUT_PER_1M"


def record(
    feature: str,
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int = 0,
    ok: bool = True,
    error: str = "",
) -> None:
    """追加一条调用记录。tokens 单位:个;失败调用也记(ok=False),保证调用次数可见。"""
    p, c = int(prompt_tokens or 0), int(completion_tokens or 0)
    entry = {
        "ts": time.time(),
        "date": time.strftime("%Y-%m-%d"),
        "feature": feature or "unknown",
        "model": str(model or ""),
        "prompt_tokens": p,
        "completion_tokens": c,
        "total_tokens": p + c,
        "duration_ms": int(duration_ms or 0),
        "ok": bool(ok),
        "error": str(error or "")[:120],
    }
    try:
        with _lock:
            COSTS_DIR.mkdir(parents=True, exist_ok=True)
            with LEDGER_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _price_in() -> float:
    try:
        return float(os.environ.get(ENV_PRICE_IN, "0") or 0)
    except ValueError:
        return 0.0


def _price_out() -> float:
    try:
        return float(os.environ.get(ENV_PRICE_OUT, "0") or 0)
    except ValueError:
        return 0.0


def _cost(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        (prompt_tokens / 1_000_000) * _price_in()
        + (completion_tokens / 1_000_000) * _price_out(),
        4,
    )


def _read_all() -> list[dict[str, Any]]:
    if not LEDGER_FILE.exists():
        return []
    entries: list[dict[str, Any]] = []
    with _lock:
        with LEDGER_FILE.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    return entries


def ledger(limit: int = 100) -> list[dict[str, Any]]:
    """最近的调用记录,新→旧。"""
    entries = _read_all()
    entries.reverse()
    return entries[: max(1, min(int(limit or 100), 5000))]


def _bucket() -> dict[str, Any]:
    return {"calls": 0, "ok_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _accum(bucket: dict[str, Any], e: dict[str, Any]) -> None:
    bucket["calls"] += 1
    bucket["ok_calls"] += 1 if e.get("ok") else 0
    bucket["prompt_tokens"] += int(e.get("prompt_tokens") or 0)
    bucket["completion_tokens"] += int(e.get("completion_tokens") or 0)
    bucket["total_tokens"] += int(e.get("total_tokens") or 0)


def summary() -> dict[str, Any]:
    """汇总:总计 / 今日 / 按功能 / 按模型;费用按当前配置价格回算。"""
    entries = _read_all()
    today = time.strftime("%Y-%m-%d")
    total = _bucket()
    today_b = _bucket()
    by_feature: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    first_ts: float | None = None
    for e in entries:
        _accum(total, e)
        if first_ts is None:
            first_ts = float(e.get("ts") or 0)
        if e.get("date") == today:
            _accum(today_b, e)
        fb = by_feature.setdefault(str(e.get("feature") or "unknown"), _bucket())
        _accum(fb, e)
        mb = by_model.setdefault(str(e.get("model") or "未知模型"), _bucket())
        _accum(mb, e)

    def _finish(b: dict[str, Any]) -> dict[str, Any]:
        b = dict(b)
        b["cost"] = _cost(b["prompt_tokens"], b["completion_tokens"])
        return b

    return {
        "pricing": {
            "input_per_1m": _price_in(),
            "output_per_1m": _price_out(),
            "configured": _price_in() > 0 or _price_out() > 0,
        },
        "total": {**_finish(total), "first_ts": first_ts},
        "today": _finish(today_b),
        "by_feature": [
            {"feature": k, **_finish(v)} for k, v in sorted(by_feature.items(), key=lambda kv: -kv[1]["total_tokens"])
        ],
        "by_model": [
            {"model": k, **_finish(v)} for k, v in sorted(by_model.items(), key=lambda kv: -kv[1]["total_tokens"])
        ],
    }
