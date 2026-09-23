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
    assert "kineo" in ids and "generic" in ids
    assert pp.get_profile("kineo").hypotheses["H1"]


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
        project_id="generic",
        project_context_compact="自定义上下文",
    )
    profile = pp.resolve_profile(config)
    assert profile.profile_id == "generic"
    assert profile.context_compact == "自定义上下文"


def test_resolve_profile_falls_back_to_default():
    config = RunConfig(
        run_id="r",
        name="r",
        file_paths=["a.csv"],
        field_mapping=FieldMapping(comment_text="content"),
        project_id="does-not-exist",
    )
    assert pp.resolve_profile(config).profile_id == "kineo"


def test_research_prompt_uses_profile_hypotheses():
    generic = pp.get_profile("generic")
    prompt = build_research_system_prompt(generic)
    assert generic.hypothesis_short["H1"] in prompt
    # fitness-specific rule must not leak into a generic profile
    assert "实时视觉识别" not in prompt


def test_report_noise_markers_are_profile_scoped():
    theme = {"theme_name": "bgm 合集", "comment_count": 20}
    # kineo filters bgm-style noise
    assert _is_reportable_theme(theme, pp.get_profile("kineo").noise_markers) is False
    # a custom profile without that marker keeps it
    custom = pp.ProjectProfile(profile_id="x", name="x", noise_markers=["广告"])
    assert _is_reportable_theme(theme, custom.noise_markers) is True
    assert len(_reportable_themes([theme], custom.noise_markers)) == 1