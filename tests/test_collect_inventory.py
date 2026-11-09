# -*- coding: utf-8 -*-
"""采集页「本地已采数据」盘点 + 按日期分析对 xhs 行的归一。"""

import json

from api.routers import comments as comments_router
from api.services import collect_inventory


def _write_jsonl(path, rows):
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


class TestLocalDataInventory:
    def test_manual_dir_mixes_bili_and_xhs_by_row_shape(self, tmp_path, monkeypatch):
        manual = tmp_path / "manual"
        manual.mkdir()
        # 同一天:B 站批 + 小红书批混在手动目录,靠行形状区分
        _write_jsonl(
            manual / "contents_2026-11-09.jsonl",
            [
                {"video_id": "BV1", "title": "B站视频甲"},
                {"note_id": "N1", "title": "小红书笔记乙"},
            ],
        )
        _write_jsonl(
            manual / "comments_2026-11-09.jsonl",
            [
                {"comment_id": "c1", "video_id": "BV1", "content": "a"},
                {"comment_id": "c2", "note_id": "N1", "content": "b"},
            ],
        )
        auto_bili = tmp_path / "auto_bili"
        auto_bili.mkdir()
        _write_jsonl(
            auto_bili / "comments_2026-10-26.jsonl",
            [{"comment_id": "c3", "video_id": "BV2", "content": "x"}],
        )
        auto_xhs = tmp_path / "auto_xhs"
        auto_xhs.mkdir()
        _write_jsonl(
            auto_xhs / "contents_2026-11-09.jsonl",
            [{"note_id": "N2", "title": "自动化小红书笔记"}],
        )
        _write_jsonl(
            auto_xhs / "comments_2026-11-09.jsonl",
            [{"comment_id": "c4", "note_id": "N2", "content": "y"}],
        )

        monkeypatch.setattr(
            collect_inventory,
            "SOURCES",
            [(manual, "manual"), (auto_bili, "automation"), (auto_xhs, "automation")],
        )
        result = collect_inventory.local_data_inventory()

        by_key = {(b["date"], b["source"], b["platform"]): b for b in result["batches"]}
        # 手动目录同一天混采两平台 → 拆成两个批次,谁的数据算谁的
        manual_bili = by_key[("2026-11-09", "manual", "bili")]
        assert manual_bili["comments"] == 1
        assert manual_bili["contents"] == 1
        manual_xhs = by_key[("2026-11-09", "manual", "xhs")]
        assert manual_xhs["comments"] == 1
        assert manual_xhs["contents"] == 1
        assert manual_xhs["titles"] == ["小红书笔记乙"]
        assert ("2026-10-26", "automation", "bili") in by_key
        xhs_auto = by_key[("2026-11-09", "automation", "xhs")]
        assert xhs_auto["comments"] == 1
        assert xhs_auto["contents"] == 1
        assert xhs_auto["titles"] == ["自动化小红书笔记"]

        agg = result["platforms"]
        assert agg["xhs"]["comments"] == 2
        assert agg["bili"]["comments"] == 2

    def test_u2028_in_content_does_not_split_lines(self, tmp_path, monkeypatch):
        manual = tmp_path / "manual"
        manual.mkdir()
        # 正文含 U+2028:splitlines 会把它当换行撕开,split("\n") 不会
        _write_jsonl(
            manual / "comments_2026-11-09.jsonl",
            [{"comment_id": "c1", "note_id": "N1", "content": "前段\u2028后段"}],
        )
        monkeypatch.setattr(collect_inventory, "SOURCES", [(manual, "manual")])
        result = collect_inventory.local_data_inventory()
        assert result["batches"][0]["comments"] == 1
        assert result["batches"][0]["platform"] == "xhs"

    def test_empty_and_missing_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            collect_inventory,
            "SOURCES",
            [(tmp_path / "nope", "manual"), (tmp_path / "empty", "automation")],
        )
        (tmp_path / "empty").mkdir()
        result = collect_inventory.local_data_inventory()
        assert result["batches"] == []
        assert result["platforms"] == {}


class TestLoadRowsXhsNormalization:
    def test_xhs_batch_groups_by_note_id(self, tmp_path, monkeypatch):
        bulk = tmp_path / "bulk"
        bulk.mkdir()
        _write_jsonl(
            bulk / "contents_2026-11-09.jsonl",
            [{"note_id": "N1", "title": "修图就像喝水一样简单"}],
        )
        _write_jsonl(
            bulk / "comments_2026-11-09.jsonl",
            [
                {"comment_id": "c1", "note_id": "N1", "content": "这是哪个AI网站", "like_count": 3},
                {"comment_id": "c2", "note_id": "N1", "content": "要会员吗", "like_count": 1},
            ],
        )
        monkeypatch.setattr(comments_router, "BULK_COMMENT_DIR", bulk)
        monkeypatch.setattr(comments_router, "COMMENT_DIR", tmp_path / "no-auto")

        rows, video_map, scope = comments_router._load_rows("2026-11-09")

        assert scope == "2026-11-09"
        assert len(rows) == 2
        # xhs 行归一出 video_id,与笔记表(note_id 作 key)能对上
        assert all(r["video_id"] == "N1" for r in rows)
        assert "N1" in video_map
        assert video_map["N1"]["title"] == "修图就像喝水一样简单"

    def test_bili_rows_unchanged(self, tmp_path, monkeypatch):
        bulk = tmp_path / "bulk"
        bulk.mkdir()
        _write_jsonl(
            bulk / "contents_2026-10-27.jsonl",
            [{"video_id": "BV1", "title": "B站视频"}],
        )
        _write_jsonl(
            bulk / "comments_2026-10-27.jsonl",
            [{"comment_id": "c1", "video_id": "BV1", "content": "好"}],
        )
        monkeypatch.setattr(comments_router, "BULK_COMMENT_DIR", bulk)
        monkeypatch.setattr(comments_router, "COMMENT_DIR", tmp_path / "no-auto")

        rows, video_map, _ = comments_router._load_rows("2026-10-27")

        assert rows[0]["video_id"] == "BV1"
        assert "BV1" in video_map
