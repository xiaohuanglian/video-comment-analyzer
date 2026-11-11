# -*- coding: utf-8 -*-
"""热评通道：动作路由、竞争判定、播放量解析、根评论发送。

这里锁的是「什么时候发根评论、什么时候回具体的人」这条判断，不是实现细节。
阈值来自本机 58,483 条真实语料的实测中位数，改动前先跑
`uv run python scripts/hot_comment_stats.py` 看语料有没有变。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from api.services.outreach import hot_comment as hc


def _now() -> datetime:
    return datetime(2026, 11, 11, 12, 0, 0)


def _video(vid: str = "v1", play: int = 100_000, comments: int = 200, age_hours: int = 40) -> dict:
    ts = int((_now() - timedelta(hours=age_hours)).timestamp())
    return {
        "video_id": vid,
        "title": "用 AI 做副业的第一天",
        "video_url": f"https://www.bilibili.com/video/{vid}",
        "video_play_count": str(play),
        "video_comment": str(comments),
        "create_time": ts,
    }


def _root(cid: str, likes: int, vid: str = "v1", text: str = "") -> dict:
    return {
        "comment_id": cid,
        "video_id": vid,
        "content": text or f"评论{cid}",
        "like_count": likes,
        "parent_comment_id": "0",
        "create_time": int(_now().timestamp()),
    }


def _roots(vid: str, *likes: int) -> list[dict]:
    """造一批根评论。**条数要给够**——少于 5 条会被判 unknown_coverage。"""
    return [_root(f"{vid}-c{i}", lk, vid=vid) for i, lk in enumerate(likes)]


def _quiet_roots(vid: str = "v1") -> list[dict]:
    """评论区有 6 条评论、最高 1 赞 → 任何档位都判「还有空位」。"""
    return _roots(vid, 1, 0, 0, 0, 0, 0)


class TestParsePlayCount:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("5305", 5305),
            (5305, 5305),
            ("10万+", 100_000),
            ("1.2w", 12_000),
            ("2W", 20_000),
            (" 27152 ", 27152),
            ("", 0),
            (None, 0),
            ("-5", 0),
            ("不详", 0),
            (True, 0),  # bool 是 int 的子类，不能当数字用
        ],
    )
    def test_parses_platform_formats(self, raw, expected):
        assert hc.parse_play_count(raw) == expected


class TestAssessCompetition:
    def test_tiny_video_is_skipped(self):
        """播放不足 1000：评论区几乎没人，发根评论没有收益。"""
        got = hc.assess_video_competition(video=_video(play=800), root_rows=[], now=_now())
        assert got["competition"] == "too_small"
        assert got["route"] == "skip"

    def test_cold_comment_section_favors_root_comment(self):
        """评论区规模小、现有热评也没赞 → 一条像样的根评论就能占住。"""
        got = hc.assess_video_competition(
            video=_video(play=5000, comments=4),
            root_rows=[_root("c1", 1), _root("c2", 0)],
            now=_now(),
        )
        assert got["competition"] == "cold"
        assert got["route"] == "hot_comment"

    def test_crowded_section_replies_instead(self):
        """已有远超同档中位的热评（5w-20w 档中位 248，门槛 496，这里 900 赞）→ 抢不过。"""
        got = hc.assess_video_competition(
            video=_video(play=100_000, comments=300),
            root_rows=[_root(f"c{i}", v) for i, v in enumerate([900, 400, 120, 80, 60, 40])],
            config={"hot_comment_crowd_floor": 50},
            now=_now(),
        )
        assert got["competition"] == "crowded"
        assert got["route"] == "reply"

    def test_open_section_favors_root_comment(self):
        """同档中位 248，最高只有 30 赞（开位线 124）→ 还有空位。"""
        got = hc.assess_video_competition(
            video=_video(play=100_000, comments=120),
            root_rows=[_root(f"c{i}", v) for i, v in enumerate([30, 12, 8, 5, 3, 1])],
            now=_now(),
        )
        assert got["competition"] == "open"
        assert got["route"] == "hot_comment"

    def test_contested_section_replies(self):
        """介于空位与被占住之间：稳妥做法是回具体的人。"""
        got = hc.assess_video_competition(
            video=_video(play=100_000, comments=150),
            root_rows=[_root(f"c{i}", v) for i, v in enumerate([180, 120, 90, 70, 50, 40])],
            now=_now(),
        )
        assert got["competition"] == "contested"
        assert got["route"] == "reply"

    def test_same_like_count_means_different_things_by_tier(self):
        """30 赞在 2 千播放里是压死人的热评，在 20 万播放里几乎没人看见。

        这条是「为什么不能设固定赞数门槛」的核心断言。
        """
        rows = [_root(f"c{i}", 30 if i == 0 else 1) for i in range(6)]
        small = hc.assess_video_competition(
            video=_video(play=2_000, comments=60),
            root_rows=rows,
            now=_now(),
        )
        big = hc.assess_video_competition(
            video=_video(play=300_000, comments=60),
            root_rows=rows,
            now=_now(),
        )
        assert small["route"] == "reply"       # 30 ≥ 小流量档门槛 50 的八成，已算抢手
        assert big["route"] == "hot_comment"   # 30 << 爆款档中位 577

    def test_too_few_samples_is_not_judged(self):
        """只采到几条评论时 top1 不可信（实测 0–4 条六成判错）→ 不赌根评论。

        真实案例 117480458555570：播放 7,184、我们一条没采到，被判「空位」，
        实际平台真热评 71 赞。
        """
        got = hc.assess_video_competition(
            video=_video(play=7_184, comments=40),
            root_rows=[],
            now=_now(),
        )
        assert got["competition"] == "unknown_coverage"
        assert got["route"] == "reply"
        assert got["sampled"] == 0
        assert "只采到 0 条" in got["reason"]

    def test_small_but_complete_sample_still_judged(self):
        """平台只报告 3 条评论、我们也采到 3 条 → 采样完整，照常判。"""
        got = hc.assess_video_competition(
            video=_video(play=9_000, comments=3),
            root_rows=[_root("c1", 1), _root("c2", 0), _root("c3", 0)],
            now=_now(),
        )
        assert got["competition"] == "cold"
        assert got["route"] == "hot_comment"

    def test_min_sample_configurable(self):
        """阈值可配：把下限调到 1，同样的残缺采样就放行。"""
        video = _video(play=100_000, comments=300)
        rows = [_root("c1", 10), _root("c2", 5)]
        strict = hc.assess_video_competition(video=video, root_rows=rows, now=_now())
        loose = hc.assess_video_competition(
            video=video, root_rows=rows, config={"hot_comment_min_sample": 1}, now=_now()
        )
        assert strict["competition"] == "unknown_coverage"
        assert loose["competition"] != "unknown_coverage"

    def test_uses_platform_reported_comment_count(self):
        """平台报告的评论数比我们采到的全，取较大值当规模。"""
        got = hc.assess_video_competition(
            video=_video(play=20_000, comments=500),
            root_rows=[_root("c1", 0)],  # 我们只采到 1 条
            now=_now(),
        )
        assert got["comment_count"] == 500
        assert got["competition"] != "cold"

    def test_hot_texts_carried_for_drafting(self):
        """已有热评原文要带出去给起草用（别重复别人说过的话）。"""
        got = hc.assess_video_competition(
            video=_video(play=100_000),
            root_rows=[_root("c1", 5, text="这个我试过"), _root("c2", 1, text="求教程")],
            now=_now(),
        )
        assert got["hot_texts"] == ["这个我试过", "求教程"]

    def test_thresholds_configurable(self):
        """阈值必须能配——语料换领域后中位数会变。"""
        video = _video(play=100_000)
        rows = [_root(f"c{i}", 30 if i == 0 else 1) for i in range(6)]
        strict = hc.assess_video_competition(
            video=video, root_rows=rows, config={"hot_comment_open_ratio": 0.01}, now=_now()
        )
        loose = hc.assess_video_competition(
            video=video, root_rows=rows, config={"hot_comment_open_ratio": 1.0}, now=_now()
        )
        assert strict["route"] == "reply"
        assert loose["route"] == "hot_comment"


class TestBuildHotCandidates:
    def _cfg(self, **kw) -> dict:
        cfg = {
            "hot_comment_enabled": True,
            "hot_comment_max_per_cycle": 2,
            "hot_comment_min_play": 1_000,
            "hot_comment_cold_comments": 10,
            "hot_comment_crowd_multiple": 2.0,
            "hot_comment_crowd_floor": 50,
            "hot_comment_open_ratio": 0.5,
            "freshness_a_hours": 48,
            "freshness_b_hours": 720,
        }
        cfg.update(kw)
        return cfg

    def test_produces_root_comment_item(self):
        video_map = {"v1": _video("v1", play=100_000, comments=300)}
        rows = _quiet_roots("v1")
        picked, funnel = hc.build_hot_candidates(rows, video_map, self._cfg(), now=_now())
        assert len(picked) == 1
        item = picked[0]
        assert item["action"] == "hot_comment"
        # 根评论没有目标评论：发送时 root/parent 都用 "0"
        assert item["comment_id"] == "0"
        assert item["video_id"] == "v1"
        assert item["lane"] == "engage"
        assert item["status"] == "pending_review"
        assert funnel["hot_candidates"] == 1

    def test_one_per_cycle_quota(self):
        video_map = {f"v{i}": _video(f"v{i}", play=100_000, comments=300) for i in range(5)}
        rows = [r for i in range(5) for r in _quiet_roots(f"v{i}")]
        picked, _ = hc.build_hot_candidates(rows, video_map, self._cfg(hot_comment_max_per_cycle=2), now=_now())
        assert len(picked) == 2

    def test_largest_video_first(self):
        video_map = {
            "small": _video("small", play=6_000, comments=300),
            "big": _video("big", play=900_000, comments=300),
        }
        rows = _quiet_roots("small") + _quiet_roots("big")
        picked, _ = hc.build_hot_candidates(rows, video_map, self._cfg(hot_comment_max_per_cycle=1), now=_now())
        assert picked[0]["video_id"] == "big"

    def test_busy_video_is_skipped(self):
        """同一个视频在队列里已有根评论 → 不再出第二条（像刷屏）。"""
        video_map = {"v1": _video("v1", play=100_000, comments=300)}
        picked, funnel = hc.build_hot_candidates(
            _quiet_roots("v1"), video_map, self._cfg(), now=_now(), busy_videos={"v1": "pending_review"}
        )
        assert picked == []
        assert funnel["cooldown"] == 1

    def test_processed_video_is_skipped(self):
        video_map = {"v1": _video("v1", play=100_000, comments=300)}
        picked, _ = hc.build_hot_candidates(
            _quiet_roots("v1"), video_map, self._cfg(), now=_now(), skip_videos={"v1"}
        )
        assert picked == []

    def test_disabled_returns_empty(self):
        video_map = {"v1": _video("v1", play=100_000, comments=300)}
        picked, funnel = hc.build_hot_candidates(
            _quiet_roots("v1"), video_map, self._cfg(hot_comment_enabled=False), now=_now()
        )
        assert picked == []
        assert funnel["hot_candidates"] == 0

    def test_stale_video_skipped(self):
        video_map = {"v1": _video("v1", play=100_000, comments=300, age_hours=1000)}
        picked, funnel = hc.build_hot_candidates(_quiet_roots("v1"), video_map, self._cfg(), now=_now())
        assert picked == []
        assert funnel["cooldown"] == 1

    def test_unknown_coverage_video_not_picked(self):
        """只采到 2 条评论（平台报告 300）→ 看不到真实热评，不发根评论。"""
        video_map = {"v1": _video("v1", play=100_000, comments=300)}
        picked, funnel = hc.build_hot_candidates(_roots("v1", 1, 0), video_map, self._cfg(), now=_now())
        assert picked == []
        assert funnel["unknown_coverage"] == 1

    def test_sub_replies_excluded_from_competition(self):
        """楼中楼不算根评论竞争——它们不参与赞排序。"""
        video_map = {"v1": _video("v1", play=100_000, comments=300)}
        rows = _roots("v1", 10, 0, 0, 0, 0, 0) + [
            {**_root("c-sub", 9999, vid="v1"), "parent_comment_id": "v1-c0"},
        ]
        picked, _ = hc.build_hot_candidates(rows, video_map, self._cfg(), now=_now())
        assert picked[0]["like_count"] == 10


class TestMarkVideoRoutes:
    def test_same_video_both_actions_marked(self):
        items = [
            {"video_id": "v1", "action": "reply"},
            {"video_id": "v1", "action": "hot_comment"},
            {"video_id": "v2", "action": "reply"},
        ]
        counts = hc.mark_video_routes(items)
        assert items[0]["video_route"] == "both"
        assert items[1]["video_route"] == "both"
        assert items[2]["video_route"] == "reply"
        assert counts == {"both": 2, "reply": 1}

    def test_hot_only(self):
        items = [{"video_id": "v1", "action": "hot_comment"}]
        hc.mark_video_routes(items)
        assert items[0]["video_route"] == "hot_comment"
