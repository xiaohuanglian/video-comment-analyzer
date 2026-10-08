# -*- coding: utf-8 -*-
"""Built-in example product profiles: YouVibe & TrainMind (演示种子，非硬编码业务逻辑).

These are *data* seeds for validation, following 任务书: 通用核心 + 产品档案。
Business rules live in profiles, not in code.
"""

from __future__ import annotations

from .models import AttributionCapability, ProductProfile

YOUVIBE = ProductProfile(
    product_id="youvibe",
    name="YouVibe",
    domain="AI 内容创作工具",
    growth_goal="通过外部平台内容分发为 youvibe.cn 获取真实用户。",
    target_audience="想用 AI 做短视频/动画/网页生成的内容创作者与入门用户。",
    value_props=[
        "AI 生成多样化内容（动画/网页/视频）",
        "降低创作门槛",
    ],
    positioning_status="未形成经过验证的独特定位；优先找到吸引目标用户的内容与有效导流方式。",
    forbidden_claims=(
        "不捏造素材真实效果；不夸大数据；未经授权的站内素材不搬运；"
        "不伪造用户评价；不宣传站内不存在的教程或资源。"
    ),
    attribution_capability=AttributionCapability.NONE,  # 经审计前不假设有站内埋点
    distribution_accounts=[],  # 站外分发账号需人工登记
    insight_profile_id="default",
    data_rights="内容来自团队原创、内部作品与已授权站内素材；逐条素材需在资产库标记授权状态。",
    is_builtin=True,
)

TRAINMIND = ProductProfile(
    product_id="trainmind",
    name="TrainMind",
    domain="AI 健身教练",
    growth_goal="通过内容与口碑验证个性化训练处方的拉新与激活。",
    target_audience="有训练意愿但缺乏计划与陪伴的健身入门与进阶用户。",
    value_props=[
        "理解用户状态与训练需求",
        "结合训练历史生成个性化训练处方",
        "语音与界面陪伴训练",
        "根据反馈调整训练",
        "记录训练结果并优化下次体验",
    ],
    positioning_status="核心价值已定义（见 value_props），不以实时摄像头动作纠错为核心。",
    forbidden_claims=(
        "不得公开用户训练记录、健康反馈或身份信息（仅脱敏、已授权数据可用）；"
        "未验证的功能不得宣传成真实效果。"
    ),
    attribution_capability=AttributionCapability.EVENT_API,  # 可提供脱敏行为/反馈/完成率数据
    distribution_accounts=[],
    insight_profile_id="default",
    data_rights="仅使用经授权、去标识化的训练行为、用户反馈、完成率、退出原因数据。",
    is_builtin=True,
)

BUILTIN_PRODUCTS = {p.product_id: p for p in [YOUVIBE, TRAINMIND]}
