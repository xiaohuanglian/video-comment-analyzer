# -*- coding: utf-8 -*-
"""JSON 存储的三条底线：并发不丢写、损坏不清空、写入原子。

背景（2026-11-11 审计）：项目里有 4 套各自实现的 JSON 持久化，全部踩了
同样的坑。这组测试把修好的行为钉死：
- 20 并发 `add_many` 过去最终只落 3 条；
- 文件被截断过去 `load()` 返回 `[]`，下一次保存就把历史抹掉。
"""

from __future__ import annotations

import json
import threading

import pytest

from api.services.json_store import JsonListStore, JsonStoreCorruption
from api.services.outreach.reply_automation import AutomationStore
from api.services.topics import store as topic_store

# ---------------------------------------------------------------------------
# 并发不丢写
# ---------------------------------------------------------------------------


def test_concurrent_add_many_keeps_every_topic(tmp_path, monkeypatch):
    monkeypatch.setattr(topic_store, "TOPICS_DIR", tmp_path)
    monkeypatch.setattr(topic_store, "TOPICS_FILE", tmp_path / "topics.json")
    topic_store.save([])

    # 标题必须彼此不像：选题库有 bigram 去重，`并发选题1/2/3` 会被判为
    # 「换汤不换药」而合并——那是去重的正确行为，不是丢写。
    titles = [
        "用脚本批量导出评论到表格", "如何判断评论区是不是刷的", "新手做短视频先学什么",
        "剪辑软件到底选哪个好", "涨粉慢的真正原因", "这类选题为什么没人看",
        "选题会该怎么开", "把长视频拆成短片的方法", "评论区的真实需求怎么找",
        "数据回填的正确姿势", "发布后多久复盘合适", "账号定位怎么定",
        "封面设计有哪些坑", "标题党还能用吗", "冷启动第一周该干什么",
        "为什么播放量高但不涨粉", "内容日历怎么排", "怎么把采访做成选题",
        "对标账号该怎么拆", "复盘时该看哪几个指标",
    ]

    def add(index: int) -> None:
        topic_store.add_many(
            [topic_store.make_topic(
                title=titles[index],
                source=topic_store.SOURCE_EVENT,
                origin={"kind": "test"},
            )]
        )

    threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(topic_store.load()) == 20


def test_concurrent_automation_counter_is_not_lost(tmp_path):
    path = tmp_path / "auto.json"
    AutomationStore(path=path, platform="bili").save()

    # 多个实例各自读盘、各自落盘：CLI 进程与 Web 进程共用同一个
    # bili_reply.json 时就是这个形状。计数必须走 bump_stat()，
    # 它会把「我加了 1」登记为增量，落盘时叠加到磁盘最新值上。
    def bump() -> None:
        state = AutomationStore(path=path, platform="bili")
        state.bump_stat("sent_total", 1)
        state.save()

    threads = [threading.Thread(target=bump) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert json.loads(path.read_text(encoding="utf-8"))["stats"]["sent_total"] == 20


def test_concurrent_publish_records_are_not_lost(tmp_path, monkeypatch):
    from api.services import publish_log

    monkeypatch.setattr(publish_log, "PUBLISH_DIR", tmp_path)
    monkeypatch.setattr(publish_log, "RECORDS_FILE", tmp_path / "records.json")

    def create(index: int) -> None:
        publish_log.create_record({"title": f"作品{index}", "platform": "xhs"})

    threads = [threading.Thread(target=create, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(publish_log.list_records()) == 20


# ---------------------------------------------------------------------------
# 损坏不清空
# ---------------------------------------------------------------------------


def test_corrupt_topic_file_raises_and_preserves_bytes(tmp_path, monkeypatch):
    path = tmp_path / "topics.json"
    broken = '[{"id":"a","title":"A"}'
    path.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(topic_store, "TOPICS_DIR", tmp_path)
    monkeypatch.setattr(topic_store, "TOPICS_FILE", path)

    with pytest.raises(JsonStoreCorruption) as excinfo:
        topic_store.load()

    # 现场必须留着，且不能已经被清空
    backup = excinfo.value.backup
    assert backup is not None and backup.exists()
    assert backup.read_text(encoding="utf-8") == broken


def test_corrupt_topic_file_blocks_write_that_would_wipe_history(tmp_path, monkeypatch):
    path = tmp_path / "topics.json"
    path.write_text("not-json-at-all", encoding="utf-8")
    monkeypatch.setattr(topic_store, "TOPICS_DIR", tmp_path)
    monkeypatch.setattr(topic_store, "TOPICS_FILE", path)

    with pytest.raises(JsonStoreCorruption):
        topic_store.add_many(
            [topic_store.make_topic(
                title="新选题", source=topic_store.SOURCE_EVENT, origin={"kind": "test"}
            )]
        )

    # 原文件（或其备份）内容仍在，没有被 [] 覆盖
    survivors = [path] + list(tmp_path.glob("topics.json.corrupt-*"))
    assert any(p.exists() and "not-json-at-all" in p.read_text(encoding="utf-8") for p in survivors)


def test_corrupt_automation_state_does_not_lose_processed_ids(tmp_path):
    """最不能接受的场景：已回复用户名单被静默清空 → 同一批人被重复回复。"""
    path = tmp_path / "auto.json"
    path.write_text(
        '{"processed_comment_ids":["c1","c2"],"items":[]', encoding="utf-8"
    )

    with pytest.raises(JsonStoreCorruption):
        AutomationStore(path=path, platform="bili")

    backups = list(tmp_path.glob("auto.json.corrupt-*"))
    assert backups, "损坏文件必须留档"
    assert "c1" in backups[0].read_text(encoding="utf-8")


def test_missing_file_is_not_treated_as_corruption(tmp_path, monkeypatch):
    """「还没有数据」和「文件坏了」是两件事，前者要能正常初始化。"""
    monkeypatch.setattr(topic_store, "TOPICS_DIR", tmp_path)
    monkeypatch.setattr(topic_store, "TOPICS_FILE", tmp_path / "topics.json")
    assert topic_store.load() == []

    state = AutomationStore(path=tmp_path / "auto.json", platform="bili")
    assert state.items == []


def test_tolerate_corruption_opt_in_returns_default(tmp_path):
    """旁路读（如费用台账展示）可以显式降级，但不能是默认行为。"""
    path = tmp_path / "ledger.json"
    path.write_text("{broken", encoding="utf-8")
    store = JsonListStore(path)
    # 降级读会把坏文件移走留档，所以「再读一次」拿到的是空数据而非再次抛错。
    assert store.load(tolerate_corruption=True) == []
    assert list(tmp_path.glob("ledger.json.corrupt-*")), "降级也要留档"

    path2 = tmp_path / "ledger2.json"
    path2.write_text("{broken", encoding="utf-8")
    with pytest.raises(JsonStoreCorruption):
        JsonListStore(path2).load()


# ---------------------------------------------------------------------------
# 原子写
# ---------------------------------------------------------------------------


def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "x.json"
    store = JsonListStore(target)
    store.save([{"id": "1"}])
    store.save([{"id": "1"}, {"id": "2"}])
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "x.json"]
    assert leftovers == []
    assert len(json.loads(target.read_text(encoding="utf-8"))) == 2


def test_max_items_truncation_is_single_defined_place(tmp_path, monkeypatch):
    """容量上限原先 router(300) 与 store(400) 各写一套，会静默砍数据。"""
    monkeypatch.setattr(topic_store, "TOPICS_DIR", tmp_path)
    monkeypatch.setattr(topic_store, "TOPICS_FILE", tmp_path / "topics.json")
    topic_store.save(
        [
            topic_store.make_topic(
                title=f"T{i}", source=topic_store.SOURCE_EVENT, origin={"kind": "test"}
            )
            for i in range(450)
        ]
    )
    assert len(topic_store.load()) == topic_store._MAX_ITEMS
