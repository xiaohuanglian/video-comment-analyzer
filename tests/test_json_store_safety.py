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

# ---------------------------------------------------------------------------
# 并发不丢写
# ---------------------------------------------------------------------------




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




# ---------------------------------------------------------------------------
# 损坏不清空
# ---------------------------------------------------------------------------






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
