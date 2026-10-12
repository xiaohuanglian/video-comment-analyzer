# -*- coding: utf-8 -*-
"""reply_style：活人感硬禁令 lint + 平台风控频率默认值。"""

from __future__ import annotations

from api.services.insight.reply_style import (
    PLATFORM_REPLY_DEFAULTS,
    check_reply_style,
    resolve_platform_defaults,
)


class TestCheckReplyStyle:
    def test_clean_reply_passes(self):
        text = "看到你说导出总失败，我之前也卡在这。后来发现是没勾选原始画质，勾上之后就正常了，你试试。"
        assert check_reply_style(text) == []

    def test_clean_reply_with_quote_colon_passes(self):
        # 引直接原话的冒号合法
        text = "你原话说的「加载两分钟」，我这边同一个视频秒开，大概率是网络问题，换个网络再试一次。"
        assert check_reply_style(text) == []

    def test_dash_banned(self):
        assert any("破折号" in w for w in check_reply_style("这个方法很简单——先关掉再重开"))

    def test_prompt_colon_banned(self):
        assert any("冒号" in w for w in check_reply_style("一句话总结，我的经验是：多试几次"))

    def test_reversal_patterns_banned(self):
        cases = [
            "关键不是工具，而是习惯",
            "问题并非出在手机，而是网络",
            "重点不在于快，而在于稳",
            "与其说它是教程，不如说是经验",
            "表面上卡顿，实际是内存不足",
            "你以为很难，其实五分钟搞定",
            "说到底还是练习量不够",
        ]
        for text in cases:
            assert check_reply_style(text), text

    def test_jargon_banned(self):
        assert any("黑话" in w for w in check_reply_style("这个方法很底层逻辑，建议收藏"))
        assert any("黑话" in w for w in check_reply_style("说白了就是权限问题"))

    def test_triple_parallel_banned_but_double_ok(self):
        assert any("排比" in w for w in check_reply_style("需要耐心、需要时间、需要练习"))
        assert check_reply_style("需要耐心、需要时间") == []

    def test_nominalization_banned(self):
        assert any("名词化" in w for w in check_reply_style("我完成了对流程的优化"))

    def test_empty_text(self):
        assert check_reply_style("") == []


class TestPlatformDefaults:
    def test_known_platforms_covered(self):
        for key in ("bilibili", "douyin", "xhs", "kuaishou", "weibo", "zhihu", "tieba"):
            assert key in PLATFORM_REPLY_DEFAULTS

    def test_aliases_resolved(self):
        assert resolve_platform_defaults("bili")["daily_limit"] == PLATFORM_REPLY_DEFAULTS["bilibili"]["daily_limit"]
        assert resolve_platform_defaults("XHS")["daily_limit"] == PLATFORM_REPLY_DEFAULTS["xhs"]["daily_limit"]
        assert resolve_platform_defaults("xiaohongshu")["daily_limit"] == PLATFORM_REPLY_DEFAULTS["xhs"]["daily_limit"]

    def test_unknown_platform_gets_conservative_defaults(self):
        got = resolve_platform_defaults("unknown_platform")
        assert got["interval_seconds"] >= 300
        assert got["daily_limit"] <= 10

    def test_all_intervals_reasonable(self):
        # 外站引流场景：最小间隔不低于 2 分钟，日限不高于 30
        for key, d in PLATFORM_REPLY_DEFAULTS.items():
            assert d["interval_seconds"] >= 120, key
            assert d["daily_limit"] <= 30, key
            assert d["jitter_seconds"] > 0, key
