# -*- coding: utf-8 -*-
"""reply_style：活人感硬禁令 lint + 平台风控频率默认值。"""

from __future__ import annotations

from api.services.outreach.reply_style import (
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

    def test_condescending_tone_banned(self):
        cases = [
            "你再翻翻看，别急着放弃，其实很简单的",
            "仔细找找就能发现",
            "这个其实很容易的",
        ]
        for text in cases:
            assert check_reply_style(text), text
        # 方法直接给到 + 归因于产品的写法是干净的
        assert check_reply_style("批量导出是支持的，只是入口藏得比较深，列表里多选后点导出就行") == []

    def test_pointing_phrasing_banned(self):
        # 2026-10-13 真实案例：回复要给便利，不指路不提博主
        cases = [
            "博主自己在评论区也说过，可以换 gpt 试试",
            "具体就在这条笔记评论区往下翻",
            "好多人都在评论区找",
            "你自己去搜一下就有了",
        ]
        for text in cases:
            assert check_reply_style(text), text
        # 答案直接给全的写法是干净的
        assert check_reply_style("可灵的参数文档官方是有的，klingai.com 首页点文档中心，参数说明和 API 文档都在里面") == []
        assert check_reply_style("gpt 就能做，照片加提示词直接出，不用装别的软件。vaeen ai design 这个网站也能出同类效果") == []

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
        assert got["interval_seconds"] >= 60
        assert got["daily_limit"] >= 20
        assert got["session_replies"] >= 1

    def test_all_intervals_reasonable(self):
        # 仿人工节奏：短间隔随机波动 + 集群间长休息；日限足够自动化有意义
        for key, d in PLATFORM_REPLY_DEFAULTS.items():
            assert d["interval_seconds"] >= 30, key
            assert d["jitter_seconds"] >= d["interval_seconds"], key  # 抖动够大，避免匀速机器节奏
            assert d["daily_limit"] >= 30, key
            assert d["session_replies"] >= 3, key
            assert d["break_seconds"] >= 600, key

    def test_human_like_session_pattern(self):
        # 集群模式：连发若干条后长休息，而不是全天匀速
        for key, d in PLATFORM_REPLY_DEFAULTS.items():
            short = d["interval_seconds"] + d["jitter_seconds"]
            assert d["break_seconds"] >= short * 3, key  # 休息明显长于集群内间隔
