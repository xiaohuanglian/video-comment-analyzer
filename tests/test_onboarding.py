# -*- coding: utf-8 -*-
"""引导式建档：3 个问题 → 一份可用档案。

为什么需要：内置档案中立化后（不预设行业），新用户第一次用所有需要
「我是谁、面向谁」的功能都会报 ProfileNotConfigured——这是对的，但不能
让人先在设置页填一整页表单才能开始。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from api.services import onboarding
from api.services.insight import paths as insight_paths
from api.services.insight import project_profiles as pp


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(insight_paths, "DATA_DIR", tmp_path)
    return tmp_path


def _answers(**kw):
    base = {
        "domain": "同城鲜花配送",
        "target_audience": "想送花但不懂花的男性",
        "research_goal": "他们选花时最纠结什么",
    }
    base.update(kw)
    return base


def test_questions_are_exactly_three():
    """只问三个必答题——一次问八项，用户会直接关掉页面。"""
    qs = onboarding.questions()
    assert len(qs) == 3
    assert {q["key"] for q in qs} == {"domain", "target_audience", "research_goal"}
    assert all(q["question"] and q["hint"] for q in qs)


def test_build_profile_fills_both_positioning_and_analysis(isolated):
    profile = onboarding.build_profile(**_answers())
    # 三问答完就够用：不需要用户再手填一遍 domain/research_goal
    assert profile.domain == "同城鲜花配送"
    assert profile.niche == "同城鲜花配送"
    assert profile.research_goal == "他们选花时最纠结什么"
    assert pp.is_configured(profile) is True


def test_build_profile_rejects_incomplete(isolated):
    with pytest.raises(onboarding.OnboardingIncomplete) as exc:
        onboarding.build_profile(domain="鲜花", target_audience="", research_goal="")
    assert "面向谁" in str(exc.value) or "服务谁" in str(exc.value)


def test_build_profile_does_not_invent_industry(isolated):
    """档案只能来自用户原话，不得回落到任何行业预设。"""
    profile = onboarding.build_profile(**_answers(domain="宠物殡葬服务", target_audience="刚失去宠物的人"))
    blob = json.dumps(profile.model_dump(), ensure_ascii=False)
    for banned in ("AI 做视频", "提示词", "教程", "健身"):
        assert banned not in blob


def test_chinese_domains_get_distinct_ids(isolated):
    """回归：slug 只留 ascii 时，所有中文业务名都塌成同一个 id 互相覆盖。"""
    a = asyncio.run(onboarding.onboard(**_answers(domain="同城鲜花配送"), complete_fn=_never_called))
    b = asyncio.run(onboarding.onboard(**_answers(domain="宠物殡葬服务"), complete_fn=_never_called))
    assert a["profile"]["profile_id"] != b["profile"]["profile_id"]
    assert {p.profile_id for p in pp.list_profiles()} >= {
        a["profile"]["profile_id"],
        b["profile"]["profile_id"],
    }


async def _never_called(messages, **kw):
    raise AssertionError("没有要求切场景时不该调模型")


def test_onboard_activates_new_profile(isolated):
    res = asyncio.run(onboarding.onboard(**_answers(), complete_fn=_never_called))
    assert res["active_profile_id"] == res["profile"]["profile_id"]
    assert pp.get_active_profile_id() == res["active_profile_id"]
    assert res["scenarios"] is None  # 没要求就不跑


def test_scenario_failure_does_not_roll_back_profile(isolated):
    """建档是主流程，切场景是顺手试一下——后者挂了不能把前者拖下水。"""

    async def broken(messages, **kw):
        raise RuntimeError("网关 502")

    res = asyncio.run(onboarding.onboard(**_answers(), run_scenario=True, complete_fn=broken))
    assert res["profile"]["profile_id"]
    assert pp.get_active_profile_id() == res["active_profile_id"]
    assert "网关 502" in res["scenario_error"]
    assert res["next_steps"]


def test_onboard_runs_scenario_when_asked(isolated):
    async def fake(messages, **kw):
        return json.dumps(
            {
                "scenarios": [
                    {
                        "name": "第一次送花怕买错",
                        "axis": "denial",
                        "trigger": "第一次给女友送花",
                        "keywords": ["第一次送花", "买错"],
                    },
                    {
                        "name": "纪念日临时抱佛脚",
                        "axis": "trigger",
                        "trigger": "明天就是纪念日",
                        "keywords": ["明天纪念日"],
                    },
                ]
            },
            ensure_ascii=False,
        )

    res = asyncio.run(onboarding.onboard(**_answers(), run_scenario=True, complete_fn=fake))
    assert res["scenario_error"] == ""
    assert len(res["scenarios"]["items"]) == 2
    names = {s["name"] for s in res["scenarios"]["items"]}
    assert "第一次送花怕买错" in names
    # 场景未经验证就必须标未验证，不能让用户以为是结论
    assert res["scenarios"]["verified"] is False


def test_onboard_keeps_unknown_extra_fields(isolated):
    res = asyncio.run(
        onboarding.onboard(**_answers(), extra={"future_flag": {"a": 1}}, complete_fn=_never_called)
    )
    stored = pp.get_profile(res["profile"]["profile_id"])
    assert getattr(stored, "future_flag", None) == {"a": 1}
