# -*- coding: utf-8 -*-
"""统一 JSON 提取：覆盖模型的各种坏输出。

审计（2026-11-11）：项目里原有 6+ 份手写提取器，对同一份输出的行为不同；
最糟的是贪婪正则 `\\{.*\\}`，遇到「先给一个示例 JSON，再给真正的 JSON」
会从第一个 `{` 切到最后一个 `}`，拼出一段非法字符串。
"""

from __future__ import annotations

import json

import pytest

from api.services.llm_json import (
    JsonExtractionError,
    extract_json_list,
    extract_json_object,
    extract_json_object_or_raise,
)


def test_plain_object():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_object_with_surrounding_prose():
    text = '好的，这是结果：\n{"title": "标题", "body": "正文"}\n希望有帮助。'
    assert extract_json_object(text) == {"title": "标题", "body": "正文"}


def test_fenced_json_block():
    text = '```json\n{"ok": true}\n```'
    assert extract_json_object(text) == {"ok": True}


def test_fenced_block_without_language():
    text = "```\n{\"ok\": true}\n```"
    assert extract_json_object(text) == {"ok": True}


def test_nested_object_is_not_truncated():
    payload = {"a": {"b": {"c": [1, 2, 3]}}, "d": "x"}
    assert extract_json_object(json.dumps(payload)) == payload


def test_greedy_regex_would_have_failed_here():
    """两个对象相邻时，贪婪正则会拼出非法 JSON；配平扫描不会。"""
    text = '示例：{"demo": 1}\n真正结果：{"real": 2}'
    assert extract_json_object(text) == {"demo": 1}

    # 对照：旧实现的行为
    import re

    match = re.search(r"\{.*\}", text, re.S)
    assert match is not None
    with pytest.raises(json.JSONDecodeError):
        json.loads(match.group(0))


def test_braces_inside_strings_do_not_break_balance():
    text = '{"template": "use {name} here", "ok": true}'
    assert extract_json_object(text) == {"template": "use {name} here", "ok": True}


def test_escaped_quotes_inside_strings():
    text = '{"quote": "he said \\"hi\\""}'
    assert extract_json_object(text) == {"quote": 'he said "hi"'}


def test_truncated_output_is_repaired():
    """模型被 max_tokens 截断时，尽量救回已生成的字段。"""
    text = '{"title": "标题", "body": "正文写到一半'
    parsed = extract_json_object(text)
    assert parsed is not None
    assert parsed["title"] == "标题"


def test_truncated_with_unclosed_nesting():
    text = '{"a": 1, "nested": {"b": [1, 2'
    parsed = extract_json_object(text)
    assert parsed is not None
    assert parsed["a"] == 1


def test_returns_none_or_default_for_garbage():
    assert extract_json_object("完全没有 JSON") is None
    assert extract_json_object("") is None
    assert extract_json_object(None) is None
    assert extract_json_object("垃圾", default={"fallback": True}) == {"fallback": True}


def test_array_payload_is_not_returned_as_object():
    assert extract_json_object("[1, 2, 3]") is None


def test_raise_variant():
    assert extract_json_object_or_raise('{"a": 1}') == {"a": 1}
    with pytest.raises(JsonExtractionError):
        extract_json_object_or_raise("不是 JSON")


def test_extract_json_list():
    assert extract_json_list('[{"a": 1}]') == [{"a": 1}]
    assert extract_json_list('结果如下：\n[1, 2, 3]\n完') == [1, 2, 3]
    assert extract_json_list("没有数组") is None


def test_report_parser_uses_shared_implementation():
    from api.services.youtube import report
    assert report._extract_json('{"first": 1}\n{"second": 2}') == {"first": 1}
