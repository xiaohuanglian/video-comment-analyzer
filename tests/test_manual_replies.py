"""Native records from all three platforms reach a persistent human-only shortlist."""
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from api.routers.manual_replies import router
from api.services import manual_replies as manual
from api.services.outreach import reply_automation as auto


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    manual._jobs.clear()
    monkeypatch.setattr(manual, "ROOT", tmp_path / "manual")
    bulk = tmp_path / "comments"
    bulk.mkdir()
    monkeypatch.setattr(auto, "BULK_COMMENT_DIR", bulk)
    monkeypatch.setattr(auto, "comment_dir_for", lambda p: tmp_path / f"cycle_{p}")
    stores = {p: auto.AutomationStore(tmp_path / f"sender_{p}.json", p) for p in manual.PLATFORMS}
    monkeypatch.setattr(auto, "get_store", lambda p: stores[p])
    now = int(datetime.now().timestamp())
    native = {
        "bili": ({"video_id": "123", "title": "B站教程", "video_url": "https://www.bilibili.com/video/av123"}, {"video_id": "123"}),
        "dy": ({"aweme_id": "234", "desc": "抖音教程", "aweme_url": "https://www.douyin.com/video/234"}, {"aweme_id": "234"}),
        "xhs": ({"note_id": "345", "title": "小红书教程", "note_url": "https://www.xiaohongshu.com/explore/345?xsec_token=test-token"}, {"note_id": "345", "comment_url": "https://www.xiaohongshu.com/explore/345?xsec_token=test-token#comment-xhs"}),
    }
    (bulk / "contents_fixture.jsonl").write_text("\n".join(json.dumps(content) for content, _ in native.values()))
    comments = [{**row, "comment_id": p, "nickname": f"{p}用户", "content": "请问这种动画用什么软件做的呀", "create_time": now, "like_count": 5} for p, (_, row) in native.items()]
    (bulk / "comments_fixture.jsonl").write_text("\n".join(json.dumps(row) for row in comments))
    return bulk, stores


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,domain", [("bili", "bilibili.com"), ("dy", "douyin.com"), ("xhs", "xiaohongshu.com")])
async def test_three_platforms_read_filter_list_mark_and_persist(isolated, platform, domain):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        response = await client.post(f"/api/manual-replies/screen?platform={platform}", json={"mode": "rules"})
        assert response.status_code == 200
        await asyncio.gather(*list(manual._tasks))
        result = (await client.get(f"/api/manual-replies?platform={platform}")).json()
        assert result["job"]["phase"] == "completed"
        assert result["total"] == 1
        item = result["items"][0]
        assert item["comment_id"] == platform  # no mixed-platform data
        assert domain in item["reply_url"]
        assert item["match_reason"] and item["comment_text"]
        assert item["mode"] == "rules"
        assert item["draft"] == ""
        if platform == "dy":
            assert "#reply" not in item["reply_url"]
            assert "不保证直达" in item["location_hint"]
        if platform == "xhs":
            assert "xsec_token=test-token" in item["reply_url"]
        # Opening/listing alone cannot mark a reply complete.
        assert (await client.get(f"/api/manual-replies?platform={platform}")).json()["counts"]["pending"] == 1
        done = await client.post(f"/api/manual-replies/{item['id']}/mark?platform={platform}", json={"status": "done"})
        assert done.json()["status"] == "done"
        assert manual.records(platform).load()[0]["status"] == "done"
        await manual.screen(platform, "rules", None, 30, 30)
        assert len(manual.records(platform).load()) == 1  # re-screen never recreates handled records
        restored = await client.post(f"/api/manual-replies/{item['id']}/mark?platform={platform}", json={"status": "pending"})
        assert restored.json()["status"] == "pending"
        assert isolated[1][platform].items == []  # never enters automated sender store
        assert isolated[1][platform].next_approved() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["bili", "dy", "xhs"])
async def test_ai_business_matching_does_not_require_a_draft(isolated, monkeypatch, platform):
    from api.services import llm

    async def complete(messages, **kwargs):
        assert "测试业务" in messages[0]["content"]
        return json.dumps({"lane": "help", "worth": 9, "reason": "对方询问动画制作软件，与业务相关", "persona": "novice_doer"})
    monkeypatch.setattr(llm, "complete", complete)
    draft = AsyncMock(side_effect=AssertionError("must not draft"))
    monkeypatch.setattr(auto, "draft_with_llm", draft)
    campaign = {"profile_id": "test", "profile_name": "测试业务", "reply_goal": "帮助学习动画", "profile_snapshot": {"domain": "动画教程", "target_audience": "新手"}}
    await manual.screen(platform, "ai", campaign, 30, 30)
    item = manual.records(platform).load()[0]
    assert item["worth"] == 9
    assert item["profile_id"] == "test"
    assert item["mode"] == "ai"
    assert item["draft"] == ""
    draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_failure_is_not_reported_as_success(isolated, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise auto.LlmScreenUnavailable("连接失败")
    monkeypatch.setattr(auto, "llm_screen_candidates", unavailable)
    await manual.screen("dy", "ai", {"profile_id": "test"}, 30, 30)
    assert manual.job_status("dy")["phase"] == "failed"
    assert "连接失败" in manual.job_status("dy")["message"]
    assert manual.records("dy").load() == []


@pytest.mark.asyncio
async def test_empty_source_and_request_validation_are_actionable(isolated):
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        assert (await client.post("/manual-replies/screen?platform=unknown", json={"mode": "rules"})).status_code == 422
        assert (await client.post("/manual-replies/screen", json={"mode": "rules", "limit": 0})).status_code == 422
        assert (await client.post("/manual-replies/screen", json={"mode": "ai"})).status_code == 400
        assert (await client.post("/manual-replies/not-found/mark", json={"status": "done"})).status_code == 404
    (isolated[0] / "comments_fixture.jsonl").unlink()
    await manual.screen("bili", "rules", None, 30, 30)
    assert "先到“采集评论”" in manual.job_status("bili")["message"]


def test_wrong_platform_links_cannot_leak_to_manual_list():
    dy = manual.reply_location({"platform": "dy", "video_id": "234", "comment_id": "1", "video_url": "javascript:alert(1)"})
    assert dy["reply_url"] == "https://www.douyin.com/video/234"
    xhs = manual.reply_location({"platform": "xhs", "video_id": "345", "comment_id": "2", "comment_url": "https://evil.example/test"})
    assert xhs["reply_url"] == "https://www.xiaohongshu.com/explore/345"


@pytest.mark.asyncio
async def test_manually_replied_comment_is_not_reselected_for_another_business(isolated, monkeypatch):
    await manual.screen("bili", "rules", None, 30, 30)
    item = manual.records("bili").load()[0]
    manual.mark("bili", item["id"], "done")
    async def must_not_call(*args, **kwargs):
        raise AssertionError("already replied comment must not reach AI")
    monkeypatch.setattr(auto, "llm_screen_candidates", must_not_call)
    await manual.screen("bili", "ai", {"profile_id": "another"}, 30, 30)
    assert manual.job_status("bili")["phase"] == "completed"
    assert manual.job_status("bili")["summary"]["added"] == 0
    assert len(manual.records("bili").load()) == 1
