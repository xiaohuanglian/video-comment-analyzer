# -*- coding: utf-8 -*-
"""切场景：从产品定位推导可切入的具体场景，并用真实语料验证。

需求来源（用户原话）：
> youvibe 上都是 AI 做的好看的图、视频，用户复制提示词或 skill 就能做同款。
> 这个定位让我自己想，只能想到「求模板、求提示词、新人小白」，
> 但实际上还有非常多的场景可以切入。

核心难点：**人只能从产品功能反推场景**（我有模板 → 找求模板的人），
而真正的场景活在用户生活里（要发小红书没图 / 被老板说图太假）。
这组测试锁住三件事：
1. 六个轴都在，且强制分散（不许全挤在"困境"里）；
2. 每个场景必须给出可搜索的关键词，否则无法验证 = 空话；
3. 验证数字**全部由代码回算**，模型不许报数字。
"""

from __future__ import annotations

import pytest

from api.services.outreach import scenario as svc

# ---------------------------------------------------------------------------
# 六个轴
# ---------------------------------------------------------------------------


def test_six_axes_are_defined():
    keys = [key for key, _, _ in svc.AXES]
    assert keys == ["identity", "struggle", "alternative", "trigger", "denial", "adjacent"]
    assert all(svc.AXIS_LABELS[k] for k in keys)
    assert all(svc.AXIS_DESCRIPTIONS[k] for k in keys)


# ---------------------------------------------------------------------------
# 解析：宁可少，不可脏
# ---------------------------------------------------------------------------


def _sample_payload() -> dict:
    return {
        "scenarios": [
            {
                "name": "明天纪念日才想起买花的男生",
                "axis": "trigger",
                "trigger": "明天就是纪念日，现在下单还来得及吗",
                "pain": "不知道买什么、怕买错",
                "entry": "按预算和场合直接给三个方案",
                "keywords": ["纪念日送什么花", "明天要用能送到吗"],
                "platforms": ["小红书"],
                "why_underused": "大家默认用户会提前规划",
                "competitor_density": "中 有花店广告但缺选购指南",
            },
            {
                "name": "被老板说图太假的新人",
                "axis": "struggle",
                "trigger": "交上去被打回",
                "pain": "会用工具但出图廉价",
                "entry": "给出可直接套的提示词模板",
                "keywords": ["AI图太假", "生成的图看着很廉价"],
                "platforms": ["B站"],
                "why_underused": "教程都停在'能生成'",
                "competitor_density": "低 多数教程不解决质感问题",
            },
            {
                "name": "一直觉得AI做不出好东西的人",
                "axis": "denial",
                "trigger": "刷到别人做的图却说一眼假",
                "pain": "看不起但心里动摇",
                "entry": "用同题对比让他自己判断",
                "keywords": ["AI一眼假", "AI图没有灵魂"],
                "platforms": ["知乎"],
                "why_underused": "否认者常被当成黑粉忽略",
                "competitor_density": "低",
            },
            {
                "name": "从Midjourney弃坑转过来的人",
                "axis": "adjacent",
                "trigger": "订阅太贵、出图不可控",
                "pain": "有基础但换工具成本高",
                "entry": "迁移对照表 + 等价提示词",
                "keywords": ["midjourney太贵", "mj换什么工具"],
                "platforms": ["B站"],
                "why_underused": "默认按新人做内容",
                "competitor_density": "中",
            },
        ]
    }


def test_parse_scenarios():
    scenarios = svc.parse_scenarios(_sample_payload())
    assert len(scenarios) == 4
    assert scenarios[0].axis == "trigger"
    assert scenarios[0].keywords
    assert scenarios[0].to_dict()["axis_label"] == "触发"


def test_parse_drops_scenarios_without_keywords():
    """没有关键词 = 无法搜索验证 = 空话，直接丢。"""
    payload = {
        "scenarios": [
            {"name": "有词", "axis": "struggle", "keywords": ["怎么弄"]},
            {"name": "没词", "axis": "struggle", "keywords": []},
            {"name": "", "axis": "trigger", "keywords": ["有词但没名"]},
        ]
    }
    scenarios = svc.parse_scenarios(payload)
    assert [s.name for s in scenarios] == ["有词"]


def test_parse_accepts_raw_model_string():
    """模型常带解释文字，要走统一 JSON 提取器。"""
    raw = '好的，这是结果：\n{"scenarios":[{"name":"x","axis":"identity","keywords":["a"]}]}\n希望有用'
    assert len(svc.parse_scenarios(raw)) == 1


def test_parse_clamps_unknown_axis():
    payload = {"scenarios": [{"name": "x", "axis": "不存在的轴", "keywords": ["a"]}]}
    assert svc.parse_scenarios(payload)[0].axis == "struggle"


# ---------------------------------------------------------------------------
# 覆盖度检查：防止模型偷懒
# ---------------------------------------------------------------------------


def test_coverage_warns_when_all_scenarios_share_one_axis():
    payload = {
        "scenarios": [
            {"name": f"场景{i}", "axis": "struggle", "keywords": [f"词{i}"]} for i in range(5)
        ]
    }
    scenarios = svc.parse_scenarios(payload)
    warnings = svc.coverage_warnings(scenarios)
    assert any("只覆盖了 1 个轴" in w for w in warnings)


def test_coverage_passes_with_four_axes():
    scenarios = svc.parse_scenarios(_sample_payload())
    warnings = svc.coverage_warnings(scenarios)
    assert not any("只覆盖了" in w for w in warnings)


def test_coverage_warns_on_duplicate_keywords():
    payload = {
        "scenarios": [
            {"name": "a", "axis": "struggle", "keywords": ["求模板"]},
            {"name": "b", "axis": "identity", "keywords": ["求模板"]},
            {"name": "c", "axis": "trigger", "keywords": ["求提示词"]},
            {"name": "d", "axis": "denial", "keywords": ["求教程"]},
        ]
    }
    warnings = svc.coverage_warnings(svc.parse_scenarios(payload))
    assert any("重复出现" in w for w in warnings)


def test_axis_coverage_counts():
    counts = svc.axis_coverage(svc.parse_scenarios(_sample_payload()))
    assert counts["trigger"] == 1
    assert counts["identity"] == 0


# ---------------------------------------------------------------------------
# 验证：数字由代码算
# ---------------------------------------------------------------------------


def _corpus() -> list[dict]:
    rows = []
    # 9 个人问"纪念日送什么花"，分布在 3 个视频（超过 8 条信号门槛）
    for i in range(9):
        rows.append(
            {
                "content": f"请问纪念日送什么花比较好 {i}",
                "user_id": f"u{i}",
                "video_id": f"v{i % 3}",
            }
        )
    # 1 个人问 AI 图太假
    rows.append({"content": "AI图太假了怎么办", "user_id": "x1", "video_id": "v9"})
    # 无关评论
    rows.append({"content": "哈哈哈哈沙发", "user_id": "y1", "video_id": "v10"})
    return rows


def test_verify_counts_hits_users_videos():
    scenario = svc.Scenario(
        name="纪念日临时买花",
        axis="trigger",
        keywords=["纪念日送什么花"],
    )
    svc.verify_scenario(scenario, _corpus())
    assert scenario.hits == 9
    assert scenario.users == 9
    assert scenario.videos == 3
    assert scenario.verdict.startswith("有信号")
    assert scenario.sample_quotes


def test_verify_reports_weak_signal_below_threshold():
    scenario = svc.Scenario(name="AI图太假", axis="struggle", keywords=["AI图太假"])
    svc.verify_scenario(scenario, _corpus())
    assert scenario.hits == 1
    assert scenario.verdict.startswith("弱信号")


def test_verify_reports_no_signal_honestly():
    scenario = svc.Scenario(name="没人问的场景", axis="identity", keywords=["完全没人说这个"])
    svc.verify_scenario(scenario, _corpus())
    assert scenario.hits == 0
    assert scenario.verdict.startswith("无信号")


def test_verify_without_keywords_is_not_silently_passed():
    scenario = svc.Scenario(name="空场景", axis="struggle", keywords=[])
    svc.verify_scenario(scenario, _corpus())
    assert "无法验证" in scenario.verdict


def test_model_cannot_dictate_numbers():
    """模型就算在输出里写了 hits/users，也必须被代码覆盖。"""
    payload = {
        "scenarios": [
            {
                "name": "想说有 999 人问",
                "axis": "trigger",
                "keywords": ["纪念日送什么花"],
                "hits": 999,
                "users": 999,
                "verdict": "有信号",
            }
        ]
    }
    scenarios = svc.parse_scenarios(payload)
    svc.verify_scenarios(scenarios, _corpus())
    assert scenarios[0].hits == 9
    assert scenarios[0].users == 9
    assert scenarios[0].hits != 999


def test_rank_prefers_signal_then_hits_then_low_competition():
    strong = svc.Scenario(name="强", axis="trigger", keywords=["纪念日送什么花"])
    weak = svc.Scenario(name="弱", axis="struggle", keywords=["AI图太假"])
    none = svc.Scenario(name="无", axis="identity", keywords=["不存在"])
    scenarios = [none, weak, strong]
    svc.verify_scenarios(scenarios, _corpus())
    ranked = svc.rank_scenarios(scenarios)
    assert [s.name for s in ranked] == ["强", "弱", "无"]


def test_summary_stats_counts():
    payload = _sample_payload()
    scenarios = svc.parse_scenarios(payload)
    svc.verify_scenarios(scenarios, _corpus())
    stats = svc.summary_stats(scenarios)
    assert stats["total"] == 4
    assert stats["verified"] == 4
    assert stats["with_signal"] + stats["weak_signal"] + stats["no_signal"] == 4


# ---------------------------------------------------------------------------
# 生成编排
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_requires_positioning():
    with pytest.raises(ValueError):
        await svc.generate_scenarios(positioning="   ")


@pytest.mark.asyncio
async def test_generate_parses_and_warns():
    async def fake_complete(messages, **kwargs):
        # 断言 prompt 里确实带上了定位，且要求六轴发散
        user = messages[1]["content"]
        assert "同城鲜花" in user
        assert "六条路径" in user or "六条" in user
        return '{"scenarios":[{"name":"纪念日买花","axis":"trigger","keywords":["纪念日送什么花"]}]}'

    scenarios, warnings = await svc.generate_scenarios(
        positioning="同城鲜花配送，按预算给方案",
        audience="想送花但不懂花的男性",
        complete_fn=fake_complete,
    )
    assert len(scenarios) == 1
    assert any("只覆盖了 1 个轴" in w for w in warnings)


def test_build_user_message_mentions_avoiding_function_reverse():
    """prompt 必须明确要求避开「从功能反推」的常规答案。"""
    msg = svc.build_user_message(
        positioning="AI 做图工具",
        audience="内容创作者",
        existing_hint="求模板、求提示词、新人小白",
    )
    assert "不要只给" in msg
    assert "求模板" in msg  # 把用户已想到的告诉他，避免雷同


# ---------------------------------------------------------------------------
# 验证方法的两个实测坑（都用真实语料踩过）
# ---------------------------------------------------------------------------


def test_keywords_are_split_into_matchable_tokens():
    """搜索词是给搜索引擎的，不会原样出现在评论区。

    实测教训：拿「小红书代运营 怎么做图」整串去评论里找子串，5 个场景
    全部 0 命中；但拆成词根后同一批语料有几百条命中。
    """
    tokens = svc._match_tokens(["小红书代运营 怎么做图", "AI 出图 太假"], [])
    assert "小红书代运营" in tokens
    assert "出图" in tokens
    assert "太假" in tokens
    # 疑问词不该变成验证词
    assert "怎么做" not in tokens
    assert "怎么" not in tokens


def _big_corpus(filler: int = 400) -> list[dict]:
    """造一个 >200 条的语料，用来验证泛词降权确实生效。"""
    rows = []
    for i in range(filler):
        rows.append({"content": f"这是一条普通评论 {i} 提到 ai 和工具", "user_id": f"f{i}", "video_id": "v0"})
    for i in range(12):
        rows.append({"content": f"我的图太假了怎么办 {i}", "user_id": f"s{i}", "video_id": f"v{i % 3}"})
    return rows


def test_generic_tokens_are_downweighted_on_large_corpus():
    """「ai」这种到处都是的词不能构成信号。

    实测教训：修好分词后曾出现相反问题——"ai" 命中 4384 条，
    三个完全不同的场景全被判成有信号，等于没验证。
    """
    rows = _big_corpus()
    weights = svc._token_specificity({"ai", "工具", "太假"}, rows)
    assert weights["ai"] <= 0.4, "泛词必须降权"
    assert weights["太假"] >= 0.9, "稀有词应保留全权重"


def test_generic_token_hits_do_not_count_as_evidence():
    scenario = svc.Scenario(name="全靠泛词", axis="struggle", keywords=["ai", "工具"])
    svc.verify_scenario(scenario, _big_corpus())
    assert scenario.hits == 0, "只有泛词命中时不该算有信号"
    assert scenario.verdict.startswith("无信号")


def test_specific_token_still_counts_on_large_corpus():
    scenario = svc.Scenario(name="有真信号", axis="struggle", keywords=["太假"])
    svc.verify_scenario(scenario, _big_corpus())
    assert scenario.hits == 12
    assert scenario.verdict.startswith("有信号")


def test_small_corpus_skips_downweighting():
    """小样本的占比没有统计意义，不能把真信号误判成泛词。"""
    rows = [{"content": "纪念日送什么花", "user_id": f"u{i}", "video_id": "v1"} for i in range(9)]
    weights = svc._token_specificity({"纪念日送什么花"}, rows)
    assert weights["纪念日送什么花"] == 1.0


def test_matched_tokens_are_reported_for_human_audit():
    """要让人能核对「到底是哪几个词在起作用」，而不是只给一个数字。"""
    scenario = svc.Scenario(name="x", axis="struggle", keywords=["太假"])
    svc.verify_scenario(scenario, _big_corpus())
    matched = (scenario.raw or {}).get("matched_tokens") or []
    assert matched and matched[0][0] == "太假"
