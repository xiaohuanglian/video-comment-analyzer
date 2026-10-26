# -*- coding: utf-8 -*-
"""知识原子检索(风物执守·XY 操盘系统,本地 data/knowledge/xyskill/)。

数据许可 CC BY-NC 4.0:仅本机内部使用(对话上下文/起草参考),
不进公开仓库、不再分发。引用时带原子编号与来源。

检索方案:轻量关键词打分(词元重合 + 话题命中 + 置信度加权),
2.8 万条原子全量内存匹配,毫秒级,无需向量库。
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ATOMS_FILE = PROJECT_ROOT / "data" / "knowledge" / "xyskill" / "atoms.jsonl"

_CONF_WEIGHT = {"high": 1.3, "medium": 1.0, "low": 0.8, None: 1.0}
# 停用词(查询侧切出的高频虚词不计分)
_STOP = set("的了是有在和与对从被把这就那也都很还再又才只要不了怎么什么为什么".replace(" ", ""))

_lock = threading.Lock()
_cache: dict[str, Any] = {"loaded": False, "atoms": []}


def _load_atoms() -> list[dict[str, Any]]:
    if _cache["loaded"]:
        return _cache["atoms"]
    with _lock:
        if _cache["loaded"]:
            return _cache["atoms"]
        atoms: list[dict[str, Any]] = []
        if ATOMS_FILE.exists():
            for line in ATOMS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                k = str(d.get("knowledge") or "").strip()
                if k:
                    atoms.append(
                        {
                            "id": str(d.get("id") or ""),
                            "knowledge": k,
                            "topics": [str(t) for t in (d.get("topics") or [])],
                            "confidence": str(d.get("confidence") or ""),
                            "source_label": str(d.get("source_label") or ""),
                        }
                    )
        _cache["atoms"] = atoms
        _cache["loaded"] = True
    return atoms


def _tokens(text: str) -> list[str]:
    """中文粗切词:2字滑窗 + 拉出的英文/数字词,去停用单字。"""
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    tokens: list[str] = []
    for chunk in text.split():
        if re.fullmatch(r"[A-Za-z0-9_.-]+", chunk):
            tokens.append(chunk.lower())
            continue
        for ch in chunk:
            if ch in _STOP:
                continue
        for i in range(len(chunk) - 1):
            bigram = chunk[i : i + 2]
            if any(c in _STOP for c in bigram):
                continue
            tokens.append(bigram)
    return tokens


def search(
    query: str,
    k: int = 6,
    topics: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """按查询词检索知识原子,返回 Top-k(带 id/置信度/来源)。"""
    atoms = _load_atoms()
    if not atoms or not (query or "").strip():
        return []
    q_tokens = set(_tokens(query))
    if not q_tokens:
        return []
    q_topic = {t for t in topics or []}
    scored: list[tuple[float, dict[str, Any]]] = []
    for a in atoms:
        text = a["knowledge"]
        score = 0.0
        for t in q_tokens:
            if t in text:
                score += 2.0 if len(t) > 2 else 1.0
        if not score:
            continue
        for tp in a["topics"]:
            if tp in q_topic or any(t in query for t in (tp,)):
                score += 1.5
        score *= _CONF_WEIGHT.get(a["confidence"], 1.0)
        if score > 1.0:
            scored.append((score, a))
    scored.sort(key=lambda x: -x[0])
    return [a for _, a in scored[:k]]


def count() -> int:
    return len(_load_atoms())


def context_for(query: str, k: int = 5, max_chars: int = 1800) -> str:
    """给 system prompt 的知识上下文段落;无命中返回空串。"""
    hits = search(query, k=k)
    if not hits:
        return ""
    lines = [f"[{a['id']}|{a['confidence'] or '?'}|{a['source_label'] or '?'}] {a['knowledge']}" for a in hits]
    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[:max_chars] + "…"
    return (
        "【私域操盘知识库】(来源:风物执守·XY 原子,内部参考;引用结论请带原子编号,与你的判断冲突时以实际数据为准)\n"
        + body
    )
