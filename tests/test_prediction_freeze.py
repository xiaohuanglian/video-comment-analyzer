# -*- coding: utf-8 -*-
"""prediction_freeze：两段式不可变冻结（P0-A 创意包冻结 P0-B / 裁决1/2/3）。"""

from __future__ import annotations

import json

import pytest

from api.services.growth import prediction_freeze as pf
from api.services.growth import store as gstore
from api.services.growth.models import ExperimentStatus, GrowthExperiment


@pytest.fixture()
def tmp_product(tmp_path, monkeypatch):
    monkeypatch.setattr(gstore, "GROWTH_ROOT", tmp_path, raising=True)
    from api.services.growth.models import ProductProfile

    gstore.upsert_product(ProductProfile(product_id="p1", name="t"))
    exp = GrowthExperiment(
        experiment_id="e1", product_id="p1", status=ExperimentStatus.PLANNED,
        content_variants=[{"variant_id": "v1", "type": "利益冲突型", "title": "测试"}],
    )
    gstore.upsert_experiment(exp)
    return "p1", "e1", "v1"


def _payload(**over):
    p = {
        "creative_package": {
            "topic": "AI视频真实成本", "target_audience": "泛小白", "user_lifecycle": "尝试",
            "topic_lifecycle": "seasonal", "title": "我花100元做AI视频，发现被骗了",
            "cover_hypothesis": "100元 vs 8毛 数字冲突", "hook": "利益冲突+数字反差",
            "format": "漫画图文对比", "content_structure": "成本拆解→真实账单→便宜做法",
            "cta": "主页昵称承接", "tags": ["AI视频", "成本"], "platform": ["bilibili", "xiaohongshu"],
            "account_id": "bili_old_main", "account_state": "日常活跃",
        },
        "predictions": {
            "ctr": {"expected_range": [0.04, 0.12], "failure_threshold": 0.03, "success_threshold": 0.08},
        },
        "counterfactuals": {"success": "验证利益冲突标题假设", "failure": "推翻标题假设但不动选题结论"},
        "calibration_bet": "如果 CTR >= 8%，支持利益冲突型标题撬动点击的假设",
        "reasoning_snapshot": "成本_价格聚类 169条/周；数字冲突是已验证钩子",
        "evidence_snapshot": {"opportunity_id": "aud-opp-成本_价格-20261013", "avs": 0.31},
    }
    p.update(over)
    return p


class TestFreeze:
    def test_freeze_ok_and_idempotent_reject(self, tmp_product):
        pid, eid, vid = tmp_product
        frozen = pf.freeze_predictions(pid, eid, vid, _payload())
        assert frozen["payload_hash"] and frozen["frozen_at"]
        assert frozen["confidence"] == "very_low" and frozen["calibration_samples"] == 0  # N=0 裁决3
        assert frozen["model_version"] == "v1"
        with pytest.raises(pf.FreezeError, match="禁止再冻结"):
            pf.freeze_predictions(pid, eid, vid, _payload())  # 重复冻结拒绝

    def test_missing_creative_fields_rejected(self, tmp_product):
        pid, eid, vid = tmp_product
        bad = _payload()
        bad["creative_package"].pop("cover_hypothesis")
        with pytest.raises(pf.FreezeError, match="cover_hypothesis"):
            pf.freeze_predictions(pid, eid, vid, bad)

    def test_threshold_logic_rejected(self, tmp_product):
        pid, eid, vid = tmp_product
        bad = _payload()
        bad["predictions"]["ctr"] = {"expected_range": [0.04, 0.12], "failure_threshold": 0.10, "success_threshold": 0.05}
        with pytest.raises(pf.FreezeError, match="failure_threshold"):
            pf.freeze_predictions(pid, eid, vid, bad)

    def test_dist_optional_but_must_sum_100(self, tmp_product):
        pid, eid, vid = tmp_product
        # dist 不填 → 通过（裁决3：N=0 不强制概率分布）
        pf.freeze_predictions(pid, eid, vid, _payload())
        # redo 变体验证 dist 校验
        exp = [e for e in gstore.list_experiments(pid) if e.experiment_id == eid][0]
        exp.content_variants.append({"variant_id": "v1_redo1", "type": "redo"})
        gstore.upsert_experiment(exp)
        bad = _payload()
        bad["predictions"]["ctr"]["dist"] = [{"bucket": "<3%", "p": 0.6}, {"bucket": ">=3%", "p": 0.2}]
        with pytest.raises(pf.FreezeError, match="加总"):
            pf.freeze_predictions(pid, eid, "v1_redo1", bad)

    def test_bet_required(self, tmp_product):
        pid, eid, vid = tmp_product
        with pytest.raises(pf.FreezeError, match="calibration_bet"):
            pf.freeze_predictions(pid, eid, vid, _payload(calibration_bet="  "))

    def test_store_guard_blocks_tamper_via_upsert(self, tmp_product):
        pid, eid, vid = tmp_product
        pf.freeze_predictions(pid, eid, vid, _payload())
        exp = [e for e in gstore.list_experiments(pid) if e.experiment_id == eid][0]
        v = exp.content_variants[0]
        v["_frozen"]["predictions"]["ctr"]["expected_range"] = [0.05, 0.13]  # 事后改预测
        with pytest.raises(ValueError, match="已冻结"):
            gstore.upsert_experiment(exp)

    def test_redo_variant_allowed_and_old_preserved(self, tmp_product):
        pid, eid, vid = tmp_product
        pf.freeze_predictions(pid, eid, vid, _payload())
        exp = [e for e in gstore.list_experiments(pid) if e.experiment_id == eid][0]
        exp.content_variants.append({"variant_id": "v1_redo1", "type": "redo"})
        gstore.upsert_experiment(exp)  # 新变体放行
        pf.freeze_predictions(pid, eid, "v1_redo1", _payload(calibration_bet="重做后的新赌注"))
        exp2 = [e for e in gstore.list_experiments(pid) if e.experiment_id == eid][0]
        assert len(exp2.content_variants) == 2
        assert all(v.get("_frozen") for v in exp2.content_variants)  # 旧记录保留


class TestPublishBinding:
    def test_bind_requires_freeze_first(self, tmp_product):
        pid, eid, vid = tmp_product
        with pytest.raises(pf.FreezeError, match="先 freeze"):
            pf.bind_published_asset(pid, eid, vid, {"publish_time": "2026-10-15 20:00", "account_state_version": "s1", "creative_asset_hash": "abc123"})

    def test_bind_ok_then_immutable(self, tmp_product):
        pid, eid, vid = tmp_product
        pf.freeze_predictions(pid, eid, vid, _payload())
        rec = pf.bind_published_asset(pid, eid, vid, {
            "publish_time": "2026-10-15 20:00", "account_state_version": "bili_old_lv4_daily",
            "creative_asset_hash": "sha256:9f2a", "url": "https://b23.tv/xxx",
        })
        assert rec["binding_hash"]
        with pytest.raises(pf.FreezeError, match="不可改"):
            pf.bind_published_asset(pid, eid, vid, {
                "publish_time": "2026-10-15 21:00", "account_state_version": "s2", "creative_asset_hash": "zzz",
            })
        exp = [e for e in gstore.list_experiments(pid) if e.experiment_id == eid][0]
        exp.content_variants[0]["_publish_binding"]["creative_asset_hash"] = "tampered"
        with pytest.raises(ValueError, match="发布绑定不可修改"):
            gstore.upsert_experiment(exp)

    def test_binding_requires_asset_hash(self, tmp_product):
        pid, eid, vid = tmp_product
        pf.freeze_predictions(pid, eid, vid, _payload())
        with pytest.raises(pf.FreezeError, match="creative_asset_hash"):
            pf.bind_published_asset(pid, eid, vid, {"publish_time": "t", "account_state_version": "s1"})


class TestIntegrityVerify:
    def test_tamper_detected_by_hash(self, tmp_product, tmp_path):
        pid, eid, vid = tmp_product
        pf.freeze_predictions(pid, eid, vid, _payload())
        # 绕过 store 直接改磁盘文件（模拟手改 json）
        path = tmp_path / "p1" / "experiments.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("items", [])
        for it in items:
            if it.get("experiment_id") == eid:
                it["content_variants"][0]["_frozen"]["calibration_bet"] = "事后改的赌注"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        report = pf.verify_integrity(pid, eid)
        assert report["variants"][0]["tampered"] is True
        assert report["variants"][0]["payload_ok"] is False

    def test_clean_pass(self, tmp_product):
        pid, eid, vid = tmp_product
        pf.freeze_predictions(pid, eid, vid, _payload())
        pf.bind_published_asset(pid, eid, vid, {
            "publish_time": "2026-10-15 20:00", "account_state_version": "s1", "creative_asset_hash": "h1",
        })
        report = pf.verify_integrity(pid, eid)
        v = report["variants"][0]
        assert v["tampered"] is False and v["payload_ok"] and v["binding_ok"]


class TestCalibrationSamples:
    def test_confidence_upgrades_with_pool(self, tmp_product):
        # 冻结+绑定+观测 3 个样本 → confidence 应仍 very_low/low 档（样本纪律）
        pid, eid, vid = tmp_product
        from api.services.growth.models import MetricsObservation
        from api.services.growth.models import MetricKind

        pf.freeze_predictions(pid, eid, vid, _payload())
        pf.bind_published_asset(pid, eid, vid, {
            "publish_time": "2026-10-15 20:00", "account_state_version": "s1", "creative_asset_hash": "h1",
        })
        gstore.add_observations([MetricsObservation(
            observation_id="o1", product_id=pid, experiment_id=eid, metric_kind=MetricKind.REACH,
            name="ctr", value=0.06, collected_at="2026-10-16",
        )])
        assert pf._count_calibration_samples(pid) == 1
        # 新变体的 confidence 派生自池子
        exp = [e for e in gstore.list_experiments(pid) if e.experiment_id == eid][0]
        exp.content_variants.append({"variant_id": "v2", "type": "b"})
        gstore.upsert_experiment(exp)
        frozen = pf.freeze_predictions(pid, eid, "v2", _payload(calibration_bet="第二个赌注"))
        assert frozen["calibration_samples"] == 1
        assert frozen["confidence"] == "low"  # 1 个样本 → low（方向感优于绝对数字）
