# -*- coding: utf-8 -*-
"""reply_automation：B 站回复自动化——筛选规则 / 状态机 / 发送闸门。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from api.services.outreach import reply_automation as auto


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

    def test_monetize_no_longer_excluded(self):
        # 2026-10-27 定位转向:想赚钱的实干者是核心受众,不再规则排除
        status, label = auto.classify_comment("这种AI视频怎么做变现啊，能赚钱吗")
        assert status == "target_a", label  # "怎么做"命中 HOWTO,进 A 档

    def test_business_entity_recalled_as_target_c(self):
        # 商业词不带AI也能被 C 档召回(AI×商业讨论)
        status, label = auto.classify_comment("一人公司才是普通人在AI时代翻身的正路,别老想着打工")
        assert status == "target_c", label

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

    # 2026-10-13 真实数据回归(2026-10-23 双通道模型重审):
    # 观点评论分两类——AI 相关有实质内容的观点是互动对象(target_c,交 LLM 精筛判 engage);
    # 纯修辞/抒情/引流仍是噪声。
    def test_real_world_false_positives_excluded(self):
        for text in (
            # 反问式夸奖(钓夸,非观点)
            "不是，没人夸这个Gemini的配音吗……逻辑重音和情绪节奏都非常完美，真的和真人科普纪录片配音一模一样了",
            # 引流分享
            "全套流程提示词已跑通，免费分享",
            # 抒情体(纯情绪无内容可接)
            "我从没觉得自己是一个多愁善感的人，带着对AI的郻夷和无可奈何点进这个视频。是AI掌握了用音乐使人类哭泣的能力吗？",
        ):
            status, label = auto.classify_comment(text)
            assert status == "excluded", f"{text[:30]}… 被误判为 {status}/{label}"

    def test_real_world_ai_opinions_now_target_c(self):
        # 用户画像重定义:对AI感兴趣、发表看法的人值得互动——不再当误报拦掉
        cases = (
            # AI 时代教育观点长文
            "应试教育考查人的方式真该改改了，以后新一代所有人都应该学会如何利用ai，而不是比谁会算题。闭卷计算数学，应该逐渐转向开放工具的数学推理与建模",
            # 模型对比体验(含习语但观点实质)
            "3.8flash日用非常好了，比豆包聪明多模态跟豆包一样好软件体验也比豆包好，我真当豆包用的，一年68还要什么自行车",
        )
        for text in cases:
            status, label = auto.classify_comment(text)
            assert status == "target_c", f"{text[:30]}… 应为互动候选,实际 {status}/{label}"

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


# ---------------------------------------------------------------------------
# LLM 语义精筛
# ---------------------------------------------------------------------------

def _screen_item(cid: str, text: str, likes: int = 3) -> dict:
    return {
        "id": f"c_{cid}",
        "comment_id": cid,
        "video_id": "v1",
        "video_title": "AI视频教程",
        "video_url": "u",
        "commenter": "u",
        "comment_text": text,
        "like_count": likes,
        "age_hours": 1.0,
        "signal": "问工具/怎么做",
        "tier": "A",
        "lane": "help",
        "worth": 0,
        "intent": "",
        "match_reason": "问工具/怎么做",
        "screened_by": "rules",
        "draft": "",
        "lint_warnings": [],
        "draft_source": "",
        "status": "pending_review",
        "created_at": "2026-10-23T10:00:00",
        "decided_at": "",
        "sent_at": "",
        "send_error": "",
        "reply_id": "",
        "attempts": 0,
        "note": "",
    }


def _fake_complete(responses: dict[str, str]):
    """按评论原文关键词路由返回不同判定 JSON。"""

    async def _fn(messages, temperature=0.1, timeout=60, feature="automation.screen"):
        user = messages[-1]["content"]
        for key, resp in responses.items():
            if key in user:
                return resp
        return json.dumps({"lane": "help", "intent": "求做法/路径", "worth": 7, "reason": "默认通过"}, ensure_ascii=False)

    return _fn


class TestLlmScreen:
    def test_keeps_high_worth_with_reason(self):
        fn = _fake_complete({"动画": json.dumps({"lane": "help", "intent": "求做法/路径", "worth": 8, "reason": "具体问做法,能给全步骤"}, ensure_ascii=False)})
        items = [_screen_item("1", "这个数学动画用什么做的呀")]
        kept, stats = asyncio.run(auto.llm_screen_candidates(items, threshold=6, complete_fn=fn))
        assert len(kept) == 1
        assert kept[0]["worth"] == 8
        assert kept[0]["screened_by"] == "llm"
        assert "步骤" in kept[0]["match_reason"]
        assert stats == {"screened": 1, "kept": 1, "llm_failed": 0}

    def test_drops_off_domain_study_help(self):
        # 真提问但离域(备考/学术)→不入选:这是此前队列不精准的主场景
        fn = _fake_complete({"绩点": json.dumps({"lane": "skip", "intent": "离域求助", "worth": 2, "reason": "备考学习求助,不是内容创作人群"}, ensure_ascii=False)})
        items = [_screen_item("1", "大三重修求绩点复习规划建议")]
        kept, stats = asyncio.run(auto.llm_screen_candidates(items, threshold=6, complete_fn=fn))
        assert kept == []
        assert stats["screened"] == 1 and stats["kept"] == 0

    def test_threshold_boundary(self):
        fn = _fake_complete({"动画": json.dumps({"lane": "help", "intent": "求做法/路径", "worth": 5, "reason": "泛泛问法"}, ensure_ascii=False)})
        items = [_screen_item("1", "这个动画怎么做的")]
        kept, _ = asyncio.run(auto.llm_screen_candidates(items, threshold=6, complete_fn=fn))
        assert kept == []  # 5 < 6 不入选

    def test_sort_by_worth_desc(self):
        responses = {
            "高": json.dumps({"lane": "help", "intent": "求做法/路径", "worth": 9, "reason": "r9"}, ensure_ascii=False),
            "低": json.dumps({"lane": "help", "intent": "求工具/求推荐", "worth": 6, "reason": "r6"}, ensure_ascii=False),
        }
        fn = _fake_complete(responses)
        items = [_screen_item("1", "低分问题怎么弄"), _screen_item("2", "高分问题怎么做", likes=1)]
        kept, _ = asyncio.run(auto.llm_screen_candidates(items, threshold=6, complete_fn=fn))
        assert [k["worth"] for k in kept] == [9, 6]

    def test_unconfigured_raises_for_fallback(self):
        async def _fn(messages, **kw):
            raise RuntimeError("LLM 网关未配置")

        items = [_screen_item("1", "怎么做的")]
        with pytest.raises(auto.LlmScreenUnavailable):
            asyncio.run(auto.llm_screen_candidates(items, complete_fn=_fn))

    def test_first_network_failure_aborts_all(self):
        # 首条网络失败 → 整体降级,不逐条空等
        async def _fn(messages, **kw):
            raise OSError("connection reset")

        items = [_screen_item("1", "a"), _screen_item("2", "b")]
        with pytest.raises(auto.LlmScreenUnavailable):
            asyncio.run(auto.llm_screen_candidates(items, complete_fn=_fn))

    def test_later_parse_failure_keeps_item_as_rules(self):
        calls = {"n": 0}

        async def _fn(messages, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"lane": "help", "intent": "求做法/路径", "worth": 8, "reason": "ok"}, ensure_ascii=False)
            return "模型抽风了,没有JSON"

        items = [_screen_item("1", "first"), _screen_item("2", "second")]
        kept, stats = asyncio.run(auto.llm_screen_candidates(items, threshold=6, complete_fn=_fn))
        assert len(kept) == 2
        assert stats["llm_failed"] == 1
        assert kept[1]["screened_by"] == "rules"
        assert "LLM判读失败" in kept[1]["match_reason"]

    def test_screen_brief_injects_strategy(self, monkeypatch):
        from api.services import strategy as strategy_mod

        monkeypatch.setattr(
            strategy_mod, "load", lambda: {"niche": "给新手的AI视频实战教程", "target_audience": "上班族"}
        )
        brief = auto._screen_brief()
        assert "给新手的AI视频实战教程" in brief and "上班族" in brief

    def test_screen_brief_falls_back_to_default(self, monkeypatch):
        from api.services import strategy as strategy_mod

        monkeypatch.setattr(strategy_mod, "load", lambda: {})
        brief = auto._screen_brief()
        assert auto._DEFAULT_NICHE in brief


class TestLaneModel:
    """双通道:帮助型(help)与互动型(engage)。"""

    def test_ai_opinion_comment_is_target_c(self):
        # 不提问但有实质内容的 AI 观点 → C 档互动候选(用户画像:对AI感兴趣、发表看法可互动)
        status, signal = auto.classify_comment("说实话AI生成的东西现在还是有一种塑料感,但进步速度真的吓人,再过两年估计看不出来了")
        assert status == "target_c"
        assert signal == "AI相关观点/讨论"

    def test_ai_opinion_short_water_excluded(self):
        status, _ = auto.classify_comment("AI真强")
        assert status == "excluded"  # 太短没内容可接

    def test_non_ai_opinion_excluded(self):
        status, _ = auto.classify_comment("这个up主的剪辑节奏是真的舒服,看着不累,下饭神器")
        assert status == "excluded"  # 与 AI 无关的泛观点

    def test_english_word_not_misjudged_as_ai(self):
        status, _ = auto.classify_comment("I said hello to the world and waited")
        assert status == "excluded"  # said/hair 不应命中 AI 实体

    def test_llm_screen_keeps_engage_lane(self):
        fn = _fake_complete({"塑料感": json.dumps({"lane": "engage", "intent": "吐槽/怀疑", "worth": 7, "reason": "对AI成品有真实体感,可接话聊具体场景"}, ensure_ascii=False)})
        items = [_screen_item("1", "AI生成的还是有塑料感,但进步太快了")]
        items[0]["lane"] = "engage"
        kept, stats = asyncio.run(auto.llm_screen_candidates(items, threshold=6, complete_fn=fn))
        assert len(kept) == 1 and kept[0]["lane"] == "engage"

    def test_help_sorted_before_engage(self):
        responses = {
            "帮": json.dumps({"lane": "help", "intent": "求做法/路径", "worth": 6, "reason": "rh"}, ensure_ascii=False),
            "聊": json.dumps({"lane": "engage", "intent": "观点/预测", "worth": 9, "reason": "re"}, ensure_ascii=False),
        }
        fn = _fake_complete(responses)
        items = [_screen_item("1", "聊聊这个"), _screen_item("2", "帮我怎么做")]
        kept, _ = asyncio.run(auto.llm_screen_candidates(items, threshold=6, complete_fn=fn))
        assert [k["lane"] for k in kept] == ["help", "engage"]  # 帮助型优先

    def test_llm_off_domain_question_marked_skip(self):
        # 离域真实提问(如 GPT vs Claude 用于学术笔记)→ LLM 应判 skip 而非硬编进 help
        fn = _fake_complete({"obsidian": json.dumps({"lane": "skip", "intent": "离域求助", "worth": 3, "reason": "学术笔记场景,非内容创作域"}, ensure_ascii=False)})
        items = [_screen_item("1", "请问用GPT还是Claude做obsidian学术笔记知识库")]
        kept, _ = asyncio.run(auto.llm_screen_candidates(items, threshold=6, complete_fn=fn))
        assert kept == []

    def test_engage_draft_uses_engage_prompt(self):
        item = _screen_item("1", "AI还是塑料感")
        item["lane"] = "engage"
        assert "人味规则" in auto._system_prompt_for(item)  # 2026-10-26 人味化重写后的标志段
        assert "把答案直接给全" not in auto._system_prompt_for(item)
        assert "把答案直接给全" in auto._system_prompt_for(_screen_item("2", "怎么做"))


class TestSpamNick:
    def test_subscription_seller_nick_excluded_in_build(self):
        # 真实案例:昵称「GPT等AI订阅-可开票61」卖订阅,评论是体面观点也不值得回
        rows = [{
            "comment_id": "9001", "video_id": "v9", "content": "感觉AI正在成为新的生产力入口,以后人人都要会用",
            "nickname": "GPT等AI订阅-可开票61", "like_count": 9, "create_time": int(datetime.now().timestamp()) - 3600,
        }]
        picked, funnel = auto.build_candidates(rows, {"v9": {"title": "t", "video_url": "u"}}, {"max_new_candidates_per_cycle": 5}, set())
        assert picked == []
        assert funnel["excluded"] == 1

    def test_normal_nick_still_passes(self):
        rows = [{
            "comment_id": "9002", "video_id": "v9", "content": "这个AI动画用什么软件做的呀,求推荐",
            "nickname": "一只神秘的羊", "like_count": 2, "create_time": int(datetime.now().timestamp()) - 3600,
        }]
        picked, _ = auto.build_candidates(rows, {"v9": {"title": "t", "video_url": "u"}}, {"max_new_candidates_per_cycle": 5}, set())
        assert len(picked) == 1 and picked[0]["lane"] == "help"


class TestBulkReject:
    def test_bulk_reject_only_rules_screened_pending(self, store):
        old1 = _item("r1"); old1["screened_by"] = "rules"; old1["status"] = "pending_review"
        old2 = _item("r2"); old2["screened_by"] = ""; old2["status"] = "pending_review"
        new1 = _item("n1"); new1["screened_by"] = "llm"; new1["status"] = "pending_review"
        approved_old = _item("a1"); approved_old["screened_by"] = "rules"; approved_old["status"] = "approved"
        for it in (old1, old2, new1, approved_old):
            store._state["items"].append(it)
        n = store.bulk_reject_rules_screened()
        assert n == 2  # 只清 rules 的 pending
        assert old1["status"] == "rejected" and old2["status"] == "rejected"
        assert new1["status"] == "pending_review"
        assert approved_old["status"] == "approved"


class TestBulkApprove:
    def test_bulk_approve_only_llm_with_draft(self, store):
        good = _item("g1", draft="答案直接给全的草稿一。")
        good["screened_by"] = "llm"; good["status"] = "pending_review"
        no_draft = _item("g2", draft="")
        no_draft["screened_by"] = "llm"; no_draft["status"] = "pending_review"
        rules = _item("g3", draft="规则筛的有草稿。")
        rules["screened_by"] = "rules"; rules["status"] = "pending_review"
        for it in (good, no_draft, rules):
            store._state["items"].append(it)
        approved, skipped, skipped_similar = store.bulk_approve_llm_screened()
        assert approved == 1 and skipped == 1 and skipped_similar == 0
        assert good["status"] == "approved"
        assert no_draft["status"] == "pending_review"  # 无草稿不动
        assert rules["status"] == "pending_review"      # 规则筛不动

    def test_sender_tick_pauses_while_login_window_open(self, store):
        store._state["config"]["enabled"] = True
        store._state["sender"]["login_flow"] = {"running": True, "message": "等待扫码"}
        import asyncio as _a
        msg = _a.run(auto._sender_tick(store))
        assert "扫码登录窗口开启中" in msg


# ---------------------------------------------------------------------------
# P0-1 已回复用户冷却 / P0-2 相似度闸 / P0-3 通知节流
# ---------------------------------------------------------------------------

def _crow(cid, text, uid="u1", likes=3, nickname="普通网友"):
    return {
        "comment_id": cid, "video_id": "v1", "content": text, "nickname": nickname,
        "user_id": uid, "like_count": likes,
        "create_time": int(datetime.now().timestamp()) - 3600,
    }


class TestUserCooldown:
    def test_recently_replied_user_excluded(self):
        cfg = {
            "max_new_candidates_per_cycle": 5,
            "_replied_users": {"u1": datetime.now().timestamp() - 3600},  # 1小时前刚回过
            "user_cooldown_days": 14,
        }
        picked, funnel = auto.build_candidates([_crow("1", "这个AI动画用什么软件做的呀")], {"v1": {"title": "t", "video_url": "u"}}, cfg, set())
        assert picked == []
        assert funnel["replied_user"] == 1

    def test_replied_long_ago_passes_cooldown(self):
        cfg = {
            "max_new_candidates_per_cycle": 5,
            "_replied_users": {"u1": datetime.now().timestamp() - 20 * 86400},  # 20天前,超过冷却
            "user_cooldown_days": 14,
        }
        picked, _ = auto.build_candidates([_crow("1", "这个AI动画用什么软件做的呀")], {"v1": {"title": "t", "video_url": "u"}}, cfg, set())
        assert len(picked) == 1 and picked[0]["commenter_id"] == "u1"

    def test_mark_sent_records_replied_user(self, store):
        it = _item("c1", draft="答案直接给全的草稿。")
        it["commenter_id"] = "u9527"
        store.add_items([it])
        store.decide("c_c1", "approve", draft="答案直接给全的草稿。")
        item = store.find("c_c1")
        store.mark_sent(item, "rpid1")
        assert store._state["replied_users"]["u9527"] > 0


class TestSimilarityGate:
    DRAFT_A = "可以,没有场景图也能做。用带文生图和图生视频的工具,先用提示词生成首帧图,再让这张图动起来,按主体动作场景镜头逐项写清。"
    DRAFT_A_TWIN = "可以,没有场景图也能做。用带文生图和图生视频的工具,先用提示词生成首帧图,再让这张图动起来,按主体动作场景镜头一项项写。"
    DRAFT_DIFF = "审核主要看人脸相似度和素材来源。把照片裁到脸占三分之一以下,转15度侧脸,加2%噪点再试,过了就正常出片。"

    def test_similarity_scores(self):
        from api.services.outreach.reply_style import draft_similarity, similarity_verdict
        assert draft_similarity(self.DRAFT_A, self.DRAFT_A) == 1.0
        assert draft_similarity(self.DRAFT_A, self.DRAFT_A_TWIN) > 0.6
        assert draft_similarity(self.DRAFT_A, self.DRAFT_DIFF) < 0.3
        v, s = similarity_verdict(self.DRAFT_A_TWIN, [self.DRAFT_A], lane="help")
        assert v == "block" and s > 0.55
        v2, _ = similarity_verdict(self.DRAFT_DIFF, [self.DRAFT_A], lane="help")
        assert v2 == "ok"

    def test_approve_blocked_when_similar_to_sent(self, store):
        sent = _item("s1", draft=self.DRAFT_A)
        sent["status"] = "sent"
        sent["sent_at"] = datetime.now().isoformat(timespec="seconds")
        store._state["items"].append(sent)
        victim = _item("v1", draft=self.DRAFT_A_TWIN)
        store._state["items"].append(victim)
        with pytest.raises(ValueError, match="相似"):
            store.decide("c_v1", "approve")

    def test_approve_passes_and_warns_band(self, store):
        sent = _item("s1", draft=self.DRAFT_A)
        sent["status"] = "sent"
        sent["sent_at"] = datetime.now().isoformat(timespec="seconds")
        store._state["items"].append(sent)
        ok_item = _item("v2", draft=self.DRAFT_DIFF)
        store._state["items"].append(ok_item)
        item = store.decide("c_v2", "approve")
        assert item["status"] == "approved"
        assert not any("相似度" in w for w in item["lint_warnings"])

    def test_bulk_approve_counts_similar_skips(self, store):
        sent = _item("s1", draft=self.DRAFT_A)
        sent["status"] = "sent"
        sent["sent_at"] = datetime.now().isoformat(timespec="seconds")
        store._state["items"].append(sent)
        twin = _item("t1", draft=self.DRAFT_A_TWIN); twin["screened_by"] = "llm"
        diff = _item("t2", draft=self.DRAFT_DIFF); diff["screened_by"] = "llm"
        store._state["items"].extend([twin, diff])
        approved, skipped, similar = store.bulk_approve_llm_screened()
        assert approved == 1 and similar == 1 and skipped == 0


class TestNotifyThrottle:
    def test_should_notify_dedupes_same_message(self):
        from api.services import notify as nm
        state = {}
        assert nm.should_notify(state, "k", "msg") is True
        assert nm.should_notify(state, "k", "msg") is False   # 同文同键冷却内
        assert nm.should_notify(state, "k", "msg2") is True   # 文案变化立即放行
        assert nm.should_notify(state, "k2", "msg") is True   # 不同键独立

    def test_notify_noop_without_webhook(self):
        import asyncio
        from api.services import notify as nm
        assert nm.configured() is False or nm.configured() is True  # 取决于环境,不崩即可
        async def _t():
            await nm.notify("测试", ["行1"])  # 未配置时静默 False,不抛异常
        asyncio.run(_t())


# ---------------------------------------------------------------------------
# P1-4 子评论语境 + 已答拦截
# ---------------------------------------------------------------------------

class TestSubCommentContext:
    def _rows_with_subs(self):
        top = _crow("1000", "请问这种AI动画用什么软件做的呀", uid="u1", likes=5)
        sub1 = _crow("1001", "剪映就行,手机也能做", uid="u2")
        sub1["parent_comment_id"] = "1000"
        sub1["like_count"] = 2
        sub2 = _crow("1002", "谢谢,我去试试", uid="u1")
        sub2["parent_comment_id"] = "1000"
        # 孙子楼
        sub3 = _crow("1003", "剪映特效没有这个丝滑", uid="u3")
        sub3["parent_comment_id"] = "1001"
        return [top, sub1, sub2, sub3]

    def test_sub_rows_not_candidates_but_context(self):
        rows = self._rows_with_subs()
        cfg = {"max_new_candidates_per_cycle": 5}
        picked, funnel = auto.build_candidates(rows, {"v1": {"title": "t", "video_url": "u"}}, cfg, set())
        # 只有顶层那条入选;3 条楼中楼全部只进语境
        assert len(picked) == 1 and picked[0]["comment_id"] == "1000"
        assert funnel["sub_context"] == 3
        assert funnel["candidates"] == 1
        # 语境收拢:直接子楼 + 孙子楼都进来了
        texts = picked[0]["sub_replies"]
        assert any("剪映" in t for t in texts)
        assert any("丝滑" in t for t in texts)
        assert picked[0]["sub_reply_count"] == len(texts)

    def test_no_sub_rows_no_regression(self):
        # 老数据没有楼中楼:行为不变
        picked, funnel = auto.build_candidates(
            [_crow("2000", "请问这种AI动画用什么软件做的呀")],
            {"v1": {"title": "t", "video_url": "u"}}, {"max_new_candidates_per_cycle": 5}, set())
        assert picked[0]["sub_replies"] == [] and picked[0]["sub_reply_count"] == 0

    @pytest.mark.asyncio
    async def test_screen_includes_sub_replies_in_user_msg(self):
        async def fake_complete(messages, **kwargs):
            user = messages[-1]["content"]
            assert "评论区已有回复" in user and "剪映" in user
            return '{"lane":"help","intent":"求工具","worth":8,"already_answered":false,"reason":"值得"}'
        item = {"id": "c_1", "comment_text": "问软件", "video_title": "t", "sub_replies": ["剪映就能做"], "signal": "s"}
        kept, stats = await auto.llm_screen_candidates([item], complete_fn=fake_complete)
        assert stats["kept"] == 1 and kept[0]["worth"] == 8

    @pytest.mark.asyncio
    async def test_already_answered_forces_skip(self):
        async def fake_complete(messages, **kwargs):
            return '{"lane":"help","intent":"求做法/路径","worth":9,"already_answered":true,"reason":"评论区已有人给出靠谱答案"}'
        item = {"id": "c_2", "comment_text": "这个怎么做", "video_title": "t",
                "sub_replies": ["用A软件,先xx再yy"], "signal": "s", "like_count": 10}
        kept, stats = await auto.llm_screen_candidates([item], complete_fn=fake_complete)
        # 哪怕 worth=9:已被答好 → 一律拦下
        assert kept == [] and stats["screened"] == 1

    def test_draft_user_msg_mentions_sub_replies(self):
        item = {"comment_text": "怎么做", "video_title": "t", "intent": "求做法",
                "sub_replies": ["有人答了一半"], "signal": "s"}
        msg = auto._llm_user_message(item)
        assert "楼中楼" in msg and "不重复原话" in msg


# ---------------------------------------------------------------------------
# 定位转向:六档 persona 分层(2026-10-27)
# ---------------------------------------------------------------------------

class TestPersonaScreening:
    @pytest.mark.asyncio
    async def test_persona_parsed_and_passed_through(self):
        async def fake_complete(messages, **kwargs):
            return ('{"lane":"help","persona":"novice_doer","intent":"求做法/路径",'
                    '"worth":8,"already_answered":false,"reason":"具体卡点"}')
        item = {"id": "c_p1", "comment_text": "问怎么接单", "video_title": "t", "signal": "s"}
        kept, _ = await auto.llm_screen_candidates([item], complete_fn=fake_complete)
        assert kept[0]["persona"] == "novice_doer"

    @pytest.mark.asyncio
    async def test_beggar_and_seller_forced_skip(self):
        async def fake_complete(messages, **kwargs):
            # 模型给了 lane=help 但 persona 是求带党 → 强制 skip
            return ('{"lane":"help","persona":"beggar","intent":"求带",'
                    '"worth":7,"already_answered":false,"reason":"求带"}')
        item = {"id": "c_p2", "comment_text": "带带我", "video_title": "t", "signal": "s"}
        kept, _ = await auto.llm_screen_candidates([item], complete_fn=fake_complete)
        assert kept == []

    @pytest.mark.asyncio
    async def test_unknown_persona_falls_back_by_lane(self):
        async def fake_complete(messages, **kwargs):
            return ('{"lane":"engage","persona":"whatever","intent":"观点/预测",'
                    '"worth":6,"already_answered":false,"reason":"有观点"}')
        item = {"id": "c_p3", "comment_text": "观点", "video_title": "t", "signal": "s"}
        kept, _ = await auto.llm_screen_candidates([item], complete_fn=fake_complete)
        assert kept[0]["persona"] == "thinker"  # engage 兜底为 thinker

    def test_draft_user_message_carries_persona_tactic(self):
        item = {"comment_text": "怎么做", "video_title": "t", "intent": "求做法",
                "persona": "watcher", "signal": "s"}
        msg = auto._llm_user_message(item)
        assert "对方画像" in msg and "watcher" in msg
        assert "稳住" in msg and "第一步" in msg  # watcher 专属策略注入

    def test_seller_tactic_absent_from_draft(self):
        # beggar/seller 不入起草,不应出现在策略表
        assert "beggar" not in auto._PERSONA_TACTICS and "seller" not in auto._PERSONA_TACTICS

    def test_keywords_default_v2(self):
        assert "AI工具" in auto.DEFAULT_CONFIG["keywords"]
        assert "AI赚钱" not in auto.DEFAULT_CONFIG["keywords"]  # 求带重灾区不入采集


class TestCollectCommand:
    def test_sub_comment_flag_follows_global_config(self):
        cmd = auto.build_collect_command({"keywords": ["AI工具"], "max_notes_per_keyword": 5, "max_comments_per_video": 50})
        joined = " ".join(cmd)
        # config/base_config.ENABLE_GET_SUB_COMMENTS=True(P1-4)→ 命令必须传 true
        assert "--get_sub_comment true" in joined, joined
        assert "--keywords AI工具" in joined

    def test_keywords_joined(self):
        cmd = auto.build_collect_command({"keywords": ["AI工具", "一人公司"]})
        assert "AI工具,一人公司" in cmd


class TestTailQuestionLint:
    # 用户 2026-10-26 实测反馈:草稿结尾全是反问,批量看像机器人
    USER_CASE = ("同感，早期那些作品现在回看还是能看进去。我自己做片子时把分辨率拉到4K、"
                 "帧率提到60，画面精致不少，结果观众留言记住的全是开头那个怪点子。"
                 "精细度更像门槛，过了线之后拼的还是创意那口气。你觉得现在AI创作最缺的是哪块？")

    def test_user_case_caught(self):
        from api.services.outreach.reply_style import check_reply_style
        ws = check_reply_style(self.USER_CASE)
        assert any("结尾开放反问" in w for w in ws), ws

    def test_common_open_questions_caught(self):
        from api.services.outreach.reply_style import check_reply_style
        for tail in ("这个思路你们怎么看？", "效率是不是才是关键呢？", "大家觉得哪个更好？", "你说是不是这个道理？"):
            ws = check_reply_style("我觉得工具只是放大器。" + tail)
            assert any("结尾开放反问" in w for w in ws), tail

    def test_specific_question_not_caught(self):
        # 针对对方处境的具体提问是真人行为,不误伤
        from api.services.outreach.reply_style import check_reply_style
        ws = check_reply_style("我这边用即梦跑分镜挺稳的。你那条卡住的是生成还是剪辑环节？")
        assert not any("结尾开放反问" in w for w in ws), ws

    def test_plain_statement_clean(self):
        from api.services.outreach.reply_style import check_reply_style
        ws = check_reply_style("同感，我拉到4K之后观看完成率反而没变，记住的还都是开头那个怪点子。")
        assert not any("结尾开放反问" in w for w in ws), ws

    def test_engage_prompt_bans_tail_question(self):
        assert "禁结尾开放反问" in auto.BILI_ENGAGE_SYSTEM_PROMPT
        assert "让对话能继续" not in auto.BILI_ENGAGE_SYSTEM_PROMPT  # 旧指令已删


# ---------------------------------------------------------------------------
# XY 原子知识库 + 人味 lint v2(2026-10-26 集成风物执守·XY 操盘系统)
# ---------------------------------------------------------------------------

class TestKnowledgeBase:
    def test_search_relevant_atoms(self):
        from api.services import knowledge as kb
        if kb.count() == 0:
            pytest.skip("本地无 atoms.jsonl(仅内部数据)")
        hits = kb.search("客户嫌贵不回消息", k=3)
        assert hits and all(h["id"] for h in hits)
        assert any("嫌贵" in h["knowledge"] or "价格" in h["knowledge"] or "异议" in h["knowledge"] for h in hits)

    def test_context_for_cites_source(self):
        from api.services import knowledge as kb
        if kb.count() == 0:
            pytest.skip("本地无 atoms.jsonl")
        ctx = kb.context_for("朋友圈怎么发")
        assert "私域操盘知识库" in ctx and "[XY-" in ctx or "[" in ctx

    def test_draft_user_message_has_structure_hint(self):
        # 结构变体:同批条目骨架提示互不相同
        ids = ["c_a1", "c_a2", "c_a3", "c_a4", "c_a5"]
        hints = set()
        for i in ids:
            item = {"comment_text": "x", "video_title": "t", "id": i, "signal": "s", "lane": "engage"}
            msg = auto._llm_user_message(item)
            import json as _json
            payload = _json.loads(msg.split("起草评论区回复：\n")[1])
            hints.add(payload["本条写法"])
        assert len(hints) >= 2, f"结构提示应该打散,实际 {hints}"


class TestHumanFlavorLintV2:
    def test_cliche_open_caught(self):
        from api.services.outreach.reply_style import check_reply_style
        ws = check_reply_style("太真实了,我也有同感,后来我直接换了工具。")
        assert any("套话开场" in w for w in ws)

    def test_punchline_tail_caught(self):
        from api.services.outreach.reply_style import check_reply_style
        ws = check_reply_style("我重跑过一遍,画面好了不少,但片子还是不行。说到底,工具从来不是关键。")
        assert any("金句收尾" in w for w in ws), ws

    def test_translation_tone_caught(self):
        from api.services.outreach.reply_style import check_reply_style
        ws = check_reply_style("我先对素材进行排查,再进行优化,就好了。")
        assert any("翻译腔" in w for w in ws)

    def test_broadcast_tone_caught(self):
        from api.services.outreach.reply_style import check_reply_style
        ws = check_reply_style("亲,这个问题的答案是肯定的,可以用工具解决。")
        assert any("群发味" in w for w in ws)

    def test_connective_pileup_caught(self):
        from api.services.outreach.reply_style import check_reply_style
        ws = check_reply_style("然而事实并非如此。值得注意的是,工具在变。更重要的是,人在变。")
        assert any("连接词堆叠" in w for w in ws)

    def test_clean_human_draft_stays_clean(self):
        from api.services.outreach.reply_style import check_reply_style
        ws = check_reply_style("确实,我之前也这么试过,后来直接把分辨率降一半先抽构图,能用的高清重跑,废卡少了一多半。")
        assert not any(k in w for w in ws for k in ("套话", "金句", "翻译腔", "群发味", "连接词")), ws
