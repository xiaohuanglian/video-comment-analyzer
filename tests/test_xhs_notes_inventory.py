# -*- coding: utf-8 -*-
"""采集页「小红书笔记列表」：清单解析 + 接口契约。

这批数据是 scripts/xhs_keyword_notes.py 写的 notes.csv（只有笔记、没有评论），
和评论文件不是一回事，所以单独锁住：字段形状、排序、过滤、批次选择、限量。
"""

import csv
import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services import xhs_notes_inventory as inv

_COLUMNS = [
    "keyword",
    "note_id",
    "title",
    "author",
    "author_id",
    "note_type",
    "liked_count",
    "collected_count",
    "comment_count",
    "xsec_token",
    "url",
    "cover_url",
]


def _write_batch(root, name, rows, created_at="2026-11-11 20:01:59"):
    batch = root / name
    batch.mkdir(parents=True)
    with open(batch / "notes.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in _COLUMNS})
    (batch / "manifest.json").write_text(
        json.dumps({"created_at": created_at}, ensure_ascii=False), encoding="utf-8"
    )
    return batch


@pytest.fixture()
def notes_root(tmp_path, monkeypatch):
    root = tmp_path / "xhs_search"
    root.mkdir()
    monkeypatch.setattr(inv, "NOTES_ROOT", root)
    return root


_ROWS = [
    {
        "keyword": "信息过载",
        "note_id": "n1",
        "title": "执行力差是因为你陷入了信息过载",
        "author": "桃子 Cool",
        "note_type": "normal",
        "liked_count": "24754",
        "collected_count": "8000",
        "comment_count": "109",
        "url": "https://www.xiaohongshu.com/explore/n1?xsec_token=t1",
    },
    {
        "keyword": "戒短视频",
        "note_id": "n2",
        "title": "亲测45天，大脑真的能被重新训练",
        "author": "老金的开源人生",
        "note_type": "video",
        "liked_count": "8152",
        "collected_count": "3001",
        "comment_count": "323",
        "url": "https://www.xiaohongshu.com/explore/n2?xsec_token=t2",
    },
    {
        "keyword": "信息过载",
        "note_id": "n3",
        "title": "别再看和你无关的信息",
        "author": "心理师 bestta",
        "note_type": "normal",
        "liked_count": "32681",
        "collected_count": "9000",
        "comment_count": "479",
        "url": "https://www.xiaohongshu.com/explore/n3?xsec_token=t3",
    },
]


class TestInventory:
    def test_lists_batches_newest_first_with_totals(self, notes_root):
        _write_batch(notes_root, "20261111_190000", _ROWS[:1], created_at="2026-11-11 19:00:00")
        _write_batch(notes_root, "20261111_200159", _ROWS, created_at="2026-11-11 20:01:59")
        batches = inv.list_batches()
        assert [b["batch"] for b in batches][0] == "20261111_200159"
        assert {b["batch"]: b["total"] for b in batches} == {
            "20261111_190000": 1,
            "20261111_200159": 3,
        }
        assert batches[0]["created_at"] == "2026-11-11 20:01:59"

    def test_defaults_to_latest_batch_sorted_by_liked(self, notes_root):
        _write_batch(notes_root, "20261111_190000", _ROWS[:1], created_at="2026-11-11 19:00:00")
        _write_batch(notes_root, "20261111_200159", _ROWS, created_at="2026-11-11 20:01:59")
        data = inv.get_notes()
        assert data["batch"] == "20261111_200159"
        assert data["total"] == 3
        assert [r["note_id"] for r in data["items"]] == ["n3", "n1", "n2"]  # 点赞倒序
        first = data["items"][0]
        assert first["liked"] == 32681 and first["collected"] == 9000 and first["comments"] == 479
        assert first["url"].startswith("https://www.xiaohongshu.com/explore/n3")
        assert data["keyword_counts"] == {"信息过载": 2, "戒短视频": 1}

    def test_query_filters_title_author_and_keyword(self, notes_root):
        _write_batch(notes_root, "20261111_200159", _ROWS)
        assert [r["note_id"] for r in inv.get_notes(q="信息过载")["items"]] == ["n3", "n1"]
        assert [r["note_id"] for r in inv.get_notes(q="老金")["items"]] == ["n2"]
        assert inv.get_notes(q="不存在的词")["total"] == 0

    def test_sort_keyword_keeps_csv_order(self, notes_root):
        _write_batch(notes_root, "20261111_200159", _ROWS)
        assert [r["note_id"] for r in inv.get_notes(sort="keyword")["items"]] == ["n1", "n2", "n3"]

    def test_limit_is_clamped_and_paged(self, notes_root):
        _write_batch(notes_root, "20261111_200159", _ROWS)
        assert inv.get_notes(limit=0)["limit"] == 1
        assert inv.get_notes(limit=99999)["limit"] == inv.MAX_LIMIT
        page = inv.get_notes(limit=1, offset=1)
        assert [r["note_id"] for r in page["items"]] == ["n1"]
        assert page["total"] == 3

    def test_unknown_batch_raises(self, notes_root):
        _write_batch(notes_root, "20261111_200159", _ROWS)
        with pytest.raises(KeyError):
            inv.get_notes(batch="20990101_000000")

    def test_empty_root_returns_empty(self, notes_root):
        data = inv.get_notes()
        assert data["batch"] == "" and data["items"] == [] and data["batches"] == []

    def test_rows_without_note_id_are_dropped(self, notes_root):
        _write_batch(notes_root, "20261111_200159", _ROWS + [{"note_id": "", "title": "脏行"}])
        assert inv.get_notes()["total"] == 3

    def test_non_numeric_counts_degrade_to_zero(self, notes_root):
        row = dict(_ROWS[0], note_id="n9", liked_count="1.2万")
        _write_batch(notes_root, "20261111_200159", [row])
        assert inv.get_notes()["items"][0]["liked"] == 0


class TestRoute:
    def test_endpoint_returns_notes(self, notes_root):
        _write_batch(notes_root, "20261111_200159", _ROWS)
        client = TestClient(app)
        r = client.get("/api/crawler/xhs-notes")
        assert r.status_code == 200
        body = r.json()
        assert body["batch"] == "20261111_200159" and body["total"] == 3
        assert body["items"][0]["title"] and body["items"][0]["url"]

    def test_endpoint_404_for_unknown_batch(self, notes_root):
        _write_batch(notes_root, "20261111_200159", _ROWS)
        client = TestClient(app)
        r = client.get("/api/crawler/xhs-notes", params={"batch": "nope"})
        assert r.status_code == 404
