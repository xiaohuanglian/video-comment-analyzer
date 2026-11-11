# -*- coding: utf-8 -*-
"""YouTube 评论采集：目标发现 / 行转换 / 合并 / 失败隔离（全部离线）。"""

from __future__ import annotations

import csv
import json

import pytest

from api.services.youtube import comments

# ---------------------------------------------------------------------------
# 目标发现
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_dirs(tmp_path, monkeypatch):
    bench = tmp_path / "bench"
    creators = tmp_path / "creators"
    bench.mkdir()
    (creators / "liamottley" / "raw").mkdir(parents=True)
    (creators / "_tmp" / "raw").mkdir(parents=True)
    monkeypatch.setattr(comments, "BENCH_DIR", bench)
    monkeypatch.setattr(comments, "CREATORS_DIR", creators)
    return bench, creators


def test_list_channels_reads_bench_and_creators(data_dirs):
    bench, creators = data_dirs
    (bench / "SomeOne.json").write_text(
        json.dumps({"videos": [{"id": "aaa", "title": "A", "views": 100}, {"id": "bbb", "title": "B", "views": 900}]}),
        encoding="utf-8",
    )
    (creators / "liamottley" / "raw" / "ccc.json").write_text(
        json.dumps({"video_id": "ccc", "title": "C", "views": 50}), encoding="utf-8"
    )
    (creators / "_tmp" / "raw" / "zzz.json").write_text(
        json.dumps({"video_id": "zzz", "title": "hidden"}), encoding="utf-8"
    )

    channels = comments.list_channels()
    names = {c.name for c in channels}
    assert names == {"SomeOne", "liamottley"}
    liam = next(c for c in channels if c.name == "liamottley")
    assert [v["id"] for v in liam.videos] == ["ccc"]


def test_select_videos_orders_by_views(data_dirs):
    bench, _ = data_dirs
    (bench / "X.json").write_text(
        json.dumps({"videos": [{"id": "low", "views": 1}, {"id": "highest", "views": 999}, {"id": "mid", "views": 10}]}),
        encoding="utf-8",
    )
    channel = comments.list_channels()[0]
    picked = comments.select_videos(channel, limit=2)
    assert [v["id"] for v in picked] == ["highest", "mid"]


def test_list_targets_shape(data_dirs):
    bench, _ = data_dirs
    (bench / "X.json").write_text(json.dumps({"videos": [{"id": "a", "views": 5}]}), encoding="utf-8")
    targets = comments.list_targets(limit=1)
    assert targets[0]["channel"] == "X"
    assert targets[0]["selected"][0]["id"] == "a"
    assert targets[0]["video_count"] == 1


# ---------------------------------------------------------------------------
# 行转换
# ---------------------------------------------------------------------------

def _fake_extract(payload):
    def _inner(url, *, max_comments, max_parents, max_replies, sort):
        assert isinstance(max_comments, int)
        return payload

    return _inner


def test_fetch_maps_fields_and_parent():
    payload = {
        "title": "Real Title",
        "view_count": 1234,
        "webpage_url": "https://www.youtube.com/watch?v=vid1",
        "comments": [
            {
                "id": "c1",
                "parent": "root",
                "text": "主评论",
                "like_count": 7,
                "author": "@alice",
                "author_id": "UC1",
                "timestamp": 1700000000,
                "reply_count": 2,
                "author_is_uploader": False,
                "author_url": "https://www.youtube.com/@alice",
            },
            {
                "id": "c2",
                "parent": "c1",
                "text": "回复",
                "like_count": 0,
                "author": "@bob",
                "author_id": "UC2",
                "timestamp": 1700000100,
                "author_is_uploader": True,
            },
        ],
    }
    out = comments.fetch_video_comments(
        {"id": "vid1", "title": "", "views": 0, "url": "u"}, channel="ch", extract_fn=_fake_extract(payload)
    )
    assert out["error"] == ""
    rows = out["rows"]
    assert len(rows) == 2
    assert rows[0]["parent_comment_id"] == ""
    assert rows[0]["create_time"] == 1700000000000
    assert rows[0]["video_title"] == "Real Title"
    assert rows[0]["channel"] == "ch"
    assert rows[1]["parent_comment_id"] == "c1"
    assert rows[1]["is_uploader"] is True
    assert rows[0]["sub_comment_count"] == 2


def test_fetch_isolates_errors():
    def boom(url, **kwargs):
        raise RuntimeError("429 Too Many Requests")

    out = comments.fetch_video_comments({"id": "v", "url": "u"}, extract_fn=boom)
    assert out["rows"] == []
    assert "429" in out["error"]


def test_fetch_without_comments_returns_empty():
    out = comments.fetch_video_comments({"id": "v", "url": "u"}, extract_fn=_fake_extract({"comments": None}))
    assert out["rows"] == [] and out["error"] == ""


# ---------------------------------------------------------------------------
# 落盘与合并
# ---------------------------------------------------------------------------

def test_merge_dedupes_by_comment_id(tmp_path):
    path = tmp_path / "all.csv"
    first = [{"comment_id": "a", "content": "1"}, {"comment_id": "b", "content": "2"}]
    comments.merge_into(path, first)
    stats = comments.merge_into(path, [{"comment_id": "b", "content": "2-updated"}, {"comment_id": "c", "content": "3"}])
    assert stats == {"before": 2, "after": 3, "added": 1}

    rows = comments.read_csv(path)
    assert rows["b"]["content"] == "2-updated"
    with path.open(encoding="utf-8-sig") as fh:
        header = next(csv.reader(fh))
    assert header[:5] == ["comment_id", "parent_comment_id", "create_time", "video_id", "content"]


def test_collect_channel_writes_csv_and_reports(tmp_path, monkeypatch, data_dirs):
    monkeypatch.setattr(comments, "OUT_DIR", tmp_path / "out")
    channel = comments.Channel(
        name="chan",
        source="bench",
        videos=[
            {"id": "v1", "title": "one", "views": 10, "url": "u1"},
            {"id": "v2", "title": "two", "views": 20, "url": "u2"},
        ],
    )
    events = []

    def fake_extract(url, **kwargs):
        return {"title": url, "comments": [{"id": f"id-{url}", "parent": "root", "text": "hi", "timestamp": 1}]}

    summary = comments.collect_channel(
        channel,
        limit=2,
        sleep_seconds=0,
        extract_fn=fake_extract,
        progress=events.append,
    )
    assert summary["fetched"] == 2
    assert summary["total_in_csv"] == 2
    assert summary["errors"] == []
    assert len(events) == 2
    assert (tmp_path / "out" / "chan" / "all.csv").is_file()


def test_collect_channel_keeps_going_after_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(comments, "OUT_DIR", tmp_path / "out")
    channel = comments.Channel(name="c2", source="bench", videos=[{"id": "bad", "url": "bad"}, {"id": "ok", "url": "ok"}])
    calls = {"n": 0}

    def flaky(url, **kwargs):
        calls["n"] += 1
        if url == "bad":
            raise RuntimeError("blocked")
        return {"comments": [{"id": "x", "parent": "root", "text": "ok", "timestamp": 1}]}

    summary = comments.collect_channel(channel, limit=2, sleep_seconds=0, extract_fn=flaky)
    assert summary["total_in_csv"] == 1
    assert len(summary["errors"]) == 1
    assert calls["n"] == 2


def test_channel_csv_path_sanitizes_name(tmp_path, monkeypatch):
    monkeypatch.setattr(comments, "OUT_DIR", tmp_path)
    path = comments.channel_csv_path("a/b c")
    assert path.parent.name == "a-b-c"
    assert path.name == "all.csv"


def test_content_newlines_are_collapsed():
    """CSV 里保留换行会让「记录数」按物理行算错，采集时统一压成空格。"""
    payload = {"comments": [{"id": "c", "parent": "root", "text": "line1\n\n  line2 \nline3", "timestamp": 1}]}
    out = comments.fetch_video_comments({"id": "v", "url": "u"}, extract_fn=_fake_extract(payload))
    assert out["rows"][0]["content"] == "line1 line2 line3"


def test_limits_derive_from_total_comments():
    """只给总条数时，主评论数必须跟随，否则实际只会拿到「主评论数+少量回复」。"""
    captured = {}

    def fake(url, *, max_comments, max_parents, max_replies, sort):
        captured.update(max_comments=max_comments, max_parents=max_parents, max_replies=max_replies)
        return {"comments": []}

    comments.fetch_video_comments({"id": "v", "url": "u"}, max_comments=500, extract_fn=fake)
    assert captured == {"max_comments": 500, "max_parents": 500, "max_replies": 50}


def test_explicit_limits_win_over_derivation():
    captured = {}

    def fake(url, *, max_comments, max_parents, max_replies, sort):
        captured.update(parents=max_parents, replies=max_replies)
        return {"comments": []}

    comments.fetch_video_comments(
        {"id": "v", "url": "u"}, max_comments=800, max_parents=300, max_replies=20, extract_fn=fake
    )
    assert captured == {"parents": 300, "replies": 20}
