# -*- coding: utf-8 -*-
"""Streaming pagination must match the in-memory variant and stay one-pass."""

from __future__ import annotations

from api.services.insight.query_filters import paginate_results, paginate_results_iter


def _rows(n: int) -> list[dict]:
    return [
        {
            "record_id": f"r{i}",
            "analysis": {
                "primary_intent": "question" if i % 2 else "check_in",
                "signals": [],
            },
            "source": {"comment_text": f"评论内容 {i}"},
        }
        for i in range(n)
    ]


def test_stream_pagination_matches_list_pagination():
    rows = _rows(250)
    for page in (1, 2, 3, 4):
        expected = paginate_results(rows, page=page, page_size=100)
        streamed = paginate_results_iter((dict(row) for row in rows), page=page, page_size=100)
        assert streamed["total"] == expected["total"]
        assert [r["record_id"] for r in streamed["items"]] == [
            r["record_id"] for r in expected["items"]
        ]
        assert streamed["page"] == page


def test_stream_pagination_applies_keyword_filter():
    rows = _rows(30)
    streamed = paginate_results_iter(
        (dict(row) for row in rows), page=1, page_size=10, keyword="评论内容 1"
    )
    assert streamed["total"] == 11
    assert len(streamed["items"]) == 10
    assert all("1" in row["source"]["comment_text"] for row in streamed["items"])