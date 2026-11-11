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
    """
    from api.services import costs

    monkeypatch.setattr(costs, "COSTS_DIR", tmp_path / "costs")
    monkeypatch.setattr(costs, "LEDGER_FILE", tmp_path / "costs" / "ledger.jsonl")
