# -*- coding: utf-8 -*-

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from unittest.mock import Mock

from api.main import app
from api.routers import data as data_router
from api.schemas import CrawlerStartRequest
from api.schemas.creator_rank import CreatorCommentRankRequest
from api.services.crawler_manager import CrawlerManager
from api.services.operation_guard import OperationCoordinator


@pytest.mark.parametrize(
    "path",
    ["/tmp/comments", "../comments", "./output/comments", "data/../private"],
)
def test_crawler_rejects_output_outside_data(path):
    with pytest.raises(ValidationError):
        CrawlerStartRequest(platform="bili", specified_ids="BV1test", save_data_path=path)


def test_crawler_normalizes_safe_data_path():
    request = CrawlerStartRequest(
        platform="bili",
        specified_ids="BV1test",
        save_data_path="data/comments/project-a",
    )
    assert request.save_data_path == "./data/comments/project-a"


def test_crawler_build_command_supports_multi_specified_ids():
    request = CrawlerStartRequest(
        platform="bili",
        specified_ids="BV1aaa,BV1bbb",
        max_notes_count=2,
        split_by_video=True,
    )
    command = CrawlerManager()._build_command(request)
    idx = command.index("--specified_id")
    assert command[idx + 1] == "BV1aaa,BV1bbb"
    assert "--split_by_video" in command
    assert command[command.index("--split_by_video") + 1] == "true"


    request = CrawlerStartRequest(
        platform="bili",
        specified_ids="BV1test",
        cookies="SESSDATA=secret",
    )
    command = CrawlerManager()._build_command(request)
    assert "--cookies" not in command
    assert "SESSDATA=secret" not in command


@pytest.mark.asyncio
async def test_operation_coordinator_mutually_excludes_rank_and_crawl():
    coordinator = OperationCoordinator()
    assert await coordinator.try_acquire("rank") is True
    assert await coordinator.try_acquire("crawl") is False
    await coordinator.release("rank")
    assert await coordinator.try_acquire("crawl") is True


def test_creator_scan_defaults_to_full_catalog():
    request = CreatorCommentRankRequest(platform="bili", creator_url="https://space.bilibili.com/1")
    assert request.scan_all is True
    assert request.max_videos == 0


def test_platform_capability_matrix_is_exposed():
    response = TestClient(app).get("/api/config/platforms")
    assert response.status_code == 200
    platforms = {item["value"]: item for item in response.json()["platforms"]}
    assert platforms["xhs"]["engagement_metric"] == "点赞"
    assert platforms["wb"]["engagement_metric"] == "转发"
    assert platforms["bili"]["content_term"] == "视频"


def test_csv_preview_is_limited_and_reports_total(tmp_path, monkeypatch):
    csv_file = tmp_path / "comments.csv"
    csv_file.write_text("id,content\n1,first\n2,second\n3,third\n", encoding="utf-8")
    monkeypatch.setattr(data_router, "DATA_DIR", tmp_path)

    response = TestClient(app).get("/api/data/files/comments.csv?preview=true&limit=2")
    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert len(response.json()["data"]) == 2

    normalized = TestClient(app).get("/api/data/dataset/comments.csv?limit=2")
    assert normalized.status_code == 200
    assert normalized.json()["status"] == "ready"
    assert normalized.json()["content"]["metrics"]["comments"] == 2
    assert len(normalized.json()["comments"]) == 2


def test_stale_crawler_status_is_repaired():
    manager = CrawlerManager()
    manager.status = "running"
    manager.process = Mock()
    manager.process.poll.return_value = 0
    manager.process.returncode = 0
    manager.current_config = CrawlerStartRequest(platform="bili", specified_ids="BV1test")

    status = manager.get_status()

    assert status["status"] == "idle"
    assert status["result_kind"] == "completed"
