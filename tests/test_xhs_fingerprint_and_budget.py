# -*- coding: utf-8 -*-
"""小红书「像个人」的两处约束：请求指纹同源 + 搜索次数预算。

为什么单独一个文件：这两件事都不属于"撞了风控怎么止损"，而属于
**不要主动露出机器人特征**——事故复盘里，指纹自相矛盾（UA 说 Chrome 126、
客户端说 137、Client Hints 说 136 且平台是 Windows）与「40 秒问 12 个
不相关话题」都是比间隔更硬的判定依据。

锁住：
1. UA / sec-ch-ua / sec-ch-ua-platform 三者必须同源，且能从 UA 反推。
2. ``fingerprint_mismatches`` 能抓出旧代码那种手写常量。
3. 搜索有单批上限与日预算，超了在发请求之前就拒绝。
4. ``xhs`` 的 search 档比平台档更慢（搜索是主动搜库，比看已知内容敏感）。
"""

import json
import time

import pytest

import config
from media_platform.xhs.fingerprint import (
    BrowserFingerprint,
    derive_from_user_agent,
    fingerprint_mismatches,
)
from tools import crawl_pacing as cp
from tools import xhs_safety as xs

# ---------------------------------------------------------------------------
# 1. 指纹同源
# ---------------------------------------------------------------------------

_MAC_CHROME_141 = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


def test_derive_from_user_agent_keeps_versions_in_sync():
    """sec-ch-ua 里的版本号必须与 UA 一致——事故就是这里差了三代。"""
    fp = derive_from_user_agent(_MAC_CHROME_141)
    assert 'v="141"' in fp.sec_ch_ua
    assert "137" not in fp.sec_ch_ua
    assert "136" not in fp.sec_ch_ua
    assert fp.sec_ch_ua_platform == '"macOS"'


def test_derive_platform_detection_order():
    """Android UA 里含 "Linux"，必须先判 Android，否则平台头会写成 Linux。"""
    android = derive_from_user_agent(
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36"
    )
    assert android.sec_ch_ua_platform == '"Android"'
    assert android.sec_ch_ua_mobile == "?1"

    windows = derive_from_user_agent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    )
    assert windows.sec_ch_ua_platform == '"Windows"'
    assert windows.sec_ch_ua_mobile == "?0"


def test_unknown_user_agent_does_not_fake_client_hints():
    """反推不出来就不注入 sec-ch-ua：缺头比错头安全。"""
    fp = derive_from_user_agent("SomeWeirdBrowser/1.0")
    assert fp.source == "derived"
    assert fp.sec_ch_ua == ""
    assert "sec-ch-ua" not in fp.headers()
    # 但 UA 本身还是要带上
    assert fp.headers()["user-agent"] == "SomeWeirdBrowser/1.0"


def test_mismatches_catch_the_old_hardcoded_headers():
    """旧代码的头：UA 137 + sec-ch-ua 136 + platform Windows，一次性全抓出来。"""
    fp = derive_from_user_agent(_MAC_CHROME_141)
    bad = {
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
        "sec-ch-ua-platform": '"Windows"',
    }
    problems = fingerprint_mismatches(bad, fp)
    assert any("user-agent" in p for p in problems)
    assert any("sec-ch-ua 与浏览器不一致" in p for p in problems)
    assert any("sec-ch-ua-platform" in p for p in problems)


def test_matching_headers_produce_no_complaints():
    fp = derive_from_user_agent(_MAC_CHROME_141)
    assert fingerprint_mismatches(fp.headers(), fp) == []


def test_browser_fingerprint_headers_skip_empty_values():
    fp = BrowserFingerprint(user_agent="UA/1", sec_ch_ua="", sec_ch_ua_platform="")
    headers = fp.headers()
    assert headers["user-agent"] == "UA/1"
    assert "sec-ch-ua" not in headers
    assert "sec-ch-ua-platform" not in headers


# ---------------------------------------------------------------------------
# 2. search 档节奏
# ---------------------------------------------------------------------------


def test_search_kind_is_slower_than_platform_kind():
    """search 是主动搜库，比 detail/feed 敏感：同平台也要更慢。"""
    platform_base, _ = cp.compute_crawl_interval("xhs")
    search_base, _ = cp.compute_crawl_interval("xhs", "search")
    assert search_base > platform_base


def test_search_kind_keys_exist_in_config():
    for (platform, kind), (base_key, jitter_key) in cp._PACING_KINDS.items():
        assert hasattr(config, base_key), f"{platform}/{kind} 缺少 {base_key}"
        assert hasattr(config, jitter_key), f"{platform}/{kind} 缺少 {jitter_key}"


def test_unrelated_kind_does_not_change_pacing():
    """给 bili 传 kind="search" 不该误伤——只有显式登记的组合才生效。"""
    assert cp.compute_crawl_interval("bili", "search") == cp.compute_crawl_interval("bili")


# ---------------------------------------------------------------------------
# 3. 搜索预算
# ---------------------------------------------------------------------------


@pytest.fixture
def budget(tmp_path):
    b = xs.SearchBudget(tmp_path / "budget.json")
    xs.reset_search_budget(b)
    yield b
    xs.reset_search_budget(None)


def test_batch_over_limit_is_refused_before_any_request(budget):
    limit = xs.max_keywords_per_batch()
    with pytest.raises(xs.SearchBudgetExceeded) as excinfo:
        xs.ensure_batch_allowed(limit + 1)
    assert "一次最多搜" in str(excinfo.value)
    # 拒绝时不该消耗额度
    assert budget.used_today() == 0


def test_batch_within_limit_passes(budget):
    xs.ensure_batch_allowed(xs.max_keywords_per_batch())
    assert budget.used_today() == 0


def test_daily_budget_runs_out(budget):
    limit = xs.daily_search_limit()
    for _ in range(limit):
        budget.consume(1)
    assert budget.remaining_today() == 0
    with pytest.raises(xs.SearchBudgetExceeded) as excinfo:
        xs.ensure_batch_allowed(1)
    assert excinfo.value.retry_after_seconds is not None
    assert excinfo.value.retry_after_seconds > 0


def test_partial_remaining_is_respected(budget):
    budget.consume(xs.daily_search_limit() - 1)
    assert budget.remaining_today() == 1
    with pytest.raises(xs.SearchBudgetExceeded):
        xs.ensure_batch_allowed(2)
    xs.ensure_batch_allowed(1)


def test_budget_resets_on_a_new_day(budget):
    budget.consume(xs.daily_search_limit())
    raw = json.loads(budget.path.read_text(encoding="utf-8"))
    raw["date"] = "2000-01-01"
    budget.path.write_text(json.dumps(raw), encoding="utf-8")
    assert budget.used_today() == 0
    assert budget.remaining_today() == xs.daily_search_limit()


def test_budget_file_is_human_readable(budget):
    """预算落盘要能人工看/改（排查时直接打开就知道今天搜了几次）。"""
    budget.consume(2)
    raw = json.loads(budget.path.read_text(encoding="utf-8"))
    assert raw["used"] == 2
    assert raw["date"] == time.strftime("%Y-%m-%d")


def test_budget_save_failure_does_not_raise(tmp_path):
    """预算文件写不了不该让采集本身崩掉（最坏是下次少算一次）。"""
    unwritable = xs.SearchBudget(tmp_path / "no" / "such" / "dir" / "x.json")
    # 父目录不可创建时也不抛
    unwritable.path = tmp_path / "file_is_a_dir"
    unwritable.path.mkdir()
    assert unwritable.consume(1) == (1, xs.daily_search_limit())


# ---------------------------------------------------------------------------
# 4. 爬虫自身的 search 路径也要受预算约束（Web「立即采集」走这条）
# ---------------------------------------------------------------------------


def test_crawler_search_entry_checks_budget(monkeypatch):
    """``main.py --type search``（Web 面板「立即采集」）不能绕过配额。

    独立脚本有 ``ensure_batch_allowed``，但面板走的是 ``XiaoHongShuCrawler.search()``；
    只拦脚本等于"手动跑受管，点按钮不受管"。这里确认入口处有这道检查。
    """
    import inspect

    from media_platform.xhs.core import XiaoHongShuCrawler

    source = inspect.getsource(XiaoHongShuCrawler.search)
    assert "ensure_batch_allowed" in source
    assert "search_budget()" in source


def test_crawler_search_does_not_swallow_blocker():
    """撞到拦截后必须把异常抛出去，否则 main 会当成跑通并清掉冷却。"""
    import inspect

    from media_platform.xhs.core import XiaoHongShuCrawler

    source = inspect.getsource(XiaoHongShuCrawler.search)
    assert "raise blocker" in source


# ---------------------------------------------------------------------------
# 5. 关键词轮转（词表比单批上限长时，不能永远只搜前几个）
# ---------------------------------------------------------------------------


def test_short_keyword_list_is_not_split():
    batch, deferred = xs.plan_keywords(["a", "b", "c"], max_per_batch=4)
    assert batch == ["a", "b", "c"]
    assert deferred == []


def test_long_keyword_list_is_split_without_losing_any():
    words = [f"词{i}" for i in range(9)]
    batch, deferred = xs.plan_keywords(words, max_per_batch=4, today="2026-01-01")
    assert len(batch) == 4
    assert len(deferred) == 5
    # 一个都不能丢：两批合起来正好是原表（顺序可旋转，集合必须相等）
    assert set(batch) | set(deferred) == set(words)
    assert len(set(batch) | set(deferred)) == 9


def test_rotation_advances_across_days():
    """固定取前 4 个会让后排的词永远轮不到；轮转要保证每天起点不同。"""
    words = [f"词{i}" for i in range(9)]
    seen = set()
    for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
        batch, _ = xs.plan_keywords(words, max_per_batch=4, today=day)
        seen.update(batch)
    # 三天累计应当覆盖超过单批的 4 个，而不是每天都是同一批
    assert len(seen) > 4


def test_rotation_wraps_around_without_empty_result():
    """起点接近表尾时也要凑满一批（绕回表头），不能返回不足额。"""
    words = [f"词{i}" for i in range(9)]
    for day in range(1, 32):
        batch, deferred = xs.plan_keywords(words, max_per_batch=4, today=f"2026-01-{day:02d}")
        assert len(batch) == 4
        assert len(deferred) == 5


def test_plan_keywords_handles_empty_and_blank():
    assert xs.plan_keywords([]) == ([], [])
    assert xs.plan_keywords(["  ", ""]) == ([], [])


def test_plan_keywords_strips_whitespace():
    batch, _ = xs.plan_keywords([" 人工智能 ", " 副业"], max_per_batch=4)
    assert batch == ["人工智能", "副业"]
