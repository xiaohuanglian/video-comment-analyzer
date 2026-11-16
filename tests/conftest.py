"""
Pytest configuration and shared fixtures
"""

import sys
from pathlib import Path

import pytest

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def project_root_path():
    """Return project root path"""
    return project_root


@pytest.fixture
def sample_xhs_note():
    """Sample Xiaohongshu note data for testing"""
    return {
        "note_id": "test_note_123",
        "type": "normal",
        "title": "Test Title",
        "desc": "This is a test description",
        "video_url": "",
        "time": 1700000000,
        "last_update_time": 1700000000,
        "user_id": "user_123",
        "nickname": "Test User",
        "avatar": "https://example.com/avatar.jpg",
        "liked_count": 100,
        "collected_count": 50,
        "comment_count": 25,
        "share_count": 10,
        "ip_location": "Shanghai",
        "image_list": "https://example.com/img1.jpg,https://example.com/img2.jpg",
        "tag_list": "test,programming,Python",
        "note_url": "https://www.xiaohongshu.com/explore/test_note_123",
        "source_keyword": "test keyword",
        "xsec_token": "test_token_123"
    }


@pytest.fixture
def sample_xhs_comment():
    """Sample Xiaohongshu comment data for testing"""
    return {
        "comment_id": "comment_123",
        "create_time": 1700000000,
        "ip_location": "Beijing",
        "note_id": "test_note_123",
        "content": "This is a test comment",
        "user_id": "user_456",
        "nickname": "Comment User",
        "avatar": "https://example.com/avatar2.jpg",
        "sub_comment_count": 5,
        "pictures": "",
        "parent_comment_id": 0,
        "like_count": 15
    }


@pytest.fixture
def sample_xhs_creator():
    """Sample Xiaohongshu creator data for testing"""
    return {
        "user_id": "creator_123",
        "nickname": "Creator Name",
        "gender": "Female",
        "avatar": "https://example.com/creator_avatar.jpg",
        "desc": "This is the creator bio",
        "ip_location": "Guangzhou",
        "follows": 500,
        "fans": 10000,
        "interaction": 50000,
        "tag_list": '{"profession": "Designer", "interest": "Photography"}'
    }


@pytest.fixture(autouse=True)
def _isolate_real_state_files(tmp_path, monkeypatch):
    """测试不许写真实台账/状态文件。

    踩过的坑：`test_llm_config.py` 用一个假 AsyncClient 调 `llm.complete`，
    那是真跑通了完整调用路径——包括 `costs.record()`，于是每跑一次全量测试，
    `data/costs/ledger.jsonl` 就多几行 `feature=unknown/model=m` 的假记录，
    混在真实消耗里。台账是「只记账不限制」的审计数据，被污染就看不出真实花费了。

    同类的还有两个 crawl guard 状态文件（`cache/crawl_guard/` 已 gitignore，
    但污染的是开发机真实状态）：
    - `cooldowns.json`：测试撞一次 461 就会给 xhs 落 12 小时冷却，
      跑完测试本地采集直接被自己的测试拦住。
    - `xhs_search_budget.json` / `dy_search_budget.json`：每跑一次测试就消耗
      「今天还能搜几次」的额度（抖音 2026-11-12 接入同一套预算）。
    """
    from api.services import costs
    from tools import crawl_pacing as cp
    from tools import crawl_safety as cs
    from tools import xhs_safety as xs

    monkeypatch.setattr(costs, "COSTS_DIR", tmp_path / "costs")
    monkeypatch.setattr(costs, "LEDGER_FILE", tmp_path / "costs" / "ledger.jsonl")

    # 模型网关配置（data/model_settings.json）：开发机上有一份真 key。
    # 2026-11-13 起洞察路由的 key 解析会回落到持久化配置，不隔离的话
    # 「无 key 必须 400」那条红线测试会读到真实 key 而失败（而且测试结果
    # 会随开发机状态变）。隔离成空文件 = 「这个进程什么都没配」。
    from api.services import model_settings as _model_settings

    monkeypatch.setattr(_model_settings, "SETTINGS_PATH", tmp_path / "model_settings.json")
    # 环境变量也得清：开发机的 shell 里可能已经 export 了真 key，那会带进整个
    # 测试进程（pytest 先在收集阶段 import 所有测试模块，早于任何 fixture）。
    # 洞察路由会回落到环境变量，「无 key 必须 400」的红线否则会随开发机状态飘。
    for _var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(_var, raising=False)

    cp.reset_cooldown_store(cp.CooldownStore(tmp_path / "cooldowns.json"))
    # xhs_safety 现在只是 crawl_safety 的门面，reset_search_budget 是同一份实现；
    # 但两边都要显式重置，否则只测其中一边时另一边的单例会带着真实路径进测试。
    xs.reset_search_budget(cs.SearchBudget(tmp_path / "search_budget.json", platform="xhs"))
    cs.reset_search_budget(cs.SearchBudget(tmp_path / "dy_search_budget.json", platform="dy"))
    try:
        yield
    finally:
        cp.reset_cooldown_store(None)
        xs.reset_search_budget(None)
        cs.reset_search_budget(None)
