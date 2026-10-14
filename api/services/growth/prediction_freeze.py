# -*- coding: utf-8 -*-
"""Prediction Integrity + Creative Package Freeze（P0-A/P0-B，2026-10-14 用户裁决落地）。

两段式不可变冻结：
  1. freeze_predictions —— 发布前：冻结创意包 + 区间预测 + 赌注 + 证据快照
     → payload_hash 盖章，此后该变体的 _frozen 命名空间字节级不可改（store 层守卫强制）
  2. bind_published_asset —— 发布时：绑定实际发布资产哈希 + 账号状态版本 + 发布时间
     → binding_hash 盖章，同样不可改；错绑走新变体 redo

红线（用户裁决）：
  - 冻结完成前，A/B/C 三条实验不得发布——第一批"内容→行为"数据必须带赛前记录出生
  - N=0 阶段不强制完整概率分布：expected_range + failure/success_threshold + bet + confidence
    概率分布 schema 保留（dist 可选，填了则强制加总≈100%）
  - 篡改检测：verify_integrity 重算哈希，不匹配 → 样本降级为"参考"，不入校准池

Topic 与 Creative 分离（裁决5）：_frozen 里 creative_package 独立命名空间，
复盘归因时选题层与创意层用不同 verdict（见 funnel.py）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from . import store
from .audience import AUDIENCE_MODEL_VERSION

# 创意包必填（freeze 时）——裁决2：platform/account_id 必填；资产哈希留给发布绑定
CREATIVE_PACKAGE_REQUIRED = [
    "topic", "target_audience", "user_lifecycle", "topic_lifecycle",
    "title", "cover_hypothesis", "hook", "format", "content_structure",
    "cta", "tags", "platform", "account_id", "account_state",
]
# 发布绑定必填（bind 时）——裁决2：冻结实际发布资产，不是封面假设
PUBLISH_BINDING_REQUIRED = ["publish_time", "account_state_version", "creative_asset_hash"]

# payload_hash 覆盖的数据性字段（meta 字段不进哈希，但受 store 守卫保护）
FROZEN_DATA_FIELDS = [
    "creative_package", "predictions", "counterfactuals",
    "calibration_bet", "reasoning_snapshot", "evidence_snapshot",
]
BINDING_DATA_FIELDS = ["publish_time", "account_state_version", "creative_asset_hash", "url"]

# confidence 派生（吸收 cheat-on-content 的分级表语义，N=校准样本数）
CONFIDENCE_BY_SAMPLES = [
    (0, "very_low"),        # 纯纪律训练，不用于决策
    (2, "low"),             # 方向感优于绝对数字
    (5, "below_average"),   # 可作参考之一
    (10, "medium"),         # 可参与决策
    (20, "high"),           # 中枢可信
    (10**9, "data_driven"), # 允许数据驱动调权
]


class FreezeError(ValueError):
    """冻结协议违规。"""


def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(obj: Any) -> str:
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()[:16]


def _confidence_for(n: int) -> str:
    for cap, label in CONFIDENCE_BY_SAMPLES:
        if n <= cap:
            return label
    return "data_driven"


def _count_calibration_samples(product_id: str) -> int:
    """校准池 = 已冻结 + 已绑定发布资产 + 已有 actual 观测的变体数。"""
    observations = store.list_observations(product_id)
    obs_experiment_ids = {o.experiment_id for o in observations if o.experiment_id}
    n = 0
    for exp in store.list_experiments(product_id):
        for v in exp.content_variants:
            if v.get("_frozen") and v.get("_publish_binding") and exp.experiment_id in obs_experiment_ids:
                n += 1
    return n


def _validate_predictions(predictions: dict[str, Any]) -> None:
    if not predictions:
        raise FreezeError("predictions 不能为空——至少冻结一个指标的 expected_range")
    for metric, spec in predictions.items():
        rng = spec.get("expected_range")
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2 and rng[0] < rng[1]):
            raise FreezeError(f"{metric}: expected_range 必须是 [min, max] 且 min < max")
        fail, success = spec.get("failure_threshold"), spec.get("success_threshold")
        if fail is None or success is None:
            raise FreezeError(f"{metric}: failure_threshold / success_threshold 必填（裁决3：N=0 阶段用区间+阈值，不强制概率分布）")
        if not fail < success:
            raise FreezeError(f"{metric}: failure_threshold({fail}) 必须 < success_threshold({success})")
        dist = spec.get("dist")
        if dist is not None:
            total = sum(float(d.get("p", 0)) for d in dist)
            if abs(total - 1.0) > 0.01:
                raise FreezeError(f"{metric}.dist: 概率加总 {total:.3f} ≠ 1.0——要么不填，要么诚实填满")


def freeze_predictions(product_id: str, experiment_id: str, variant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把变体从可编辑状态升级为不可变冻结记录。重复冻结/修改已冻结 → FreezeError。"""
    exp = _get_experiment(product_id, experiment_id)
    variant = _find_variant(exp, variant_id)

    if variant.get("_frozen"):
        raise FreezeError(
            f"variant {variant_id} 已于 {variant['_frozen'].get('frozen_at')} 冻结，禁止再冻结或修改；"
            "重做请创建新 variant_id（redo 政策，旧记录保留）"
        )

    creative_package = payload.get("creative_package") or {}
    missing = [f for f in CREATIVE_PACKAGE_REQUIRED if not creative_package.get(f)]
    if missing:
        raise FreezeError(f"creative_package 缺必填字段: {missing}——不冻结完整创意包就无法区分'选题错'还是'封面坏'")

    predictions = payload.get("predictions") or {}
    _validate_predictions(predictions)

    if not (payload.get("calibration_bet") or "").strip():
        raise FreezeError("calibration_bet 必填——每个预测必须是一次明确赌注（'如果X发生则证明Y'）")

    frozen = {
        "creative_package": creative_package,
        "predictions": predictions,
        "counterfactuals": payload.get("counterfactuals") or {},
        "calibration_bet": payload["calibration_bet"],
        "reasoning_snapshot": payload.get("reasoning_snapshot") or "",
        "evidence_snapshot": payload.get("evidence_snapshot") or {},
        "basis": "pre_publish",
        "model_version": AUDIENCE_MODEL_VERSION,
        "calibration_samples": _count_calibration_samples(product_id),
        "confidence": "",
        "frozen_at": datetime.now().isoformat(timespec="seconds"),
        "payload_hash": "",
    }
    frozen["confidence"] = _confidence_for(frozen["calibration_samples"])
    frozen["payload_hash"] = _hash({f: frozen[f] for f in FROZEN_DATA_FIELDS})

    variant["_frozen"] = frozen
    # 冻结即定稿：清掉旧 DRAFT 平铺键（该变体此前从未冻结过，重写合法）
    for stale in ("predictions", "prediction_rationale", "is_draft", "frozen_at", "actuals"):
        variant.pop(stale, None)
    store.upsert_experiment(exp)
    return frozen


def bind_published_asset(product_id: str, experiment_id: str, variant_id: str, binding: dict[str, Any]) -> dict[str, Any]:
    """发布时绑定实际资产（裁决2）：creative_asset_hash 是成品哈希，不是封面假设。
    必须在冻结之后、任何 actual 观测之前完成。绑定后不可改。"""
    exp = _get_experiment(product_id, experiment_id)
    variant = _find_variant(exp, variant_id)

    if not variant.get("_frozen"):
        raise FreezeError("必须先 freeze_predictions 再绑定发布资产——预测必须先于发布事实存在")
    if variant.get("_publish_binding"):
        raise FreezeError(
            f"variant {variant_id} 已绑定发布资产（{variant['_publish_binding'].get('bound_at')}），不可改；错绑走新变体 redo"
        )
    missing = [f for f in PUBLISH_BINDING_REQUIRED if not binding.get(f)]
    if missing:
        raise FreezeError(f"publish_binding 缺必填字段: {missing}——不绑定成品哈希，复盘时分不清'封面假设错'还是'封面做坏'")

    record = {
        "publish_time": binding["publish_time"],
        "account_state_version": binding["account_state_version"],
        "creative_asset_hash": binding["creative_asset_hash"],
        "url": binding.get("url") or "",
        "bound_at": datetime.now().isoformat(timespec="seconds"),
        "binding_hash": "",
    }
    record["binding_hash"] = _hash({f: record[f] for f in BINDING_DATA_FIELDS})
    variant["_publish_binding"] = record
    store.upsert_experiment(exp)
    return record


def verify_integrity(product_id: str, experiment_id: str) -> dict[str, Any]:
    """重算哈希校验冻结/绑定记录是否被绕过 store 篡改（如手改 json 文件）。
    tampered 样本自动降级：标记 integrity=tampered，复盘时不得入校准池。"""
    exp = _get_experiment(product_id, experiment_id)
    report = {"experiment_id": experiment_id, "variants": []}
    changed = False
    for variant in exp.content_variants:
        vid = variant.get("variant_id", "?")
        status = {"variant_id": vid, "frozen": bool(variant.get("_frozen")), "binding": bool(variant.get("_publish_binding"))}
        frozen = variant.get("_frozen")
        if frozen:
            recomputed = _hash({f: frozen.get(f) for f in FROZEN_DATA_FIELDS})
            status["payload_ok"] = recomputed == frozen.get("payload_hash")
        binding = variant.get("_publish_binding")
        if binding:
            recomputed = _hash({f: binding.get(f) for f in BINDING_DATA_FIELDS})
            status["binding_ok"] = recomputed == binding.get("binding_hash")
        status["tampered"] = not (status.get("payload_ok", True) and status.get("binding_ok", True))
        # 降级标记写在冻结命名空间外（校验结论不属于被校验对象）
        if variant.get("_integrity") != ("tampered" if status["tampered"] else "ok"):
            variant["_integrity"] = "tampered" if status["tampered"] else "ok"
            changed = True
        report["variants"].append(status)
    if changed:
        store.upsert_experiment(exp)
    return report


def _get_experiment(product_id: str, experiment_id: str):
    for exp in store.list_experiments(product_id):
        if exp.experiment_id == experiment_id:
            return exp
    raise FreezeError(f"experiment {experiment_id} 不存在（product={product_id}）")


def _find_variant(exp, variant_id: str) -> dict[str, Any]:
    for variant in exp.content_variants:
        if variant.get("variant_id") == variant_id:
            return variant
    raise FreezeError(f"variant {variant_id} 不存在于 {exp.experiment_id}")
