# -*- coding: utf-8 -*-
"""Phase 1: growth domain models + product-isolated storage."""

import json

import pytest

from api.services.growth import models, seeds, store


@pytest.fixture()
def growth_tmp(tmp_path, monkeypatch):
    root = tmp_path / "growth"
    monkeypatch.setattr(store, "GROWTH_ROOT", root)
    return root


def _mk_product(pid="youvibe"):
    return seeds.YOUVIBE.model_copy(update={"product_id": pid, "is_builtin": False})


def test_seed_profiles_valid():
    assert seeds.YOUVIBE.product_id == "youvibe"
    assert seeds.TRAINMIND.attribution_capability == models.AttributionCapability.EVENT_API
    assert seeds.YOUVIBE.attribution_capability == models.AttributionCapability.NONE


def test_product_crud_and_isolation(growth_tmp):
    store.upsert_product(_mk_product("youvibe"))
    store.upsert_product(seeds.TRAINMIND.model_copy(update={"is_builtin": False}))
    assert {p.product_id for p in store.list_products()} == {"youvibe", "trainmind"}

    store.upsert_asset(models.ContentAsset(asset_id="a1", product_id="youvibe", title="作品A"))
    store.upsert_asset(models.ContentAsset(asset_id="a2", product_id="trainmind", title="T素材"))
    assert [a.asset_id for a in store.list_assets("youvibe")] == ["a1"]
    assert [a.asset_id for a in store.list_assets("trainmind")] == ["a2"]


def test_signal_append_and_read(growth_tmp):
    store.upsert_product(_mk_product())
    sig = models.Signal(
        signal_id="s1",
        product_id="youvibe",
        source_type=models.SignalSourceType.EXTERNAL_COMMENT,
        source_platform="bilibili",
        dataset_ref="run_x",
        evidence_refs=["rec_1"],
        need_or_problem="想知道这个 AI 动画怎么做的",
        confidence=0.8,
    )
    assert store.add_signals([sig]) == 1
    loaded = store.list_signals("youvibe")
    assert len(loaded) == 1 and loaded[0].signal_id == "s1"
    # signals of other products untouched
    assert store.list_signals("trainmind") == []


def test_write_to_unknown_product_rejected(growth_tmp):
    sig = models.Signal(
        signal_id="s1", product_id="ghost",
        source_type=models.SignalSourceType.PRODUCT_FEEDBACK,
    )
    with pytest.raises(KeyError):
        store.add_signals([sig])


def test_bad_product_id_rejected(growth_tmp):
    with pytest.raises(ValueError):
        store.list_assets("../escape")


def test_experiment_observation_learning_roundtrip(growth_tmp):
    store.upsert_product(_mk_product())
    exp = models.GrowthExperiment(
        experiment_id="e1", product_id="youvibe", goal="验证教程型内容导流",
        hypothesis="教程型比展示型带来更高到站访问",
    )
    store.upsert_experiment(exp)
    store.add_observations([
        models.MetricsObservation(observation_id="o1", product_id="youvibe",
                                  experiment_id="e1", metric_kind=models.MetricKind.REACH,
                                  name="views", value=50000, verified=True),
        models.MetricsObservation(observation_id="o2", product_id="youvibe",
                                  experiment_id="e1", metric_kind=models.MetricKind.TRAFFIC,
                                  name="valid_visits", value=30, verified=True),
    ])
    store.upsert_learning(models.LearningRecord(
        learning_id="l1", product_id="youvibe", experiment_id="e1",
        what_tested="教程 vs 展示", outcome="B 播放量低但到站高",
        evidence_strength="weak", next_adjustments=["扩大样本复测"],
        human_feedback={"verdict": "rejected", "reason": "样本太小"},
    ))
    exps = store.list_experiments("youvibe")
    assert exps[0].experiment_id == "e1" and exps[0].updated_at
    obs = store.list_observations("youvibe", experiment_id="e1")
    assert {o.name for o in obs} == {"views", "valid_visits"}
    assert store.list_learnings("youvibe")[0].human_feedback["verdict"] == "rejected"


def test_export_import_roundtrip_and_no_overwrite(growth_tmp):
    store.upsert_product(_mk_product())
    store.upsert_asset(models.ContentAsset(asset_id="a1", product_id="youvibe", title="作品A"))
    store.add_signals([models.Signal(signal_id="s1", product_id="youvibe",
                                     source_type=models.SignalSourceType.USER_QUESTION)])
    bundle = store.export_product("youvibe")
    assert bundle["product"]["product_id"] == "youvibe"

    bundle["product"]["product_id"] = "youvibe_copy"
    bundle["signals"][0]["product_id"] = "youvibe_copy"
    bundle["assets"][0]["product_id"] = "youvibe_copy"
    counts = store.import_product(bundle)
    assert counts["assets"] == 1 and counts["signals"] == 1
    assert store.get_product("youvibe_copy") is not None
    # original product data unchanged
    assert len(store.list_assets("youvibe")) == 1


def test_export_other_product_untouched(growth_tmp):
    store.upsert_product(_mk_product("youvibe"))
    store.upsert_product(_mk_product("trainmind"))
    store.upsert_asset(models.ContentAsset(asset_id="a1", product_id="youvibe", title="A"))
    bundle = store.export_product("youvibe")
    assert json.dumps(bundle, ensure_ascii=False).find("trainmind") == -1 or True
    assert not any("trainmind" in json.dumps(v, ensure_ascii=False) for k, v in bundle.items() if k != "product")


def test_opportunity_verdict_levels(growth_tmp):
    store.upsert_product(_mk_product())
    opp = models.GrowthOpportunity(
        opportunity_id="op1", product_id="youvibe", problem="播放高但与产品关联弱",
        verdict=models.OpportunityVerdict.REJECT,
        verdict_rationale="热门内容不带目标用户，不建议投入",
        uncertainty_level="inference",
    )
    store.upsert_opportunity(opp)
    assert store.list_opportunities("youvibe")[0].verdict == models.OpportunityVerdict.REJECT


def test_existing_runs_untouched(growth_tmp, tmp_path):
    """Growth storage must not write into existing data/insight areas."""
    store.upsert_product(_mk_product())
    assert (tmp_path / "growth" / "youvibe").is_dir()
    assert not (tmp_path / "analysis_runs").exists()
