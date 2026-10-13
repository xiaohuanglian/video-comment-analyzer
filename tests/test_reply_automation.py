# -*- coding: utf-8 -*-
"""reply_automation：B 站回复自动化——筛选规则 / 状态机 / 发送闸门。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from api.services.insight import reply_automation as auto


# ---------------------------------------------------------------------------
# classify_comment：产品需要人群筛选
# ---------------------------------------------------------------------------

class TestClassifyComment:
    def test_howto_question_is_target_a(self):
        status, signal = auto.classify_comment("视频只生成30s，如果要长视频，应该有怎么做衔接呀")
        assert status == "target_a"
        assert "问工具" in signal or "怎么做" in signal

    def test_tool_question_is_target_a(self):
        status, _ = auto.classify_comment("想问问生图生视频基本用什么软件？有没有便宜好用的求推荐")
        assert status == "target_a"

    def test_newbie_with_question_is_target_b(self):
        status, signal = auto.classify_comment("我是个纯小白，想做这种AI视频该从哪一步开始呢")
        assert status == "target_b"
        assert "新手" in signal

    def test_access_excluded(self):
        for text in (
            "怎么才能用上gpt啊，注册不了",
            "买了个号被封了，中转站也不稳",
            "订阅chatgpt plus用什么支付方式",
        ):
            status, label = auto.classify_comment(text)
            assert status == "excluded", text
            assert label in ("使用渠道类",), text

    def test_monetize_excluded(self):
        status, label = auto.classify_comment("这种AI视频怎么做变现啊，能赚钱吗")
        assert status == "excluded"
        assert label == "变现类"

    def test_debug_excluded(self):
        status, label = auto.classify_comment("工作流里的加载器一直报错说无法检测模型，找不到原因")
        assert status == "excluded"
        assert label == "个案报错"

    def test_resource_beg_excluded(self):
        for text in (
            "已三连，求skill！",
            "求知识库，蹲一波资料",
            "三连了 求知识库",
            "求提示词分享一下，谢谢up主",
        ):
            status, label = auto.classify_comment(text)
            assert status == "excluded", text
            assert label == "求UP私有资源", text

    def test_director_excluded(self):
        status, label = auto.classify_comment("特别想知道您的中间过渡页讲解动画是用什么AI生成的")
        assert status == "excluded"
        assert label == "导演式提问"

    def test_polite_you_not_excluded(self):
        # 礼貌用语（您好/请）不该被导演式规则误伤
        status, _ = auto.classify_comment("您好请问这类修图用什么软件做的呀，想学")
        assert status != "excluded"

    def test_ai_water_excluded(self):
        status, label = auto.classify_comment("2026年入门AI视频，云和本地部署这道选择题确实值得琢磨")
        assert status == "excluded"
        assert label == "AI水评"

    def test_pure_exclaim_excluded(self):
        status, _ = auto.classify_comment("太强了支持up")
        assert status == "excluded"

    def test_too_short_excluded(self):
        status, _ = auto.classify_comment("怎么做")
        assert status == "excluded"

    # 2026-10-13 真实数据回归：观点/反问/抒情不进队列
    def test_real_world_false_positives_excluded(self):
        for text in (
            # 观点长文：含「如何利用ai」但是论述不是提问
            "应试教育考查人的方式真该改改了，以后新一代所有人都应该学会如何利用ai，而不是比谁会算题。闭卷计算数学，应该逐渐转向开放工具的数学推理与建模，如果二三十年后学生还",
            # 反问式夸奖
            "不是，没人夸这个Gemini的配音吗……逻辑重音和情绪节奏都非常完美，真的和真人科普纪录片配音一模一样了",
            # 陈述句含「流程」
            "全套流程提示词已跑通，免费分享",
            # 习语反问
            "3.8flash日用非常好了，比豆包聪明多模态跟豆包一样好软件体验也比豆包好，我真当豆包用的，一年68还要什么自行车",
            # 抒情体
            "我从没觉得自己是一个多愁善感的人，带着对AI的郻夷和无可奈何点进这个视频。是AI掌握了用音乐使人类哭泣的能力吗？",
        ):
            status, label = auto.classify_comment(text)
            assert status == "excluded", f"{text[:30]}… 被误判为 {status}/{label}"

    def test_real_world_true_positives_pass(self):
        # 夸奖+真提问（好奇怎么做）应入选
        status, _ = auto.classify_comment("做的视频真的很厉害，把一个复杂的问题简单化了。另外，我好奇，这些非常厉害的动画是怎么做的")
        assert status == "target_a"
        # 想动手的具体设想+能实现吗应入选
        status, _ = auto.classify_comment("如果我想用大模型辅助数学学习，比如建立obsidian知识库、自动做读书笔记、归档学习记录，这个用gpt6.1sol能实现吗")
        assert status == "target_b"


# ---------------------------------------------------------------------------
# build_candidates：新鲜度 / 去重 / 配额
# ---------------------------------------------------------------------------

def _row(cid, text, vid="v1", hours=10, likes=0):
    return {
        "comment_id": cid,
        "video_id": vid,
        "content": text,
        "nickname": "用户" + cid,
        "like_count": likes,
        "create_time": int((datetime.now() - timedelta(hours=hours)).timestamp()),
    }


class TestBuildCandidates:
    def _cfg(self, **kw):
        cfg = dict(auto.DEFAULT_CONFIG)
        cfg.update(kw)
        return cfg

    def test_freshness_tiers(self):
        rows = [
            _row("c1", "请问这种动画用什么软件做的呀", vid="v1", hours=10),
            _row("c2", "请问这种动画用什么软件做的呀", vid="v2", hours=100),
            _row("c3", "请问这种动画用什么软件做的呀", vid="v3", hours=200),
        ]
        picked, funnel = auto.build_candidates(rows, {}, self._cfg(), set())
        assert [p["id"] for p in picked] == ["c_c1", "c_c2"]
        assert picked[0]["tier"] == "A"
        assert picked[1]["tier"] == "B"
        assert funnel["stale"] == 1

    def test_dedup_processed_and_inbatch(self):
        rows = [_row("c1", "请问这种动画用什么软件做的呀"), _row("c1", "请问这种动画用什么软件做的呀")]
        picked, funnel = auto.build_candidates(rows, {}, self._cfg(), {"c1"})
        assert picked == []
        assert funnel["dedup"] == 2

    def test_per_video_per_day_cap(self):
        rows = [
            _row("c1", "请问这种动画用什么软件做的呀", vid="v1"),
            _row("c2", "长视频应该怎么做衔接呀", vid="v1"),
        ]
        picked, _ = auto.build_candidates(rows, {}, self._cfg(), set())
        assert len(picked) == 1

    def test_cycle_quota(self):
        rows = [_row(f"c{i}", "请问这种动画用什么软件做的呀", vid=f"v{i}") for i in range(10)]
        picked, _ = auto.build_candidates(rows, {}, self._cfg(max_new_candidates_per_cycle=3), set())
        assert len(picked) == 3

    def test_likes_ordering(self):
        rows = [
            _row("c1", "请问这种动画用什么软件做的呀", vid="v1", likes=0),
            _row("c2", "请问这种动画用什么软件做的呀", vid="v2", likes=30),
        ]
        picked, _ = auto.build_candidates(rows, {}, self._cfg(), set())
        assert picked[0]["id"] == "c_c2"

    def test_dirty_like_count_tolerated(self):
        rows = [_row("c1", "请问这种动画用什么软件做的呀", likes="赞")]
        picked, _ = auto.build_candidates(rows, {}, self._cfg(), set())
        assert len(picked) == 1 and picked[0]["like_count"] == 0


# ---------------------------------------------------------------------------
# AutomationStore：状态机与发送闸门
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path):
    return auto.AutomationStore(path=tmp_path / "auto.json")


def _item(cid="c100", status="pending_review", draft="测试草稿，方法直接给全。"):
    return {
        "id": f"c_{cid}",
        "comment_id": cid,
        "video_id": "v1",
        "video_title": "测试视频",
        "video_url": "",
        "commenter": "测试用户",
        "comment_text": "请问这种动画用什么软件做的呀",
        "like_count": 1,
        "age_hours": 5.0,
        "signal": "问工具/怎么做",
        "tier": "A",
        "draft": draft,
        "lint_warnings": [],
        "draft_source": "llm",
        "status": status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "decided_at": "",
        "sent_at": "",
        "send_error": "",
        "reply_id": "",
        "attempts": 0,
        "note": "",
    }


class TestAutomationStore:
    def test_persistence_roundtrip(self, tmp_path):
        path = tmp_path / "auto.json"
        s1 = auto.AutomationStore(path=path)
        s1.add_items([_item("c9")])
        s1.update_config({"keywords": ["AI视频", "可灵"]})
        s2 = auto.AutomationStore(path=path)
        assert s2.find("c_c9") is not None
        assert s2.config["keywords"] == ["AI视频", "可灵"]

    def test_approve_requires_draft_and_lints(self, store):
        store.add_items([_item("c1", draft="")])
        assert store.decide("c_c1", "approve") is None  # 空草稿拒绝
        ok = store.decide("c_c1", "approve", draft="答案是gpt，照片加提示词直接出。")
        assert ok and ok["status"] == "approved"
        assert ok["lint_warnings"] == []

    def test_reject(self, store):
        store.add_items([_item("c1")])
        assert store.decide("c_c1", "reject")["status"] == "rejected"
        assert store.decide("c_c1", "approve") is None  # 已处理不可再批

    def test_config_keywords_from_text(self, store):
        cfg = store.update_config({"keywords": "AI视频，可灵, 修图"})
        assert cfg["keywords"] == ["AI视频", "可灵", "修图"]

    def test_rejected_candidates_not_requeued(self, store):
        # 拒绝的评论进 processed，之后不再重复入队
        store.add_items([_item("c1")])
        store.decide("c_c1", "reject")
        assert "c1" in store._state["processed_comment_ids"]

    def test_can_send_window(self, store):
        store.update_config({"enabled": True, "send_window_start": "23:00", "send_window_end": "23:59"})
        ok, reason = store.can_send_now(now=datetime.now().replace(hour=12, minute=0))
        assert not ok and "窗口" in reason

    def test_can_send_daily_limit(self, store):
        store.update_config({"enabled": True, "daily_send_limit": 1})
        store._state["sender"]["today"] = datetime.now().strftime("%Y-%m-%d")
        store._state["sender"]["sent_today"] = 1
        ok, reason = store.can_send_now()
        assert not ok and "上限" in reason

    def test_can_send_pacing_wait(self, store):
        store.update_config({"enabled": True})
        store._state["sender"]["next_allowed_at"] = (
            datetime.now() + timedelta(minutes=5)
        ).isoformat(timespec="seconds")
        ok, reason = store.can_send_now()
        assert not ok and "节奏" in reason

    def test_disabled_blocks_send(self, store):
        ok, reason = store.can_send_now()
        assert not ok and "未启用" in reason

    def test_mark_sent_sets_pacing_and_daily(self, store):
        store.update_config({"enabled": True, "send_interval_seconds": 60, "send_jitter_seconds": 0})
        item = _item("c1", status="approved")
        store.add_items([item])
        store.mark_sent(item, "rpid123")
        assert item["status"] == "sent"
        assert store._state["sender"]["sent_today"] == 1
        assert store._state["sender"]["next_allowed_at"]

    def test_mark_failed_backoff_and_three_strikes(self, store):
        item = _item("c1", status="approved")
        store.add_items([item])
        for i in range(3):
            store.mark_failed(item, "评论被折叠/需要验证")
        assert item["status"] == "failed"
        assert item["attempts"] == 3
        assert store._state["sender"]["next_allowed_at"]  # 失败后有退避

    def test_send_bilibili_reply_called_with_final_draft(self, store):
        # 批准时最终文本以批准时刻的草稿为准
        store.add_items([_item("c1", draft="旧草稿")])
        item = store.decide("c_c1", "approve", draft="新草稿，答案直接给全步骤。")
        assert item["draft"] == "新草稿，答案直接给全步骤。"

class TestRetractAndVisibility:
    def test_retract_approved_back_to_pending(self, store):
        store.add_items([_item("c1")])
        store.decide("c_c1", "approve", draft="答案直接给全的测试草稿。")
        back = store.retract("c_c1")
        assert back and back["status"] == "pending_review"
        # 撤回后可再次批准
        again = store.decide("c_c1", "approve", draft="修改后的草稿，步骤给全。")
        assert again and again["status"] == "approved"

    def test_retract_only_works_on_approved(self, store):
        store.add_items([_item("c1")])
        assert store.retract("c_c1") is None  # pending 状态不可撤回
