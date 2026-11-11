# -*- coding: utf-8 -*-
"""从 LLM 输出里提取 JSON 对象的唯一实现。

为什么要有它（2026-11-11 审计）：
项目里至少有 6 份手写的 `_extract_json` / `_parse_json_object`：

- `routers/topics.py`（正则 `\\{.*\\}`，最贪婪，嵌套对象会切错位置）
- `services/creator/title_lab.py`（先剥 code fence，再取首尾花括号）
- `services/youtube/report.py`（同上，几乎逐字重复）
- `services/style/distill.py`（用 ```json 代码块优先，再取首尾花括号）
- `services/content_quality.py`（先整体 loads，失败再正则）
- `services/outreach/reply_automation.py`（正则 + dict 检查）

它们对「模型多输出一句解释」「用 ```json 包起来」「输出被 max_tokens 截断」
的容忍度各不相同，于是同一个模型的同一种坏习惯，在不同功能里表现不一：
有的静默降级，有的抛错，有的解析出**错的**对象（贪婪正则跨越多个 JSON）。

这里给一份统一实现，策略从宽到严逐级尝试：
1. 整体就是 JSON
2. ```json 代码围栏里的内容
3. 第一个 `{` 到最后一个 `}`（配平扫描，不会跨对象乱切）
4. 截断修复：补齐未闭合的括号与引号（模型被 max_tokens 截断时很常见）
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.+?)(?:```|$)", re.S)
_DECODER = json.JSONDecoder()


class JsonExtractionError(ValueError):
    """输出里找不到可解析的 JSON 对象。"""


def _balanced_slice(text: str, start: int) -> Optional[str]:
    """从 `start` 处的 `{` 开始，按括号配平切出第一个完整对象。"""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _repair_truncated(text: str, start: int) -> Optional[str]:
    """尽力修复被截断的 JSON：补引号、补右括号。"""
    chunk = text[start:]
    in_string = False
    escaped = False
    stack: list[str] = []
    for char in chunk:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]" and stack:
            stack.pop()

    fixed = chunk
    if in_string:
        fixed += '"'
    # 去掉结尾悬空的逗号/冒号，否则补括号也解析不了
    fixed = re.sub(r"[,:]\s*$", "", fixed.rstrip())
    for opener in reversed(stack):
        fixed += "}" if opener == "{" else "]"
    return fixed


def _try_loads(candidate: str) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def extract_json_object(text: str, *, default: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """从模型输出里提取一个 JSON 对象；失败返回 `default`（默认 None）。"""
    if not text or not str(text).strip():
        return default
    raw = str(text).strip()

    # 1) 整体就是 JSON
    direct = _try_loads(raw)
    if direct is not None:
        return direct

    # 2) 代码围栏
    for match in _FENCE.finditer(raw):
        body = match.group(1).strip()
        parsed = _try_loads(body)
        if parsed is not None:
            return parsed
        start = body.find("{")
        if start >= 0:
            sliced = _balanced_slice(body, start)
            if sliced:
                parsed = _try_loads(sliced)
                if parsed is not None:
                    return parsed

    # 3) 配平扫描：正常输出里取第一个完整对象
    start = raw.find("{")
    if start >= 0:
        sliced = _balanced_slice(raw, start)
        if sliced:
            parsed = _try_loads(sliced)
            if parsed is not None:
                return parsed

        # 4) 截断修复
        repaired = _repair_truncated(raw, start)
        if repaired:
            parsed = _try_loads(repaired)
            if parsed is not None:
                return parsed

    return default


def extract_json_object_or_raise(text: str) -> dict[str, Any]:
    """同上，但失败抛 JsonExtractionError（需要明确报错的调用方用这个）。"""
    data = extract_json_object(text)
    if data is None:
        raise JsonExtractionError("模型输出里没有可解析的 JSON 对象")
    return data


def extract_json_list(text: str, *, default: Optional[list[Any]] = None) -> Optional[list[Any]]:
    """提取 JSON 数组（部分接口要求模型直接返回列表）。"""
    if not text or not str(text).strip():
        return default
    raw = str(text).strip()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    start = raw.find("[")
    if start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(raw)):
            char = raw[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(raw[start : index + 1])
                    except (json.JSONDecodeError, ValueError):
                        return default
                    return data if isinstance(data, list) else default
    return default
