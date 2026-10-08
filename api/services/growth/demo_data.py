# -*- coding: utf-8 -*-
"""明确标记的演示数据集（DEMO，非真实业务数据）。

产品 id 固定为 youvibe_demo，与真实 youvibe 隔离；
profile.name、所有记录均带 DEMO 语义标识，防止与真实数据混淆。
"""

from __future__ import annotations

from typing import Dict

from . import store
from .models import (
    AttributionCapability,
    ContentAsset,
    LicenseStatus,
    MetricKind,
    MetricsObservation,
    ProductProfile,
    Signal,
    SignalSourceType,
    utc_now_iso,
)

DEMO_PRODUCT_ID = "youvibe_demo"

_DEMO_NEEDS = [
    ("这个 AI 动画到底是怎么做的？求教程", 34),
    ("想用 AI 生成自己的网页，但完全不会代码", 21),
    ("这种效果要收费吗？有没有免费额度", 12),
    ("小白能学会吗，需要编程基础吗", 11),
    ("生成的视频能商用吗，版权算谁的", 8),
    ("有没有手机端？电脑不方便", 6),
    ("和剪映的 AI 功能有什么区别", 5),
    ("为什么我的动画生成出来很模糊", 3),
]


def build_demo_product() -> ProductProfile:
    base = ProductProfile(
        product_id=DEMO_PRODUCT_ID,
        name="YouVibe（DEMO 演示数据）",
        domain="AI 内容创作工具",
        growth_goal="【演示】通过外部平台内容分发为 YouVibe 获取真实用户。",
        target_audience="【演示】想用 AI 做短视频/动画/网页生成的内容创作者与入门用户。",
        value_props=["AI 生成动画/网页", "零代码门槛", "免费额度"],
        positioning_status="【演示】未验证定位，优先探索内容-用户匹配。",
        forbidden_claims="演示数据：仍遵守不得捏造效果/不得搬运未授权素材的约束。",
        attribution_capability=AttributionCapability.URL_TRACKING,  # 演示含可追踪点击
        insight_profile_id="default",
        data_rights="全部素材与数据均为演示虚构。",
        is_builtin=True,
    )
    return base


def seed_demo_dataset() -> Dict[str, int]:
    """幂等写入演示数据：重复调用不产生重复素材/信号/指标。"""
    store.upsert_product(build_demo_product())

    assets = [
        ContentAsset(asset_id="demo_a1", product_id=DEMO_PRODUCT_ID, title="AI 动画《星河》制作全流程",
                     summary="内部原创作品：从提示词到成片的完整过程录屏", uri="local://works/galaxy_anim.mp4",
                     asset_type="video", topics=["AI 动画", "制作过程", "教程"],
                     target_audience="想学 AI 动画的新手", highlights="真实制作过程，可拆解为教程",
                     landing_page="https://youvibe.cn/create/anim", license_status=LicenseStatus.OWNED,
                     published_channels=["bilibili"]),
        ContentAsset(asset_id="demo_a2", product_id=DEMO_PRODUCT_ID, title="零代码 AI 生成个人主页实录",
                     summary="内部作品：3 分钟用 AI 生成一个可访问的个人网页", uri="local://works/ai_web.mp4",
                     asset_type="video", topics=["AI 网页", "零代码", "教程"],
                     target_audience="不会代码的创作者", highlights="零代码完成真实网页",
                     landing_page="https://youvibe.cn/create/web", license_status=LicenseStatus.OWNED),
        ContentAsset(asset_id="demo_a3", product_id=DEMO_PRODUCT_ID, title="AI 动画作品混剪（效果展示）",
                     summary="内部作品混剪：纯效果展示，无教程内容", uri="local://works/showreel.mp4",
                     asset_type="video", topics=["AI 动画", "效果展示"],
                     landing_page="https://youvibe.cn/", license_status=LicenseStatus.OWNED,
                     published_channels=["douyin"]),
        ContentAsset(asset_id="demo_a4", product_id=DEMO_PRODUCT_ID, title="社区优秀作品《机械城》（已获作者授权）",
                     summary="站内优质素材，已取得作者书面授权可二次分发", uri="local://works/mech_city.mp4",
                     asset_type="video", topics=["AI 动画", "优秀作品"],
                     landing_page="https://youvibe.cn/works/mech_city", license_status=LicenseStatus.LICENSED),
        ContentAsset(asset_id="demo_a5", product_id=DEMO_PRODUCT_ID, title="社区作品《未知作者合集》",
                     summary="站内素材，授权状态未确认", uri="local://works/unknown.mp4",
                     asset_type="video", topics=["AI 动画"], license_status=LicenseStatus.UNKNOWN),
    ]
    existing_assets = {a.asset_id for a in store.list_assets(DEMO_PRODUCT_ID)}
    assets_n = 0
    for a in assets:
        if a.asset_id not in existing_assets:
            store.upsert_asset(a)
            assets_n += 1

    # 100 条模拟评论信号（按频次展开）
    existing_signals = {s.signal_id for s in store.list_signals(DEMO_PRODUCT_ID)}
    signals = []
    idx = 0
    for need, count in _DEMO_NEEDS:
        for i in range(count):
            idx += 1
            sid = f"demo_cmt_{idx:03d}"
            if sid in existing_signals:
                continue
            signals.append(Signal(
                signal_id=sid, product_id=DEMO_PRODUCT_ID,
                source_type=SignalSourceType.EXTERNAL_COMMENT, source_platform="bilibili",
                dataset_ref="demo_comments_100", evidence_refs=[f"demo_rec_{idx:03d}"],
                collected_at=utc_now_iso(), signal_type="question",
                need_or_problem=need, confidence=0.75,
                evidence_quality="high", usage_rights="internal_only",
            ))
    signals_n = store.add_signals(signals)

    # 3 条历史发布记录：两种不同表现（传播好≠导管好）
    # 历史数据直接记在没有实验的"历史表现"桶里（experiment_id=demo_hist）
    from .models import GrowthExperiment, PublishRecord

    hist_id = "demo_hist"
    existing_exp = {e.experiment_id for e in store.list_experiments(DEMO_PRODUCT_ID)}
    obs_n = 0
    if hist_id not in existing_exp:
        exp = GrowthExperiment(
            experiment_id=hist_id, product_id=DEMO_PRODUCT_ID,
            goal="【演示】历史分发表现基线", hypothesis="【演示】教程型内容导流效率高于效果展示型",
            asset_ids=["demo_a1", "demo_a3"], channels=["bilibili", "douyin"],
            publish_records=[
                PublishRecord(channel="bilibili", account="YouVibe官方", url="https://b23.tv/demo1",
                              published_at="2026-03-10", variant_id="a1_tutorial"),
                PublishRecord(channel="douyin", account="YouVibe官方", url="https://v.douyin.com/demo3",
                              published_at="2026-03-12", variant_id="a3_showreel"),
                PublishRecord(channel="bilibili", account="YouVibe官方", url="https://b23.tv/demo2",
                              published_at="2026-03-15", variant_id="a2_webdemo"),
            ],
            target_metrics=["views", "valid_visits"],
            attribution_limits="【演示】仅有可追踪链接点击与到站统计；注册数据未接入",
            status="concluded",
            conclusion="",
        )
        store.upsert_experiment(exp)
        obs = [
            # 教程型 A1：播放中等，到站率高
            MetricsObservation(observation_id="demo_ob1", product_id=DEMO_PRODUCT_ID, experiment_id=hist_id,
                               asset_id="demo_a1", metric_kind=MetricKind.REACH, name="views",
                               value=42000, channel="bilibili", source="platform_export", verified=True,
                               period_start="2026-03-10", period_end="2026-03-17"),
            MetricsObservation(observation_id="demo_ob2", product_id=DEMO_PRODUCT_ID, experiment_id=hist_id,
                               asset_id="demo_a1", metric_kind=MetricKind.TRAFFIC, name="valid_visits",
                               value=1180, channel="bilibili", source="platform_export", verified=True,
                               period_start="2026-03-10", period_end="2026-03-17",
                               attribution_note="可追踪链接点击后有效到站"),
            # 展示型 A3：播放很高，到站很低
            MetricsObservation(observation_id="demo_ob3", product_id=DEMO_PRODUCT_ID, experiment_id=hist_id,
                               asset_id="demo_a3", metric_kind=MetricKind.REACH, name="views",
                               value=310000, channel="douyin", source="platform_export", verified=True,
                               period_start="2026-03-12", period_end="2026-03-19"),
            MetricsObservation(observation_id="demo_ob4", product_id=DEMO_PRODUCT_ID, experiment_id=hist_id,
                               asset_id="demo_a3", metric_kind=MetricKind.TRAFFIC, name="valid_visits",
                               value=460, channel="douyin", source="platform_export", verified=True,
                               period_start="2026-03-12", period_end="2026-03-19"),
            # 网页教程 A2：播放较低，但到站高；注册未接入 → Unknown
            MetricsObservation(observation_id="demo_ob5", product_id=DEMO_PRODUCT_ID, experiment_id=hist_id,
                               asset_id="demo_a2", metric_kind=MetricKind.REACH, name="views",
                               value=18000, channel="bilibili", source="platform_export", verified=True,
                               period_start="2026-03-15", period_end="2026-03-22"),
            MetricsObservation(observation_id="demo_ob6", product_id=DEMO_PRODUCT_ID, experiment_id=hist_id,
                               asset_id="demo_a2", metric_kind=MetricKind.TRAFFIC, name="valid_visits",
                               value=940, channel="bilibili", source="platform_export", verified=True,
                               period_start="2026-03-15", period_end="2026-03-22"),
            MetricsObservation(observation_id="demo_ob7", product_id=DEMO_PRODUCT_ID, experiment_id=hist_id,
                               metric_kind=MetricKind.PRODUCT, name="signups",
                               value=None,  # Unknown：注册数据未接入，禁止填 0
                               source="manual_import",
                               attribution_note="注册埋点未接入，无法验证实际拉新"),
        ]
        obs_n = store.add_observations(obs)

    return {"assets": assets_n, "signals": signals_n, "historical_observations": obs_n,
            "note": "全部为 DEMO 演示数据，与真实产品数据隔离"}
