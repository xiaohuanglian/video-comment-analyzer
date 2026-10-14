# -*- coding: utf-8 -*-
"""promotion：Discovery→Holdout 晋升协议（裁决 5/6/7）。"""

from __future__ import annotations

import pytest

from api.services.growth import promotion as pr
from api.services.growth import store as gstore
from api.services.growth.models import LearningRecord, ProductProfile


@pytest.fixture()
def tmp_product(tmp_path, monkeypatch):
    monkeypatch.setattr(gstore, "GROWTH_ROOT", tmp_path, raising=True)
    gstore.upsert_product(ProductProfile(product_id="p1", name="t"))
    return "p1"


def _hyp(**over):
    base = dict(
        learning_id="h1", product_id="p1", what_tested="利益冲突标题 CTR 假设",
        outcome="待验证", stage="hypothesis", learning_scope="creative",
        evidence_requirement=3, discovery_window_end="2026-10-14",
        model_target="creative.title_guidelines",
    )
    base.update(over)
    return LearningRecord(**base)


class TestRegister:
    def test_requires_closed_window(self, tmp_product):
        with pytest.raises(pr.PromotionError, match="尚未封闭"):
            pr.register_hypothesis(_hyp(discovery_window_end="2099-01-01"))

    def test_requires_evidence_requirement(self, tmp_product):
        with pytest.raises(pr.PromotionError, match="evidence_requirement"):
            pr.register_hypothesis(_hyp(evidence_requirement=0))

    def test_ok(self, tmp_product):
        lr = pr.register_hypothesis(_hyp())
        assert lr.stage == "hypothesis" and lr.learning_scope == "creative"


class TestInSampleGuard:
    """裁决核心：发现假设的数据没资格验证假设。"""

    def test_in_sample_outcomes_rejected(self, tmp_product):
        pr.register_hypothesis(_hyp())
        outcomes = [
            # 3 条"一致"但都发生在发现窗口内 → 全部拒收
            {"experiment_id": "e1", "collected_at": "2026-10-13", "direction": 1},
            {"experiment_id": "e2", "collected_at": "2026-10-14", "direction": 1},
            {"experiment_id": "e3", "collected_at": "2026-10-10", "direction": 1},
        ]
        r = pr.validate_hypothesis("p1", "h1", outcomes)
        assert r["status"] == "awaiting_holdout"
        assert r["rejected_in_sample"] == 3 and r["consistent"] == 0

    def test_future_holdout_counts(self, tmp_product):
        pr.register_hypothesis(_hyp())
        outcomes = [
            {"experiment_id": "e1", "collected_at": "2026-10-13", "direction": 1},  # in-sample 拒收
            {"experiment_id": "e4", "collected_at": "2026-10-20", "direction": 1},
            {"experiment_id": "e5", "collected_at": "2026-10-27", "direction": 1},
            {"experiment_id": "e6", "collected_at": "2026-11-03", "direction": 1},
        ]
        r = pr.validate_hypothesis("p1", "h1", outcomes)
        assert r["status"] == "promote_ready"
        assert r["consistent"] == 3 and r["rejected_in_sample"] == 1

    def test_counterexample_blocks(self, tmp_product):
        pr.register_hypothesis(_hyp())
        outcomes = [
            {"experiment_id": "e4", "collected_at": "2026-10-20", "direction": 1},
            {"experiment_id": "e5", "collected_at": "2026-10-27", "direction": 1},
            {"experiment_id": "e6", "collected_at": "2026-11-03", "direction": 1},
            {"experiment_id": "e7", "collected_at": "2026-11-10", "direction": -1},  # 强反例
        ]
        r = pr.validate_hypothesis("p1", "h1", outcomes)
        assert r["status"] == "awaiting_holdout" and r["counterexamples"] == 1

    def test_promote_gate(self, tmp_product):
        pr.register_hypothesis(_hyp())
        with pytest.raises(pr.PromotionError, match="拒绝晋升"):
            pr.promote("p1", "h1", [])  # 未验证不可晋升
        with pytest.raises(pr.PromotionError, match="拒绝晋升"):
            pr.promote("p1", "h1", [
                {"collected_at": "2026-10-13", "direction": 1},  # in-sample 不算数
            ])
        outcomes = [
            {"collected_at": f"2026-11-{d:02d}", "direction": 1} for d in (1, 8, 15)
        ]
        lr = pr.promote("p1", "h1", outcomes)
        assert lr.stage == "promoted"


class TestSampleSizeLadder:
    """裁决7：校准池规模决定允许动作；AVS 权重只能被 promoted 假设改变。"""

    def test_ladder_mapping(self):
        # 记观察永远允许（不在闸门内）；提假设是入口动作，池子 0 也放行
        assert pr.allowed_action_for_pool(0) == "hypothesis_only"
        assert pr.allowed_action_for_pool(1) == "hypothesis_only"
        assert pr.allowed_action_for_pool(3) == "hypothesis_only"
        assert pr.allowed_action_for_pool(7) == "qualitative_fix"
        assert pr.allowed_action_for_pool(15) == "quantitative_tweak"
        assert pr.allowed_action_for_pool(50) == "data_driven"

    def test_pool0_rejects_weight_change(self, tmp_product):
        r = pr.check_adjustment_allowed("p1", "quantitative_tweak", "avs.match_weight")
        assert r["allowed"] is False
        assert "样本量纪律" in r["reason"]

    def test_pool0_allows_only_hypothesis(self, tmp_product):
        assert pr.check_adjustment_allowed("p1", "hypothesis_only")["allowed"] is True
        assert pr.check_adjustment_allowed("p1", "record_observation_only")["allowed"] is True

    def test_model_target_needs_promoted_backing(self, tmp_product, monkeypatch):
        # 池子伪装到 25（等级允许 data_driven），但 target 无 promoted 背书 → 仍拒绝
        monkeypatch.setattr(pr, "_calibration_pool", lambda pid: 25)
        r = pr.check_adjustment_allowed("p1", "data_driven", "avs.match_weight")
        assert r["allowed"] is False and "promoted 假设背书" in r["reason"]

    def test_promoted_backing_unblocks(self, tmp_product, monkeypatch):
        monkeypatch.setattr(pr, "_calibration_pool", lambda pid: 25)
        pr.register_hypothesis(_hyp(model_target="avs.match_weight", learning_id="h9"))
        pr.promote("p1", "h9", [
            {"collected_at": f"2026-11-{d:02d}", "direction": 1} for d in (1, 8, 15)
        ])
        r = pr.check_adjustment_allowed("p1", "data_driven", "avs.match_weight")
        assert r["allowed"] is True


class TestScopeSeparation:
    """裁决5：topic 与 creative 的学习记录分开。"""

    def test_topic_and_creative_coexist(self, tmp_product):
        pr.register_hypothesis(_hyp(learning_id="h_topic", learning_scope="topic",
                                    what_tested="成本选题需求池假设", model_target="avs.demand_weight"))
        pr.register_hypothesis(_hyp(learning_id="h_creative", learning_scope="creative",
                                    what_tested="利益冲突标题假设", model_target="creative.title_guidelines"))
        learnings = gstore.list_learnings("p1")
        scopes = {lr.learning_id: lr.learning_scope for lr in learnings}
        assert scopes["h_topic"] == "topic" and scopes["h_creative"] == "creative"
