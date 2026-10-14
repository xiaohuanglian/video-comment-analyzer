# -*- coding: utf-8 -*-
"""Platform Funnel Diagnosis（P0-C，2026-10-14 报告 §5.2 + 用户裁决4/5 落地）。

六层漏斗，从上往下逐层过，**在第一个明显掉链子的层停诊**——上游卡死时下游数字无诊断价值。

裁决4（语言纪律）：CTR 低 ≠ "标题/封面错"。CTR 最接近 Creative 层考卷，
但仍受 推荐人群/分发位置/账号熟悉度/同屏竞争/热点环境 影响。
输出语言固定为「标题/封面/受众匹配/分发人群层异常，需结合分发数据区分」，
禁止系统自动把 CTR 低归因给标题封面（防止"推错人→CTR低→疯狂优化标题→越改越标题党"）。

裁决5（对象分离）：topic 与 creative 的学习记录分开——
topic_verdict 单样本**无权证伪**；只有 ①-④ 全健康时才允许"获支持"。
"""

from __future__ import annotations

from typing import Any, Optional

LAYERS = ["①曝光/分发", "②点击", "③消费/完读", "④互动", "⑤关注", "⑥转化"]

# 各层对应的指标（缺失时显式标注，None ≠ 0）
LAYER_METRICS = {
    "①曝光/分发": ["exposure"],
    "②点击": ["ctr"],
    "③消费/完读": ["finish_rate", "avg_read_duration"],
    "④互动": ["save_rate", "like_rate", "comment_rate", "share_rate", "engagement_rate"],
    "⑤关注": ["new_followers", "follow_rate"],
    "⑥转化": ["conversion"],
}

# CTR 归因的固定措辞（裁决4）——绝不直接归因标题封面
CTR_ATTRIBUTION = "标题/封面/受众匹配/分发人群层异常——CTR 最接近 Creative 层考卷，但受推荐人群与分发环境影响，需结合分发数据区分后再下创意结论"

# 被禁止出现在输出的归因短语（防"优化标题→标题党"死循环）
FORBIDDEN_PHRASES = ["标题错", "封面做坏了", "封面做坏", "选题错误", "选题失败"]


class FunnelDiagnosis(dict):
    """dict 子类，方便断言同时保留结构。"""


def _landed(actual: float, spec: dict[str, Any]) -> str:
    if actual < spec["failure_threshold"]:
        return "below_failure"
    if actual >= spec["success_threshold"]:
        return "above_success"
    return "in_range"


def diagnose(
    observations: list[dict[str, Any]],
    frozen_predictions: dict[str, Any],
    own_baseline: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """单平台单篇诊断。observations: [{name, value, ...}]（value=None 表示未获取）。

    基准优先级：frozen thresholds > own_baseline > 无基准（只报数字不下结论）。
    """
    by_metric: dict[str, Optional[float]] = {}
    for ob in observations:
        by_metric[ob.get("name", "")] = ob.get("value")

    missing = [m for layer_metrics in LAYER_METRICS.values() for m in layer_metrics
               if m not in by_metric and m in _expected_metrics(frozen_predictions)]

    # 小基数守卫：曝光 <1000 时所有比率都是噪声
    exposure = by_metric.get("exposure")
    small_base = exposure is not None and exposure < 1000

    comparisons = []
    for metric, spec in (frozen_predictions or {}).items():
        actual = by_metric.get(metric)
        if actual is None:
            comparisons.append({"metric": metric, "actual": None, "landed": "no_data",
                                "expected_range": spec.get("expected_range")})
            continue
        comparisons.append({"metric": metric, "actual": actual, "landed": _landed(actual, spec),
                             "expected_range": spec.get("expected_range"),
                             "failure_threshold": spec.get("failure_threshold"),
                             "success_threshold": spec.get("success_threshold")})

    landed_by = {c["metric"]: c["landed"] for c in comparisons}

    # 逐层停诊
    layers: list[dict[str, Any]] = []
    broken_layer: Optional[str] = None
    for layer in LAYERS:
        if broken_layer:
            layers.append({"layer": layer, "status": "not_evaluable",
                           "note": f"上游 {broken_layer} 已坏，本层数据无诊断意义"})
            continue
        metrics = LAYER_METRICS[layer]
        present = [m for m in metrics if by_metric.get(m) is not None]
        if not present:
            if layer == "⑥转化":
                layers.append({"layer": layer, "status": "not_evaluable", "note": "未设转化目标，跳过"})
            else:
                layers.append({"layer": layer, "status": "no_data", "note": f"缺指标 {metrics}——缺失≠0，无法评估"})
            continue
        if small_base and layer != "①曝光/分发":
            layers.append({"layer": layer, "status": "noise", "note": "曝光<1000，比率是小基数噪声，不可读"})
            continue

        broken, why = _layer_broken(layer, metrics, by_metric, landed_by, frozen_predictions, own_baseline)
        layers.append({"layer": layer, "status": "broken" if broken else "ok", "note": why})
        if broken:
            broken_layer = layer

    verdicts = _verdicts(broken_layer, layers, landed_by, small_base)
    result = FunnelDiagnosis(
        broken_layer=broken_layer,
        layers=layers,
        verdicts=verdicts,
        guards={"small_base": small_base,
                "sample_note": "单样本假设级结论——'这条不行'≠'方向不行'，≥3 条同方向都差才能说方向错"},
        missing_metrics=missing,
        comparisons=comparisons,
    )
    _assert_language_discipline(result)
    return result


def _expected_metrics(frozen_predictions: dict[str, Any]) -> set[str]:
    return set((frozen_predictions or {}).keys())


def _layer_broken(layer, metrics, by_metric, landed_by, frozen, own_baseline) -> tuple[bool, str]:
    if layer == "①曝光/分发":
        exp = by_metric.get("exposure")
        spec = (frozen or {}).get("exposure")
        if spec and exp is not None:
            if exp < spec["failure_threshold"]:
                return True, f"曝光 {exp} < 冻结失败线 {spec['failure_threshold']}——分发层未起量（冷启动/标签/关键词，先别谈内容）"
            return False, f"曝光 {exp} 在冻结区间内"
        if exp is not None and exp < 500:
            return True, f"曝光 {exp} 极低（无冻结线，用通用守卫 <500）"
        return False, f"曝光 {exp}"

    if layer == "②点击":
        ctr = by_metric.get("ctr")
        spec = (frozen or {}).get("ctr")
        if ctr is None:
            return False, ""
        if spec and ctr < spec["failure_threshold"]:
            return True, f"CTR {ctr:.1%} < 冻结失败线 {spec['failure_threshold']:.1%}。{CTR_ATTRIBUTION}"
        if not spec and own_baseline and ctr < own_baseline.get("ctr", 0) * 0.7:
            return True, f"CTR {ctr:.1%} 低于自己历史中位数的 70%。{CTR_ATTRIBUTION}"
        return False, f"CTR {ctr:.1%}"

    if layer == "③消费/完读":
        fr = by_metric.get("finish_rate")
        if fr is not None and fr < 0.30:
            return True, f"完播 {fr:.0%} <30%（视频<30s 档经验线，🔴低可信）——开头没留住，检查前3秒"
        rd = by_metric.get("avg_read_duration")
        if fr is None and rd is not None and rd < 15:
            return True, f"平均阅读时长 {rd}s <15s（图文经验线，🔴低可信）——标题党或结构拖沓"
        return False, "完播/时长可读"

    if layer == "④互动":
        save, like = by_metric.get("save_rate"), by_metric.get("like_rate")
        spec_s = (frozen or {}).get("save_rate")
        if spec_s and save is not None and save < spec_s["failure_threshold"]:
            return True, (f"收藏率 {save:.1%} < 冻结失败线 {spec_s['failure_threshold']:.1%}——"
                          "四项互动分开看：藏低=实用价值未兑现（交付层），赞高藏低=情绪型（不一定是坏事）")
        eng = by_metric.get("engagement_rate")
        if eng is not None and eng < 0.03:
            return True, f"互动率 {eng:.1%} <3%（🟡行业经验线）"
        return False, "互动层可读"

    if layer == "⑤关注":
        nf = by_metric.get("new_followers")
        spec = (frozen or {}).get("new_followers")
        if spec and nf is not None and nf < spec["failure_threshold"]:
            return True, f"关注 {nf} < 冻结失败线 {spec['failure_threshold']}——内容有价值但缺人设记忆点/主页承接"
        return False, f"关注 {nf}"

    return False, ""


def _verdicts(broken_layer, layers, landed_by, small_base) -> dict[str, str]:
    upstream_ok = broken_layer in (None, "⑤关注", "⑥转化")
    # ①②层坏了 → 分发/受众匹配/创意层待区分，topic 不许下结论
    if broken_layer in ("①曝光/分发",):
        topic = "未证伪（分发层卡死，内容没获得公平考试机会；单样本也无权证伪）"
    elif broken_layer == "②点击":
        topic = "未证伪（点击层异常属于 标题/封面/受众匹配/分发 的待区分区，不落到选题）"
    elif broken_layer in ("③消费/完读", "④互动"):
        topic = "未证伪（单样本无权证伪；但①②健康说明选题+包装拿到了点击，问题在交付/兑现层）"
    elif broken_layer == "⑤关注":
        topic = "未证伪；①-④健康说明选题与交付被市场接受，关注层是承接问题"
    else:
        topic = "获支持（①-④全健康：拿到分发、赢得点击、完成消费、产生互动）" if not small_base else "数据噪声中，暂缓结论"
    return {
        "topic_verdict": topic,
        "creative_verdict": (
            "待区分：标题/封面/受众匹配/分发人群层异常——结合分发数据（推给谁/什么位置）后再区分是创意问题还是人群错配"
            if broken_layer == "②点击" else "无独立结论（创意层与选题层的分离判断需要多 variant 对照或分发侧数据）"
        ),
        "delivery_verdict": (
            "交付层异常（完播/兑现问题：开头钩子、结构、承诺兑现）" if broken_layer in ("③消费/完读", "④互动") else "未定位到交付层问题"
        ),
        "audience_verdict": (
            "受众匹配待查（CTR 异常时人群错配与创意问题同池，需分发数据裁决）" if broken_layer == "②点击" else "无独立异常信号"
        ),
        "distribution_verdict": (
            "分发层未起量（冷启动/账号标签/关键词，与内容质量无关的量的问题）" if broken_layer == "①曝光/分发" else "分发正常"
        ),
    }


def _assert_language_discipline(result: dict[str, Any]) -> None:
    """裁决4 语言纪律的技术强制：诊断输出永远不许出现直接归因短语。"""
    text = str(result)
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            raise AssertionError(f"漏斗诊断语言违规：输出包含被禁归因短语「{phrase}」——CTR 低只能指向待区分层，不能直接定罪标题封面/选题")
