import asyncio
import json
from datetime import datetime

import pytest

from api.routers import automation as router
from api.services.insight.project_profiles import ProjectProfile
from api.services.outreach import reply_automation as auto
from api.services.outreach import reply_campaign as campaigns


@pytest.fixture
def products(monkeypatch):
    profiles = {name: ProjectProfile(profile_id=name, name=name, domain=f"{name}产品功能", target_audience=f"{name}受众", research_goal=f"{name}试用") for name in ("造浪", "早播")}
    monkeypatch.setattr(campaigns, "get_profile", lambda pid: profiles.get(pid))
    monkeypatch.setattr(campaigns.strategy, "load", lambda pid=None: profiles[pid or "早播"].model_dump())
    return profiles


def test_campaign_requires_explicit_product(products):
    with pytest.raises(ValueError, match="明确选择"):
        campaigns.make_campaign("")
    with pytest.raises(ValueError):
        campaigns.make_campaign("不存在")


def test_screen_and_draft_keep_original_product_after_global_switch(products, monkeypatch):
    campaign = campaigns.make_campaign("造浪", "让新手试着做出第一条内容")
    item = {**campaign, "id": "c", "video_title": "教程", "signal": "具体需要", "comment_text": "想学做视频"}
    # 全局策略读取此时已是早播；显式快照不应借用它。
    brief = auto._screen_brief(campaign)
    system = auto._system_prompt_for(item)
    user = auto._llm_user_message(item)
    for prompt in (brief, system, user):
        assert "造浪" in prompt
        assert "早播" not in prompt
    assert "让新手试着做出第一条内容" in system
    assert "不出现任何产品名" not in system
    assert "自然提一次本产品名称" in system


def test_profile_filters_do_not_guess_legacy_ownership():
    assert router._matches_profile({"profile_id": "早播"}, "早播")
    assert not router._matches_profile({"profile_id": "早播"}, "造浪")
    assert router._matches_profile({}, "__unbound__")
    assert not router._matches_profile({}, "造浪")


def test_queue_tags_product_and_can_reconsider_legacy_pending(tmp_path, products, monkeypatch):
    store = auto.AutomationStore(tmp_path / "store.json")
    store.update_config({"llm_screen": False, "hot_comment_enabled": False})
    row = {"comment_id": "1", "video_id": "v", "content": "请问这种动画用什么软件做的呀", "create_time": int(datetime.now().timestamp())}
    asyncio.run(auto._queue_candidates(store, [row], {}, max_candidates=1, auto_draft=False))
    assert len(store.items) == 1
    store.update_config({"llm_screen": True})

    async def semantic_match(items, **kwargs):
        for item in items:
            item.update(screened_by="llm", lane="help", worth=8)
        return items, {"screened": len(items), "kept": len(items), "llm_failed": 0}

    monkeypatch.setattr(auto, "llm_screen_candidates", semantic_match)
    for pid in ("造浪", "早播"):
        campaign = campaigns.make_campaign(pid)
        asyncio.run(auto._queue_candidates(store, [row], {}, max_candidates=1, auto_draft=False, campaign=campaign))
    assert len(store.items) == 3
    assert {it.get("profile_id") for it in store.items} == {None, "造浪", "早播"}
    assert len({it["id"] for it in store.items}) == 3
    assert store.items[-1]["profile_snapshot"]["target_audience"] == "早播受众"


def test_bulk_approval_only_selected_product(tmp_path, monkeypatch):
    store = auto.AutomationStore(tmp_path / "store.json")
    store._state["items"] = [{"id": pid, "profile_id": pid, "status": "pending_review", "screened_by": "llm", "draft": "草稿"} for pid in ("早播", "造浪", "")]
    calls = []
    monkeypatch.setattr(store, "decide", lambda item_id, action: calls.append(item_id) or {"id": item_id})
    assert store.bulk_approve_llm_screened(profile_id="造浪")[0] == 1
    assert calls == ["造浪"]


def test_screening_llm_receives_fixed_product(products):
    campaign = campaigns.make_campaign("造浪")
    received = []
    async def complete(messages, **kwargs):
        received.append(messages[0]["content"])
        return json.dumps({"lane": "help", "worth": 8, "contact": "需要本产品的具体做法", "reason": "相关"})
    item = {"comment_text": "怎么做", "video_title": "视频"}
    kept, _ = asyncio.run(auto.llm_screen_candidates([item], campaign=campaign, complete_fn=complete))
    assert kept
    assert "造浪" in received[0] and "早播" not in received[0]


def test_updated_public_capabilities_invalidate_old_draft_and_task_key(products):
    old = campaigns.make_campaign('造浪')
    products['造浪'] = products['造浪'].model_copy(update={'product_verified_at': '2026-11-15'})
    assert campaigns.product_source_outdated(old)
    with pytest.raises(ValueError, match='旧依据'):
        campaigns.ensure_current_product_source(old)
    current = campaigns.make_campaign('造浪')
    assert not campaigns.product_source_outdated(current)
    assert current['campaign_key'] != old['campaign_key']
