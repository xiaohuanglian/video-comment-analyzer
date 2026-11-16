import asyncio
import json
from datetime import datetime

from api.services.outreach import reply_automation as auto
from api.services.outreach.collection_preflight import assess_contents, stage_command


def test_metadata_command_disables_comments_and_keeps_token():
    cmd = auto.build_collect_command({"note_urls": ["https://www.xiaohongshu.com/explore/n?xsec_token=abc"], "collect_mode": "list"}, "xhs")
    stage = stage_command(cmd, destination="/tmp/preview")
    assert stage[stage.index("--get_comment") + 1] == "false"
    assert stage[stage.index("--specified_id") + 1].endswith("xsec_token=abc")
    assert cmd[cmd.index("--get_comment") + 1] == "true"


def test_comment_command_only_fetches_selected_videos():
    cmd = stage_command(auto.build_collect_command({"keywords": ["行业"]}), targets=["BV123", "BV456"])
    assert "--keywords" not in cmd
    assert cmd[cmd.index("--type") + 1] == "detail"
    assert cmd[cmd.index("--specified_id") + 1] == "BV123,BV456"


def test_content_preflight_never_collects_unknown_or_failed():
    async def complete(messages, **kwargs):
        title = json.loads(messages[-1]["content"])["标题"]
        if title == "失败":
            raise RuntimeError("offline")
        return json.dumps({"decision": "collect" if title == "相关" else "skip", "reason": "详情证据"})
    videos = {
        "1": {"bvid": "BV1", "title": "相关", "desc": "具体内容"},
        "2": {"bvid": "BV2", "title": "无关", "desc": "无关内容"},
        "3": {"bvid": "BV3", "title": "失败", "desc": "具体内容"},
        "4": {"bvid": "BV4", "title": "空详情"},
        "5": {"title": "相关", "desc": "缺编号"},
    }
    targets, report = asyncio.run(assess_contents(videos, "账号", platform="bili", complete_fn=complete))
    assert targets == ["BV1"]
    assert [r["decision"] for r in report] == ["collect", "skip", "review", "review", "review"]


def _row(cid, likes=0):
    return {"comment_id": str(cid), "video_id": "v", "content": "请问这种动画用什么软件做的呀", "nickname": "用户", "like_count": likes, "create_time": int(datetime.now().timestamp())}


def test_rejected_top_comment_does_not_hide_other_people(tmp_path, monkeypatch):
    store = auto.AutomationStore(tmp_path / "store.json")
    store.update_config({"hot_comment_enabled": False})
    calls = []
    async def refine(items, cfg, max_candidates):
        calls.extend(i["comment_id"] for i in items)
        kept = [i for i in items if i["comment_id"] == "29"]
        for i in items:
            i["match_reason"] = "有具体接触点" if i in kept else "无接触点"
        return kept, {"screened": len(items), "kept": len(kept), "mode": "llm"}
    monkeypatch.setattr(auto, "_refine_candidates", refine)
    out = asyncio.run(auto._queue_candidates(store, [_row(i, 100-i) for i in range(30)], {}, max_candidates=1, auto_draft=False))
    assert len(calls) == 30
    assert store.items[0]["comment_id"] == "29"
    assert out["llm_screen"]["not_examined"] == 0
    assert out["llm_screen"]["rejected"] == 29


def test_recall_does_not_require_ai_keyword(tmp_path):
    rows = [_row(1)]
    rows[0]["content"] = "我每天要给客户整理一堆记录，忙一天还是做不完"
    cfg = {**auto.DEFAULT_CONFIG, "_semantic_recall": True, "_defer_video_cap": True}
    items, _ = auto.build_candidates(rows, {"v": {"title": "客户服务", "desc": "处理记录"}}, cfg, set())
    assert len(items) == 1
    assert items[0]["video_description"] == "处理记录"


def test_hot_and_reply_share_total_quota(tmp_path):
    store = auto.AutomationStore(tmp_path / "store.json")
    store.update_config({"llm_screen": False})
    from unittest.mock import patch
    async def no_refine(*args, **kwargs):
        raise AssertionError("根评论已占满，不应再筛回复")
    hot = {"comment_id": "0", "id": "hot_v", "video_id": "v", "action": "hot_comment", "status": "pending_review"}
    with patch("api.services.outreach.hot_comment.build_hot_candidates", return_value=([hot], {})), patch.object(auto, "_refine_candidates", no_refine):
        out = asyncio.run(auto._queue_candidates(store, [_row(1)], {}, max_candidates=1, auto_draft=False))
    assert out["new_candidates"] == 1


def test_cycle_stops_before_comment_requests_when_preflight_rejects(tmp_path, monkeypatch):
    from api.services.outreach import collection_preflight
    store = auto.AutomationStore(tmp_path / "store.json")
    monkeypatch.setattr(auto, "_screen_brief", lambda *args: "账号")
    monkeypatch.setattr(auto, "read_collected", lambda *a, **kw: ([], {"v": {"bvid": "BV1", "title": "无关", "desc": "内容"}}))
    async def assess(*a, **kw):
        return [], [{"video_id": "v", "decision": "skip", "reason": "无关"}]
    monkeypatch.setattr(collection_preflight, "assess_contents", assess)
    commands = []
    class Process:
        returncode = 0
        async def communicate(self):
            return b"", None
    async def create(*command, **kwargs):
        commands.append(command)
        return Process()
    monkeypatch.setattr(auto.asyncio, "create_subprocess_exec", create)
    store.update_config({"hot_comment_enabled": False, "auto_draft": False})
    store.config["audience_refresh"] = False
    result = asyncio.run(auto.run_cycle(store, campaign={"profile_id": "test", "profile_name": "测试", "reply_goal": "测试", "reply_mode": "recommend", "profile_snapshot": {}}))
    assert result["ok"]
    assert len(commands) == 1
    assert commands[0][commands[0].index("--get_comment") + 1] == "false"
    assert result["comments"] == 0


def test_direct_collection_gate_uses_details_without_requesting_platform(monkeypatch):
    from api.services.outreach import collection_preflight
    from tools import content_precheck
    monkeypatch.setenv("VC_CONTENT_PREFLIGHT", "1")
    monkeypatch.setattr(content_precheck, "_contents", {})
    monkeypatch.setattr(content_precheck, "_decisions", {})
    monkeypatch.setattr(auto, "_screen_brief", lambda: "当前产品")
    received = []
    async def assess(videos, brief, **kwargs):
        received.append(videos["n"])
        assert brief == "当前产品"
        return [], [{"decision": "skip", "reason": "详情无关", "title": "热门标题"}]
    monkeypatch.setattr(collection_preflight, "assess_contents", assess)
    content_precheck.register_content("xhs", "n", {"title": "热门标题", "desc": "真实详情", "video_url": "media.mp4", "note_url": "note?xsec_token=abc"})
    assert not asyncio.run(content_precheck.allow_comments("xhs", "n"))
    assert received[0]["desc"] == "真实详情"
    assert received[0]["video_url"] == "note?xsec_token=abc"
    assert not asyncio.run(content_precheck.allow_comments("xhs", "n"))
    assert len(received) == 1
    assert not asyncio.run(content_precheck.allow_comments("bili", "missing"))


def test_direct_crawler_does_not_request_comments_when_content_rejected(monkeypatch):
    from media_platform.bilibili.core import BilibiliCrawler
    from tools import content_precheck
    async def deny(*args):
        return False
    monkeypatch.setattr(content_precheck, "allow_comments", deny)
    crawler = object.__new__(BilibiliCrawler)
    # 未设置 bili_client：若越过内容闸调用平台会失败。
    asyncio.run(crawler.get_comments("123", asyncio.Semaphore(1)))
