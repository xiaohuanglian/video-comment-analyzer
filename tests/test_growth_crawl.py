# -*- coding: utf-8 -*-
"""L2 受控采集：权限、解析、信号转换（网络实采需 VCA_LIVE_CRAWL=1）。"""

import os

import pytest

from api.services.growth import seeds, store
from api.services.growth.crawl_tool import _extract_bvid, csv_to_signals
from api.services.growth.tools import ToolContext, execute_tool


@pytest.fixture()
def product(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    store.upsert_product(seeds.YOUVIBE.model_copy(update={"is_builtin": False}))
    return "youvibe"


def test_bvid_parse():
    assert _extract_bvid("BV1Ls421M7qq") == "BV1Ls421M7qq"
    assert _extract_bvid("https://www.bilibili.com/video/BV14rzQB9EJj/?spm=1") == "BV14rzQB9EJj"
    with pytest.raises(ValueError):
        _extract_bvid("不是视频链接")


def test_l2_grant_required(product):
    ctx = ToolContext(product_id="youvibe", session_id="s1")  # 无授权
    r = execute_tool("crawl_bilibili_comments",
                     {"video": "BV1Ls421M7qq", "reason": "测试"}, ctx, {})
    assert r.status == "denied" and "L2" in r.error
    audits = store.list_audit("youvibe")
    assert audits[-1].status == "denied"  # 未授权不产生采集行为


def test_csv_to_signals_idempotent(tmp_path, product):
    csv_path = tmp_path / "comments_test.csv"
    rows = "comment_id,content,nickname,like_count\nc1,求教程,用户A,5\nc2,这个怎么做的,用户B,3\n"
    csv_path.write_text(rows, encoding="utf-8")
    sigs = csv_to_signals(csv_path, product_id="youvibe", bvid="BVtest01", limit=50)
    assert len(sigs) == 2
    assert sigs[0].signal_type == "raw_comment" and sigs[0].usage_rights == "internal_only"
    assert sigs[0].signal_id == "crawl:BVtest01:c1"
    store.add_signals(sigs)
    # 重复转换幂等
    sigs2 = csv_to_signals(csv_path, product_id="youvibe", bvid="BVtest01", limit=50)
    assert sigs2 == []


@pytest.mark.skipif(os.environ.get("VCA_LIVE_CRAWL") != "1",
                    reason="真实采集需显式开启（会启动浏览器）")
def test_live_crawl_small(product):
    ctx = ToolContext(product_id="youvibe", session_id="s_live",
                      l2_grants=["crawl_bilibili_comments"])
    r = execute_tool("crawl_bilibili_comments",
                     {"video": "BV14rzQB9EJj", "max_comments": 30, "reason": "live smoke"}, ctx, {})
    assert r.status == "ok"
    assert r.data["imported"] > 0
    assert store.list_signals("youvibe")
