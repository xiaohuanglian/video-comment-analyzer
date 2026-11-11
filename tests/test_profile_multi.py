# -*- coding: utf-8 -*-
"""多档案：一个产品一份档案，定位/受众/口吻不混用。

背景（2026-11-11）：此前账号定位存在写死的单文件
`data/strategy/youvibe_account.json`，而分析口径另存于
`data/project_profiles.json`——两套存储、两套 ID，同一件事要填两遍；
更糟的是 `strategy.save()` 只保留白名单字段，于是"采纳场景"写入的
`target_scenarios` 被静默丢弃，接口照样返回 `{"ok": True}`。
"""

from __future__ import annotations

import json

import pytest

from api.services import strategy
from api.services.insight import paths as insight_paths
from api.services.insight import project_profiles as pp


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """把档案存储指到 tmp_path，避免污染真实 data/。"""
    monkeypatch.setattr(insight_paths, "DATA_DIR", tmp_path)
    return tmp_path


def test_first_profile_becomes_active(isolated):
    saved = strategy.save({"niche": "同城鲜花配送", "target_audience": "想送花的男性"})
    assert saved["profile_id"]
    assert pp.get_active_profile_id() == saved["profile_id"]
    assert strategy.exists() is True


def test_scenario_adopt_is_really_persisted(isolated):
    """回归：保存不能丢未知/新增字段，否则「已采纳」是假成功。"""
    strategy.save({"niche": "同城鲜花配送", "target_audience": "想送花的男性"})
    chosen = [{"name": "纪念日临时抱佛脚", "axis": "trigger", "keywords": ["纪念日"]}]
    strategy.save({**strategy.load(), "target_scenarios": chosen})

    # 重新从磁盘读（模拟刷新页面）
    fresh = strategy.load()
    assert len(fresh.get("target_scenarios") or []) == 1
    assert fresh["target_scenarios"][0]["name"] == "纪念日临时抱佛脚"


def test_two_products_do_not_share_positioning(isolated):
    """不同产品不能混用定位：改 A 不能动 B。"""
    strategy.save({"niche": "同城鲜花配送", "target_audience": "想送花的男性"}, "flower")
    strategy.save({"niche": "AI 视频教程", "target_audience": "上班族"}, "aivideo")

    flower = strategy.load("flower")
    aivideo = strategy.load("aivideo")
    assert flower["niche"] == "同城鲜花配送"
    assert aivideo["niche"] == "AI 视频教程"
    assert flower["profile_id"] == "flower"


def test_creating_profile_does_not_switch_active(isolated):
    """新建档案不应偷走当前档案——否则用户不知道自己在给谁编辑。"""
    strategy.save({"niche": "AI 视频教程", "target_audience": "上班族"}, "aivideo")
    assert pp.get_active_profile_id() == "aivideo"

    pp.upsert_profile(pp.ProjectProfile(profile_id="flower", name="花店", niche="鲜花"))
    assert pp.get_active_profile_id() == "aivideo"


def test_set_active_profile_switches(isolated):
    strategy.save({"niche": "AI 视频教程", "target_audience": "上班族"}, "aivideo")
    strategy.save({"niche": "同城鲜花配送", "target_audience": "想送花的男性"}, "flower")

    pp.set_active_profile("flower")
    assert pp.get_active_profile_id() == "flower"
    assert strategy.load()["niche"] == "同城鲜花配送"


def test_set_active_profile_rejects_unknown(isolated):
    with pytest.raises(KeyError):
        pp.set_active_profile("nope")


def test_delete_active_profile_falls_back(isolated):
    strategy.save({"niche": "A", "target_audience": "a"}, "pa")
    strategy.save({"niche": "B", "target_audience": "b"}, "pb")
    pp.set_active_profile("pa")

    assert pp.delete_profile("pa") is True
    assert pp.get_active_profile_id() == "pb"


def test_builtin_profile_is_not_reported_as_configured(isolated):
    assert strategy.load() == {}
    assert strategy.exists() is False


def test_legacy_strategy_file_is_migrated(tmp_path, monkeypatch):
    """单档案时代的文件自动变成多档案里的一个，旧文件不删。"""
    monkeypatch.setattr(insight_paths, "DATA_DIR", tmp_path)
    legacy_dir = tmp_path / "strategy"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "youvibe_account.json").write_text(
        json.dumps(
            {
                "niche": "AI 创业者,教人用 AI 赚钱",
                "target_audience": "想做副业的上班族",
                "tone_rules": ["说话直接"],
                "target_scenarios": [{"name": "旧场景"}],
                "updated_at": "2026-10-01 00:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    migrated = pp.get_profile("youvibe")
    assert migrated is not None
    assert migrated.niche.startswith("AI 创业者")
    assert migrated.target_audience == "想做副业的上班族"
    assert migrated.target_scenarios == [{"name": "旧场景"}]
    assert pp.get_active_profile_id() == "youvibe"
    # 旧文件保留，可回溯
    assert (legacy_dir / "youvibe_account.json").exists()


def test_unknown_fields_survive_roundtrip(isolated):
    """任何新字段都不该因为没加进模型就消失（插件/实验开关）。"""
    profile = pp.ProjectProfile.model_validate(
        {"profile_id": "x", "name": "x", "niche": "n", "future_flag": {"a": 1}}
    )
    pp.upsert_profile(profile)
    raw = json.loads((isolated / pp.PROFILES_FILE_NAME).read_text(encoding="utf-8"))
    stored = [p for p in raw["profiles"] if p["profile_id"] == "x"][0]
    assert stored["future_flag"] == {"a": 1}
