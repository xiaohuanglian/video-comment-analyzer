# -*- coding: utf-8 -*-
"""Discovery → Holdout 晋升协议（P1，2026-10-14 用户裁决 5/6/7）。

核心原则（修 cheat-on-content 的 in-sample 缺陷）：
  过去的数据只能提出假设；未来的数据才有资格验证假设。

  Discovery Set（截至 discovery_window_end 的数据）→ hypothesis
  Future Holdout（该日期之后的新实验结果）→ 方向一致数 ≥ evidence_requirement 且无强反例
  → promoted（建议模型版本 +1，由人确认后改代码常量）

裁决6：evidence_requirement 声明制，不写死全局 k——大效果（CTR 翻倍）3-5 个未来实验就值得继续；
小权重调整（0.25→0.29）20 个都嫌少。

裁决7（样本量纪律）：校准池（已冻结+已绑定+有 actual 的变体数）决定允许的动作：
  1 个 → 只记种子；2-4 → 假设；5-9 → 定性修正；10-19 → 定量微调；20+ → 数据驱动。
首批 3 实验复盘后只允许新增 hypothesis，禁止调 AVS 权重。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import store
from .models import LearningRecord

# 动作等级（从弱到强）——校准池规模决定允许的最高等级。
# record_observation_only 永远允许（记种子无风险），不进闸门；真正被拦的是模型变更类动作。
ACTION_LADDER: list[tuple[int, str]] = [
    (4, "hypothesis_only"),
    (9, "qualitative_fix"),
    (19, "quantitative_tweak"),
    (10**9, "data_driven"),
]
_ACTION_ORDER = [a for _, a in ACTION_LADDER]

ADJUSTMENT_KINDS = {
    "record_observation_only": "记录观察（种子）",
    "hypothesis_only": "提出假设",
    "qualitative_fix": "定性修正（判断习惯/维度定义，不动数值）",
    "quantitative_tweak": "定量微调（权重 ± 小幅）",
    "data_driven": "数据驱动（回归/重构权重）",
}


class PromotionError(ValueError):
    """晋升协议违规。"""


def allowed_action_for_pool(pool_size: int) -> str:
    for cap, action in ACTION_LADDER:
        if pool_size <= cap:
            return action
    return "data_driven"


def check_adjustment_allowed(product_id: str, kind: str, model_target: str = "") -> dict[str, Any]:
    """样本量纪律闸门（裁决7）：动作等级不得超过校准池允许的最高等级。

    AVS/画像/聚类正则类模型调整（model_target 非空）额外要求：
    必须存在指向同一 target 且 stage=promoted 的 LearningRecord——
    即权重永远只能被「未来数据验证过的假设」改变，不能被复盘直觉直接改。
    """
    if kind == "record_observation_only":
        return {"requested": kind, "allowed": True,
                "reason": "记录观察（种子）永远允许，不受闸门管辖——闸门只拦模型变更类动作"}
    if kind not in _ACTION_ORDER:
        raise PromotionError(f"未知动作类型 {kind}；合法值: {list(_ACTION_ORDER)}")
    pool = _calibration_pool(product_id)
    allowed = allowed_action_for_pool(pool)
    result = {
        "requested": kind,
        "pool_size": pool,
        "allowed_action": allowed,
        "allowed": _ACTION_ORDER.index(kind) <= _ACTION_ORDER.index(allowed),
        "reason": f"校准池 {pool} 个样本，最高允许「{ADJUSTMENT_KINDS[allowed]}」",
    }
    if not result["allowed"]:
        result["reason"] += (
            f"——请求的「{ADJUSTMENT_KINDS[kind]}」越级；样本量纪律："
            "1个只记种子 / 2-4假设 / 5-9定性 / 10-19定量 / 20+数据驱动（用户裁决7）"
        )
        return result
    if model_target:
        promoted_targets = {
            lr.model_target for lr in store.list_learnings(product_id)
            if lr.stage == "promoted" and lr.model_target
        }
        if model_target not in promoted_targets:
            result["allowed"] = False
            result["reason"] = (
                f"校准池等级允许，但 {model_target} 没有任何 promoted 假设背书——"
                "模型参数只能被「未来数据验证过的假设」改变，不能被复盘直觉直接改（先 register_hypothesis 走 holdout）"
            )
    return result


def register_hypothesis(learning: LearningRecord) -> LearningRecord:
    """把观察升级为正式假设。纪律：发现窗口必须已封闭（≤ 今天），evidence_requirement 必须声明。"""
    if learning.stage != "hypothesis":
        raise PromotionError("register_hypothesis 只接受 stage=hypothesis 的记录")
    if not learning.discovery_window_end:
        raise PromotionError("discovery_window_end 必填——没有封闭的发现窗口就无法区分发现数据和验证数据")
    try:
        window_end = date.fromisoformat(learning.discovery_window_end[:10])
    except ValueError as exc:
        raise PromotionError(f"discovery_window_end 格式错误: {exc}") from exc
    if window_end > date.today():
        raise PromotionError(
            f"发现窗口 {learning.discovery_window_end} 尚未封闭（今天是 {date.today()}）——"
            "不能对还没发生的数据先开验证通道，那等于自选验证集"
        )
    if learning.evidence_requirement <= 0:
        raise PromotionError(
            "evidence_requirement 必须 > 0 且由提议者按效果量级声明（裁决6：大效果 3-5 个够，小权重调整 20 个都嫌少；不设全局统一 k）"
        )
    return store.upsert_learning(learning)


def validate_hypothesis(product_id: str, learning_id: str, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """用实验结果验证假设。只接受 collected_at 晚于发现窗口的结果（in-sample 防护）。

    outcomes: [{"experiment_id", "variant_id", "collected_at": ISO日期, "direction": 1|-1|0, "note"}]
      direction=1 方向一致 / -1 反例 / 0 中性。
    """
    learning = _get_learning(product_id, learning_id)
    if learning.stage == "promoted":
        return {"status": "already_promoted", "learning_id": learning_id}
    if learning.stage != "hypothesis":
        raise PromotionError(f"只有 hypothesis 状态可验证，当前 stage={learning.stage}")

    window = learning.discovery_window_end
    holdout, excluded_in_sample, neutral = [], [], []
    for o in outcomes:
        if o.get("collected_at", "")[:10] <= window:
            excluded_in_sample.append(o)
        elif o.get("direction") == 1:
            holdout.append(o)
        elif o.get("direction") == -1:
            holdout.append(o)
        else:
            neutral.append(o)

    consistent = [o for o in holdout if o.get("direction") == 1]
    counter = [o for o in holdout if o.get("direction") == -1]

    if excluded_in_sample:
        # in-sample 结果被拒收——发现它的数据没资格验证它
        pass

    ready = len(consistent) >= learning.evidence_requirement and not counter
    return {
        "learning_id": learning_id,
        "status": "promote_ready" if ready else "awaiting_holdout",
        "evidence_requirement": learning.evidence_requirement,
        "consistent": len(consistent),
        "counterexamples": len(counter),
        "neutral": len(neutral),
        "rejected_in_sample": len(excluded_in_sample),
        "note": (
            f"未来一致 {len(consistent)}/{learning.evidence_requirement}，反例 {len(counter)}"
            + (f"，拒收 in-sample 结果 {len(excluded_in_sample)} 条（发现窗口 {window} 前）" if excluded_in_sample else "")
            + ("——可晋升：建议人工确认后 bump 模型版本并实施" if ready else "——继续等待未来数据，不得提前晋升")
        ),
    }


def promote(product_id: str, learning_id: str, outcomes: list[dict[str, Any]]) -> LearningRecord:
    """人工确认晋升——必须携验证结果，内部重验 promote_ready 后才改状态（防止未验证直通）。
    版本 bump 由人改代码常量（AUDIENCE_MODEL_VERSION）完成，这里只改状态。"""
    learning = _get_learning(product_id, learning_id)
    if learning.stage == "promoted":
        return learning
    if learning.stage != "hypothesis":
        raise PromotionError(f"stage={learning.stage} 不可晋升")
    check = validate_hypothesis(product_id, learning_id, outcomes)
    if check["status"] != "promote_ready":
        raise PromotionError(f"holdout 验证未通过，拒绝晋升：{check['note']}")
    learning = learning.model_copy(update={"stage": "promoted"})
    return store.upsert_learning(learning)


def _calibration_pool(product_id: str) -> int:
    from .prediction_freeze import _count_calibration_samples

    return _count_calibration_samples(product_id)


def _get_learning(product_id: str, learning_id: str) -> LearningRecord:
    for lr in store.list_learnings(product_id):
        if lr.learning_id == learning_id:
            return lr
    raise PromotionError(f"learning {learning_id} 不存在（product={product_id}）")
