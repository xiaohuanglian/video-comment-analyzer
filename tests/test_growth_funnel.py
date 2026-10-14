# -*- coding: utf-8 -*-
"""funnel：六层漏斗停诊 + 裁决4 语言纪律 + 裁决5 topic/creative 分离。"""

from __future__ import annotations

import pytest

from api.services.growth.funnel import diagnose

FROZEN = {
    "exposure": {"expected_range": [2000, 12000], "failure_threshold": 800, "success_threshold": 5000},
    "ctr": {"expected_range": [0.04, 0.12], "failure_threshold": 0.03, "success_threshold": 0.08},
    "save_rate": {"expected_range": [0.03, 0.09], "failure_threshold": 0.02, "success_threshold": 0.06},
    "new_followers": {"expected_range": [20, 100], "failure_threshold": 10, "success_threshold": 50},
}


def _obs(**kw):
    defaults = dict(exposure=5000, ctr=0.06, save_rate=0.04, new_followers=30)
    defaults.update(kw)
    return [{"name": k, "value": v} for k, v in defaults.items() if v is not None]


class TestLayerStop:
    """每层各坏一组 → broken_layer 判对，下游 not_evaluable。"""

    def test_broken_at_exposure(self):
        r = diagnose(_obs(exposure=300), FROZEN)
        assert r["broken_layer"] == "①曝光/分发"
        downstream = [l for l in r["layers"] if l["layer"] != "①曝光/分发"]
        assert all(l["status"] == "not_evaluable" or l["status"] == "noise" for l in downstream)
        assert r["verdicts"]["distribution_verdict"].startswith("分发层未起量")

    def test_broken_at_ctr(self):
        r = diagnose(_obs(exposure=8000, ctr=0.02), FROZEN)
        assert r["broken_layer"] == "②点击"
        assert r["verdicts"]["topic_verdict"].startswith("未证伪")

    def test_broken_at_consumption(self):
        r = diagnose(_obs(exposure=8000, ctr=0.07, finish_rate=0.2), FROZEN)
        assert r["broken_layer"] == "③消费/完读"
        assert r["verdicts"]["delivery_verdict"].startswith("交付层异常")

    def test_broken_at_engagement(self):
        r = diagnose(_obs(exposure=8000, ctr=0.07, save_rate=0.01), FROZEN)
        assert r["broken_layer"] == "④互动"
        assert "交付" in r["verdicts"]["delivery_verdict"] or "兑现" in r["verdicts"]["delivery_verdict"]

    def test_broken_at_follow(self):
        r = diagnose(_obs(exposure=8000, ctr=0.07, save_rate=0.05, new_followers=5), FROZEN)
        assert r["broken_layer"] == "⑤关注"
        assert "承接" in r["verdicts"]["topic_verdict"]

    def test_all_healthy_topic_supported(self):
        r = diagnose(_obs(exposure=9000, ctr=0.09, save_rate=0.07, new_followers=60), FROZEN)
        assert r["broken_layer"] is None
        assert r["verdicts"]["topic_verdict"].startswith("获支持")


class TestRuling4LanguageDiscipline:
    """裁决4：CTR 低绝不直接归因标题封面。"""

    def test_ctr_low_never_blames_title_cover(self):
        r = diagnose(_obs(exposure=8000, ctr=0.02), FROZEN)
        text = str(r)
        assert "标题错" not in text and "封面做坏" not in text and "选题错误" not in text
        assert "受众匹配" in text  # 必须指向待区分层
        assert r["verdicts"]["creative_verdict"].startswith("待区分")

    def test_save_low_but_ctr_lower_stops_at_ctr(self):
        # 收藏率没达预测 + CTR 更低 → 停在②层，绝不能得出选题结论
        r = diagnose(_obs(exposure=8000, ctr=0.01, save_rate=0.005), FROZEN)
        assert r["broken_layer"] == "②点击"
        assert r["verdicts"]["topic_verdict"] == "未证伪（点击层异常属于 标题/封面/受众匹配/分发 的待区分区，不落到选题）"

    def test_save_low_ctr_ok_points_to_delivery_not_topic(self):
        # CTR 正常而收藏低 → 交付/兑现层，仍不许证伪选题
        r = diagnose(_obs(exposure=8000, ctr=0.08, save_rate=0.005), FROZEN)
        assert r["broken_layer"] == "④互动"
        assert r["verdicts"]["topic_verdict"].startswith("未证伪")

    def test_module_self_guard(self):
        # 语言纪律是断言强制的：构造违规输入应触发（用猴子补丁验证守卫真的在跑）
        from api.services.growth import funnel as f
        original = f._verdicts
        f._verdicts = lambda *a, **k: {**original(*a, **k), "topic_verdict": "选题错误，别做了"}
        try:
            with pytest.raises(AssertionError, match="语言违规"):
                f.diagnose(_obs(exposure=300), FROZEN)
        finally:
            f._verdicts = original


class TestGuards:
    def test_small_base_noise(self):
        r = diagnose(_obs(exposure=900, ctr=0.9), FROZEN)  # 曝光过失败线但<1000，CTR 再高也是噪声
        assert r["guards"]["small_base"] is True
        ctr_layer = [l for l in r["layers"] if l["layer"] == "②点击"][0]
        assert ctr_layer["status"] == "noise"

    def test_single_sample_note(self):
        r = diagnose(_obs(), FROZEN)
        assert "≥3 条同方向" in r["guards"]["sample_note"]

    def test_missing_metrics_explicit(self):
        r = diagnose([{"name": "exposure", "value": 5000}], {"exposure": FROZEN["exposure"], "ctr": FROZEN["ctr"]})
        assert "ctr" in r["missing_metrics"]
        ctr_layer = [l for l in r["layers"] if l["layer"] == "②点击"][0]
        assert ctr_layer["status"] == "no_data" and "缺失≠0" in ctr_layer["note"]

    def test_own_baseline_fallback_when_no_frozen(self):
        # 无冻结线时用自己历史中位数（<70% 判异常）
        r = diagnose(_obs(exposure=8000, ctr=0.02), {}, own_baseline={"ctr": 0.08})
        assert r["broken_layer"] == "②点击"
        assert "历史中位数" in [l for l in r["layers"] if l["layer"] == "②点击"][0]["note"]

    def test_no_baseline_no_conclusion(self):
        r = diagnose(_obs(exposure=8000, ctr=0.02), {})
        # 无任何基准：不下 broken 结论，只报数字
        assert r["broken_layer"] != "②点击" or r["broken_layer"] is None
