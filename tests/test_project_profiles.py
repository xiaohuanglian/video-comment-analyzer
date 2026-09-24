# -*- coding: utf-8 -*-
"""Project profile system: storage, resolution and prompt/report wiring."""

from __future__ import annotations

from api.services.insight import project_profiles as pp
from api.services.insight import paths as insight_paths
from api.services.insight.evidence_prompts import build_research_system_prompt
from api.services.insight.readable_report import _reportable_themes, _is_reportable_theme
from api.services.insight.schemas import FieldMapping, RunConfig


def _isolate_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(insight_paths, "DATA_DIR", tmp_path)
    return tmp_path / pp.PROFILES_FILE_NAME


def test_builtin_profiles_available():
    ids = {p.profile_id for p in pp.list_profiles()}
    assert ids == {"default"}
    assert pp.get_profile("default").hypotheses["H1"]


def test_legacy_profile_ids_alias_to_default():
    # `generic` is the only retained neutral alias for the built-in default.
    assert pp.get_profile("generic").profile_id == "default"
    # Historical vertical/private codenames are NOT special-cased.
    assert pp.get_profile("kineo") is None


def test_upsert_and_delete_custom_profile(tmp_path, monkeypatch):
    _isolate_profiles(tmp_path, monkeypatch)

    profile = pp.ProjectProfile(
        profile_id="myapp",
        name="我的产品",
        domain="效率工具",
        context_compact="研究目标：效率工具的用户痛点。",
        hypotheses={"H1": "需求真实存在"},
    )
    saved = pp.upsert_profile(profile)
    assert saved.is_builtin is False

    got = pp.get_profile("myapp")
    assert got is not None and got.domain == "效率工具"
    assert "myapp" in {p.profile_id for p in pp.list_profiles()}

    assert pp.delete_profile("myapp") is True
    assert pp.get_profile("myapp") is None


def test_resolve_profile_applies_run_override(monkeypatch):
    config = RunConfig(
        run_id="r",
        name="r",
        file_paths=["a.csv"],
        field_mapping=FieldMapping(comment_text="content"),
        project_id="default",
        project_context_compact="自定义上下文",
    )
    profile = pp.resolve_profile(config)
    assert profile.profile_id == "default"
    assert profile.context_compact == "自定义上下文"


def test_resolve_profile_falls_back_to_default():
    config = RunConfig(
        run_id="r",
        name="r",
        file_paths=["a.csv"],
        field_mapping=FieldMapping(comment_text="content"),
        project_id="does-not-exist",
    )
    assert pp.resolve_profile(config).profile_id == "default"


def test_research_prompt_uses_profile_hypotheses():
    default = pp.get_profile("default")
    prompt = build_research_system_prompt(default)
    assert default.hypothesis_short["H1"] in prompt
    # no vertical-specific vocabulary may leak into the neutral default
    for banned in ("健身", "训练", "跟练", "实时视觉识别"):
        assert banned not in prompt


def test_report_noise_markers_are_profile_scoped():
    noise = {"theme_name": "哈哈 沙发", "comment_count": 20}
    # built-in default filters generic noise markers
    assert _is_reportable_theme(noise, pp.get_profile("default").noise_markers) is False
    # a custom profile without that marker keeps it
    custom = pp.ProjectProfile(profile_id="x", name="x", noise_markers=["广告"])
    assert _is_reportable_theme(noise, custom.noise_markers) is True
    assert len(_reportable_themes([noise], custom.noise_markers)) == 1

def test_suggest_profile_normalizes_and_validates():
    from api.services.insight.profile_suggestion import suggest_profile, validate_suggested_profile

    data = suggest_profile(
        ["怎么学 AI", "提示词总是写不好", "有没有入门教程"],
        model_name="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        use_mock=True,
    )
    profile = validate_suggested_profile(data)
    assert profile.name
    assert profile.hypotheses["H1"]
    assert profile.hypothesis_short["H3"]
    assert profile.decision_keywords
    assert profile.is_builtin is False


def test_profile_taxonomy_drives_statistics_labels():
    from api.services.insight import project_profiles as pp
    from api.services.insight.labels import label_intent, label_signal
    from api.services.insight.statistics import build_statistics

    profile = pp.ProjectProfile(
        profile_id="t",
        name="t",
        intents=[{"key": "pricing", "label": "问价格"}],
        signals=[{"key": "wants_trial", "label": "想试用"}],
    )
    intent_labels = pp.intent_label_map(profile)
    signal_labels = pp.signal_label_map(profile)
    assert intent_labels == {"pricing": "问价格"}
    assert label_intent("pricing", intent_labels) == "问价格"
    assert label_signal("wants_trial", signal_labels) == "想试用"

    summary = build_statistics(
        [{"analysis": {"primary_intent": "pricing", "signals": ["wants_trial"]}, "source": {}}],
        total_records=1,
        intent_labels=intent_labels,
        signal_labels=signal_labels,
        valid_intents=set(intent_labels),
    )
    assert summary["valid_comments"] == 1
    assert summary["intent_labels"]["pricing"] == "问价格"
    assert summary["signal_labels"]["wants_trial"] == "想试用"


def test_query_filter_accepts_custom_intent():
    from api.services.insight.query_filters import match_result_row

    assert match_result_row({"analysis": {"primary_intent": "pricing"}}, intent_valid=True)
    assert not match_result_row(
        {"analysis": {"primary_intent": "invalid_or_unclear"}}, intent_valid=True
    )
    assert not match_result_row({"analysis": {}}, intent_valid=True)
