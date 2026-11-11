# -*- coding: utf-8 -*-
"""YouTube 对标报告：摘要构建 / JSON 解析 / 落盘（离线，不联网）。"""

from __future__ import annotations

import asyncio
import json

import pytest

from api.services.youtube import report

ROWS = [
    {
        "comment_id": "c1",
        "parent_comment_id": "",
        "channel": "LiamOttley",
        "video_id": "v1",
        "video_title": "AI Agents Tutorial",
        "content": "How do I get started with this tool?",
        "like_count": "120",
        "user_id": "u1",
    },
    {
        "comment_id": "c2",
        "parent_comment_id": "c1",
        "channel": "LiamOttley",
        "video_id": "v1",
        "video_title": "AI Agents Tutorial",
        "content": "so true, needed this",
        "like_count": "9",
        "user_id": "u2",
    },
    {
        "comment_id": "c3",
        "parent_comment_id": "",
        "channel": "ImanGadzhi",
        "video_id": "v2",
        "video_title": "Make Money With AI",
        "content": "teach me please mentor",
        "like_count": "5000",
        "user_id": "u3",
    },
]


def test_build_summary_counts_and_samples():
    text = report.build_summary(ROWS, max_videos=2, sample_per_video=2)
    assert "评论总数:3" in text
    assert "涉及频道:2" in text
    assert "独立作者:3" in text
    assert "LiamOttley" in text and "ImanGadzhi" in text
    assert "How do I get started" in text
    # 高赞优先
    assert text.index("teach me please mentor") >= 0


def test_signal_classification():
    assert report._signal("How do I start?") == "求方法"
    assert report._signal("what tool is this") == "求工具"
    assert report._signal("teach me please mentor") == "求带"
    assert report._signal("random thought") == "其他"


def test_build_summary_empty():
    assert report.build_summary([]) == "（没有评论）"


def test_analyze_parses_and_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(report, "REPORTS_FILE", tmp_path / "reports.json")

    payload = {
        "audience": "想用 AI 赚钱的新手",
        "pain_themes": [{"theme": "不知道从哪开始", "evidence": "how do I", "heat": "高"}],
        "reply_opportunities": [{"target": "求工具", "why": "可给具体路径", "example": "what tool"}],
        "topic_hints": [{"title": "AI Agent 入门三步", "signal": "how do I", "score": 9}],
        "dos": ["先做一条入门"],
        "carry_over": "",
    }

    async def fake_complete(messages, **kwargs):
        assert "对标创作者" in messages[0]["content"]
        assert "YouTube" in messages[1]["content"]
        return json.dumps(payload, ensure_ascii=False)

    result = asyncio.run(
        report.analyze(ROWS, scope="YouTube 对标 LiamOttley", complete_fn=fake_complete)
    )
    assert result["total_comments"] == 3
    assert result["total_videos"] == 2
    assert result["audience"] == "想用 AI 赚钱的新手"
    assert result["pain_themes"][0]["heat"] == "高"
    assert result["channels"]["ImanGadzhi"] == 1

    saved = json.loads((tmp_path / "reports.json").read_text(encoding="utf-8"))
    assert saved[-1]["id"] == result["id"]
    assert saved[-1]["scope"].startswith("YouTube")


def test_analyze_keeps_raw_when_json_broken(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(report, "REPORTS_FILE", tmp_path / "reports.json")

    async def bad(messages, **kwargs):
        return "抱歉，我无法完成"

    result = asyncio.run(report.analyze(ROWS, scope="YouTube 对标 X", complete_fn=bad))
    assert result["audience"] == ""
    assert result["raw"].startswith("抱歉")


def test_analyze_rejects_empty():
    with pytest.raises(ValueError):
        asyncio.run(report.analyze([], scope="YouTube 对标 X"))


def test_previous_digest_only_youtube(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(report, "REPORTS_FILE", tmp_path / "reports.json")
    report.save_reports(
        [
            {"scope": "2026-10-21", "audience": "B站人群", "pain_themes": [], "topic_hints": []},
            {"scope": "YouTube 对标 A", "audience": "YT 人群", "pain_themes": [{"theme": "t"}], "topic_hints": []},
        ]
    )
    digest = report.previous_digest()
    assert "YT 人群" in digest
    assert "B站人群" not in digest
