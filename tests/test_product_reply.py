import asyncio
import json

from api.services.outreach.product_reply import CHECKS, draft_product_reply


def item():
    return {"profile_id": "造浪", "profile_name": "YouVibe", "reply_mode": "recommend", "comment_text": "组织不出来要提问的语言措辞", "video_title": "入门", "profile_snapshot": {"product_offerings": [{"name": "学习提示词、Skill 和教程"}]}}


def proposal():
    return {"decision": "reply", "need_quote": "组织不出来", "matched_offering": "学习提示词、Skill 和教程", "standalone_value": "先写想要的结果和已有材料。", "bridge_reason": "需要学习如何组织提示词", "draft": "先写想要的结果和已有材料。YouVibe 有提示词与教程，可以找类似任务的写法作参考。"}


def test_grounded_product_reply_requires_independent_review():
    calls = []

    async def complete(messages, **kwargs):
        calls.append(kwargs["feature"])
        return json.dumps(proposal() if len(calls) == 1 else {"verdict": "pass", **{key: True for key in CHECKS}, "reason": "提示词学习对应表达困难"})

    row = item()
    assert "YouVibe" in asyncio.run(draft_product_reply(row, complete))
    assert calls == ["automation.product_draft", "automation.product_draft_review"]
    assert row["draft_review"]["status"] == "passed"


def test_generic_chat_is_skipped_instead_of_filling_a_quota():
    async def complete(*args, **kwargs):
        return json.dumps({"decision": "skip", "reason": "对加密货币的观点没有产品推荐理由"})

    row = item()
    assert asyncio.run(draft_product_reply(row, complete)) == ""
    assert row["draft_review"]["status"] == "skipped"


def test_fabricated_experience_never_becomes_a_usable_draft():
    async def complete(*args, **kwargs):
        return json.dumps({**proposal(), "draft": "先写想要的结果和已有材料。我之前也用过 YouVibe，帮了300人。"})

    row = item()
    assert asyncio.run(draft_product_reply(row, complete)) == ""
    assert "亲身经历" in row["draft_review"]["reason"]


def test_critic_can_reject_a_fluent_but_unsupported_recommendation():
    async def complete(messages, **kwargs):
        if kwargs["feature"] == "automation.product_draft":
            return json.dumps(proposal())
        return json.dumps({"verdict": "skip", "product_supported": False, "issues": ["社区没有为用户代部署的服务"]})

    row = item()
    assert asyncio.run(draft_product_reply(row, complete)) == ""
    assert row["draft_review"]["status"] == "blocked"


def test_model_failure_is_visible_and_does_not_publish_unreviewed_text():
    async def complete(*args, **kwargs):
        raise RuntimeError("secret-gateway-token")

    row = item()
    assert asyncio.run(draft_product_reply(row, complete)) == ""
    assert "secret" not in row["draft_review"]["reason"]
    assert row["draft_review"]["status"] == "unavailable"


def test_source_audit_expires_when_original_draft_changes():
    from api.services.outreach.product_reply import audit_basis
    row = {**item(), 'id': '1', 'draft': '旧稿'}
    assert audit_basis(row) != audit_basis({**row, 'draft': '人工新稿'})


def test_failed_redraft_cannot_approve_the_unchanged_old_copy(tmp_path):
    import pytest
    from api.services.outreach.reply_automation import AutomationStore
    store = AutomationStore(tmp_path / 'store.json')
    store._state['items'] = [{'id': '1', 'status': 'pending_review', 'draft': '先前旧稿', 'draft_review': {'status': 'blocked'}}]
    with pytest.raises(ValueError, match='未通过质检'):
        store.decide('1', 'approve')
    store.update_draft('1', '已按实际需求改写', source='manual')
    assert store.find('1')['draft_review']['status'] == 'manual'
