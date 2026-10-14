# -*- coding: utf-8 -*-
"""受众智能层 · AI Growth Engine Phase 1（2026-10-13 规划，用户定稿）。

回答增长系统的三个前置问题（在「选题」之前）：
  1. 用户画像（Module 1）：提问者是谁——学生/科研/职场/创作者/开发者/泛小白
  2. 生命周期阶段（Module 3）：不知道AI → 知道 → 尝试 → 深入 → 愿意付费
  3. 受众价值评分 AVS（Module 2）：
       AVS = 需求数量 D × 传播潜力 P × 用户价值 V × 商业匹配 M
     例：使用渠道类需求量大但 M≈0（不碰、非业务）；求做法类 M≈0.9（产品即做法库）。

数据流：
  B站评论 jsonl → 需求聚类（19 主题）→ 画像/阶段/付费意愿推断 →
  聚类级 AVS → 写回增长引擎（Signal + GrowthOpportunity，幂等）→
  「增长复盘」视图可见。

评分透明原则：每个分数带分解与理由，禁止只有总分（对齐 GrowthOpportunity 的
verdict_rationale 要求）。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from . import store
from .models import (
    EvidenceQuality,
    GrowthOpportunity,
    OpportunityVerdict,
    ProductProfile,
    Signal,
    SignalSourceType,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 模型版本（P1 晋升协议）：AVS 权重/聚类正则/画像规则的当前版本。
# 任何 promoted 变更（走 promotion.py holdout 验证）→ 版本号 +1，旧预测凭 model_version 公平对比。
AUDIENCE_MODEL_VERSION = "v1"

# ---------------------------------------------------------------------------
# 需求聚类主题（含商业匹配 M 与理由）——M 编码 YouVibe 的价值主张映射
# ---------------------------------------------------------------------------

CLUSTER_DEFS: list[tuple[str, re.Pattern, float, str, tuple[str, str]]] = [
    # (主题, 匹配正则, 商业匹配M, 匹配理由, (选题生命周期, 生命周期打法))
    ("提示词_求做法资产", re.compile(r"提示词|prompt|咒语|口令|skill|知识库|求教程|模板|做法"), 0.9, "产品核心即做法库/skill 资产，需求与产品直接对口", ("evergreen", "新手持续涌入+收藏权重打法，做法库型内容可长期吃流量")),
    ("数学_教学动画", re.compile(r"数学|几何|函数|物理|课件|教学动画|题(目|库)|中考|高考"), 0.9, "已验证素材库+学习场景，做法内容直接可产", ("evergreen", "教材级常青，开学季/考试季有周期性峰值")),
    ("工具选择_入门", re.compile(r"什么(软件|工具|app|模型)|哪个(软件|工具|app)|怎么入门|新手|小白|零基础"), 0.8, "「刷着刷着就会了」的入口人群，产品路径即为此设计", ("evergreen", "每批新人都从『什么软件』开始问")),
    ("视频生成_工作流", re.compile(r"可灵|即梦|seedance|视频生成|文生视频|图生视频|ai视频|配音|衔接|分镜"), 0.7, "做法类内容主战场，实测与流程内容已验证", ("seasonal", "跟平台版本走，窗口=大版本更新期")),
    ("AI味_真实感", re.compile(r"ai味|太假|不真实|塑料感|一眼ai|真实感|质感"), 0.8, "做法质量类痛点，教程型内容可承接", ("decay", "随模型代际进步痛点递减，当前代际内仍有效")),
    ("成本_价格", re.compile(r"多少钱|收费|价格|贵不贵|免费|成本|划算|性价比|积分"), 0.6, "成本对比是已验证高流量题材，但转化路径间接", ("seasonal", "跟价格/政策变动走，窗口=调价事件")),
    ("模型选择_横评", re.compile(r"哪个(好|强|适合|推荐)|怎么选|对比|横评|排名|选哪个|vs"), 0.6, "发版首测/横评是内容强项，人群偏尝鲜者", ("hot", "发版窗口 3-7 天，先答先得，旧素材衰减快")),
    ("功能找不到", re.compile(r"找不到|入口|藏|位置在哪|菜单|按钮"), 0.7, "「入口藏得深」信息差，轻量栏目可批量做", ("evergreen", "平台改版持续产生『入口藏得深』信息差")),
    ("部署_本地_进阶", re.compile(r"部署|本地|显卡|显存|跑得动|ollama|comfyui|开源|工作流|节点"), 0.4, "人群偏硬核，与产品轻量定位错位，转化弱", ("evergreen", "硬核小众常驻需求")),
    ("报错_调试", re.compile(r"报错|失败|崩|闪退|无法|检测不到|装不上|卡住"), 0.3, "个案支持类，不适合内容规模化", ("hot", "个案即时性，无复用价值")),
    ("变现_副业", re.compile(r"变现|赚钱|副业|盈利|接单|商单|搞钱"), 0.3, "与 OPC/接活远期相关，但当前无标准答案可交付", ("evergreen", "欲望常青但无标准答案可交付")),
    ("使用渠道_账号", re.compile(r"用上|怎么用gpt|怎么用claude|注册|翻墙|科学上网|镜像|账号|会员|充值|中转|买.{0,4}号"), 0.0, "需求大但平台规则禁止且非产品业务——典型高分低配（用户示例：GPT账号购买）", ("hot", "发版/封控事件驱动短窗口；且 mismatch 已否决")),
]

# 选题生命周期语义（用户 2026-10-13 提出，区别于用户生命周期）：
# hot=发版/事件窗口先答先得 seasonal=跟版本/价格走有窗口期 evergreen=常青可长期吃 decay=随模型进步递减

# ---------------------------------------------------------------------------
# 画像（Module 1）——权重用于 V 分（YouVibe BP：核心=年轻用户与职场人群）
# ---------------------------------------------------------------------------

PERSONA_DEFS: list[tuple[str, re.Pattern, float]] = [
    ("创作者", re.compile(r"做视频|剪辑|账号|涨粉|粉丝|接单|商单|自媒体|发布|拍|出片|漫剧"), 1.0),
    ("职场人群", re.compile(r"工作|汇报|办公室|效率|职场|打工人|老板|同事|简历|周报|上班"), 0.9),
    ("开发者", re.compile(r"代码|编程|api|开发|程序|脚本|github|写码"), 0.8),
    ("AI尝鲜者", re.compile(r"实测|首发|新模型|横评|对决|尝鲜|第一时间"), 0.8),
    ("科研人群", re.compile(r"论文|科研|导师|文献|实验|定理|推导|组会|期刊|pde"), 0.7),
    ("创业者", re.compile(r"创业|生意|开店|接活|变现|副业"), 0.7),
    ("学生", re.compile(r"大三|大四|考研|高考|中考|绩点|宿舍|考试|复习|上课|作业|学校|留学|高中生|初中"), 0.5),
    ("泛小白", re.compile(r"新手|小白|零基础|入坑|萌新|手残|第一次|没用过|刚接触"), 0.4),
]
DEFAULT_PERSONA = ("未识别", 0.5)

# 视频上下文先验：评论本身无身份线索时，用宿主视频的受众画像兜底
# （在《新手入坑必看》下问的人→泛小白；在实测横评下的→AI尝鲜者）
PERSONA_VIDEO_PRIORS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"新手|入门|必看|小白|零基础|保姆级"), "泛小白"),
    (re.compile(r"数学|物理|科普|速通|考试|中考|高考|傅里叶"), "学生"),
    (re.compile(r"论文|科研"), "科研人群"),
    (re.compile(r"副业|变现|创业|生意"), "创业者"),
    (re.compile(r"实测|首发|横评|对决|排名|大模型|新模型"), "AI尝鲜者"),
    (re.compile(r"教程|技巧|实战|工作流"), "开发者"),
]

# 生命周期视频先验：教程视频→尝试；科普→认知；技巧/实战→深入；价格→付费
LIFECYCLE_VIDEO_PRIORS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"新手|入门|必看|保姆级|零基础"), "尝试"),
    (re.compile(r"科普|速通|什么是|到底|原理"), "认知"),
    (re.compile(r"技巧|进阶|核心|实战|工作流"), "深入"),
    (re.compile(r"价格|订阅|会员|省钱|成本"), "付费"),
    (re.compile(r"实测|横评|首发"), "尝试"),
]

# ---------------------------------------------------------------------------
# 生命周期（Module 3）——认知 → 尝试 → 深入 → 付费
# ---------------------------------------------------------------------------

LIFECYCLE_DEFS: list[tuple[str, re.Pattern]] = [
    ("付费", re.compile(r"多少钱|价格|充值|会员|订阅|买|值不值|性价比|付费|预算|花钱|免费额度")),
    ("深入", re.compile(r"工作流|参数|对比|横评|部署|进阶|优化|稳定性|细节|批量|一致性|api|节点")),
    ("尝试", re.compile(r"怎么用|什么软件|入门|开始|第一步|怎么做|新手|求教程|试一试|上手|同款|复刻")),
    ("认知", re.compile(r"什么是|到底|真的吗|第一次|没接触过|能不能|可以吗|是什么")),
]
DEFAULT_LIFECYCLE = "未识别"

_PAY_INTENT = re.compile(r"多少钱|价格|充值|会员|订阅|买|付费|预算|花钱|有偿|接单")


def infer_persona(text: str, video_context: str = "") -> tuple[str, float]:
    for name, pat, weight in PERSONA_DEFS:
        if pat.search(text):
            return name, weight
    # 评论本身无线索 → 宿主视频受众先验
    if video_context:
        for pat, persona in PERSONA_VIDEO_PRIORS:
            if pat.search(video_context):
                return persona, PERSONA_WEIGHTS.get(persona, 0.5)
    return DEFAULT_PERSONA


def infer_lifecycle(text: str, video_context: str = "") -> str:
    for stage, pat in LIFECYCLE_DEFS:
        if pat.search(text):
            return stage
    if video_context:
        for pat, stage in LIFECYCLE_VIDEO_PRIORS:
            if pat.search(video_context):
                return stage
    return DEFAULT_LIFECYCLE


def classify_cluster(text: str) -> Optional[str]:
    for name, pat, *_ in CLUSTER_DEFS:
        if pat.search(text):
            return name
    return None


def has_pay_intent(text: str) -> bool:
    return bool(_PAY_INTENT.search(text))


# ---------------------------------------------------------------------------
# 聚类聚合 + AVS 评分
# ---------------------------------------------------------------------------

def _norm_log(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return math.log1p(max(0.0, value)) / math.log1p(max_value)


def analyze_comments(rows: Iterable[dict[str, Any]], video_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """聚类级受众分析。rows 为评论 dict（comment_id/content/like_count/create_time/video_id）。
    自动按 comment_id 去重（多轮采集会追加写入同一文件）。"""
    clusters: dict[str, dict[str, Any]] = {}
    noise = {"count": 0}
    seen_ids: set[str] = set()
    for row in rows:
        cid = str(row.get("comment_id") or "")
        if cid and cid in seen_ids:
            continue
        if cid:
            seen_ids.add(cid)
        text = str(row.get("content") or "").strip()
        if len(text) < 6:
            continue
        try:
            likes = int(str(row.get("like_count") or 0) or 0)
        except (TypeError, ValueError):
            likes = 0
        cluster = classify_cluster(text)
        if not cluster:
            noise["count"] += 1
            continue
        vid = str(row.get("video_id") or "")
        video = video_map.get(vid, {})
        video_context = f"{video.get('title', '')} {video.get('source_keyword', '')}"
        persona, p_weight = infer_persona(text, video_context)
        lifecycle = infer_lifecycle(text, video_context)
        try:
            host_plays = int(video.get("video_play_count") or 0)
        except (TypeError, ValueError):
            host_plays = 0
        c = clusters.setdefault(
            cluster,
            {
                "count": 0, "videos": set(), "likes": 0, "max_host_plays": 0,
                "persona": defaultdict(int), "lifecycle": defaultdict(int),
                "pay_intent": 0, "samples": [],
            },
        )
        c["count"] += 1
        c["videos"].add(vid)
        c["likes"] += likes
        c["max_host_plays"] = max(c["max_host_plays"], host_plays)
        c["persona"][persona] += 1
        c["lifecycle"][lifecycle] += 1
        if has_pay_intent(text):
            c["pay_intent"] += 1
        if likes >= 0 and len(c["samples"]) < 12:
            c["samples"].append(
                {
                    "comment_id": str(row.get("comment_id") or ""),
                    "text": text[:120],
                    "likes": likes,
                    "video_title": str(video.get("title") or "")[:60],
                    "persona": persona,
                    "lifecycle": lifecycle,
                }
            )

    # 归一化基数
    max_count = max((c["count"] for c in clusters.values()), default=0)
    max_energy = max((c["likes"] + c["max_host_plays"] for c in clusters.values()), default=0)

    results = []
    for name, _, match, match_reason, (lifecycle, lifecycle_play) in CLUSTER_DEFS:
        c = clusters.get(name)
        if not c:
            continue
        total = c["count"]
        # V：画像权重均值 + 付费意愿加成
        v_persona = sum(PERSONA_WEIGHTS.get(p, 0.5) * n for p, n in c["persona"].items()) / total
        pay_ratio = c["pay_intent"] / total
        value = min(1.0, v_persona * (1.0 + 0.6 * pay_ratio))
        demand = _norm_log(total, max_count)
        potential = _norm_log(c["likes"] + c["max_host_plays"], max_energy)
        score = demand * potential * value * match
        top_persona = max(c["persona"].items(), key=lambda kv: kv[1])[0] if c["persona"] else "未识别"
        top_lifecycle = max(c["lifecycle"].items(), key=lambda kv: kv[1])[0] if c["lifecycle"] else "未识别"

        # 判定（对齐用户示例：需求大但商业不匹配 → reject）
        if match <= 0.2:
            verdict, rationale = OpportunityVerdict.REJECT, (
                f"需求量 {total} 条不小，但商业匹配 {match:.1f}（{match_reason}）——高需求低配型，明确不做"
            )
        elif score >= 0.10:
            verdict, rationale = OpportunityVerdict.RECOMMEND, (
                f"AVS {score:.3f}（需求{demand:.2f}×传播{potential:.2f}×价值{value:.2f}×匹配{match:.1f}），"
                f"人群以{top_persona}为主、集中在「{top_lifecycle}」阶段，{match_reason}"
            )
        elif score >= 0.04:
            verdict, rationale = OpportunityVerdict.HOLD, (
                f"AVS {score:.3f} 中等（需求{demand:.2f}×传播{potential:.2f}×价值{value:.2f}×匹配{match:.1f}），证据待更多数据"
            )
        else:
            verdict, rationale = OpportunityVerdict.HOLD, f"AVS {score:.3f} 偏低，量或传播证据不足"

        results.append(
            {
                "cluster": name,
                "demand_count": total,
                "video_count": len(c["videos"]),
                "likes": c["likes"],
                "max_host_plays": c["max_host_plays"],
                "persona_dist": dict(c["persona"]),
                "lifecycle_dist": dict(c["lifecycle"]),
                "pay_intent_ratio": round(pay_ratio, 3),
                "avs": {
                    "demand": round(demand, 3),
                    "potential": round(potential, 3),
                    "value": round(value, 3),
                    "match": match,
                    "score": round(score, 4),
                },
                "top_persona": top_persona,
                "top_lifecycle": top_lifecycle,
                "topic_lifecycle": lifecycle,
                "lifecycle_play": lifecycle_play,
                "verdict": verdict.value,
                "rationale": rationale,
                "match_reason": match_reason,
                "samples": sorted(c["samples"], key=lambda s: -s["likes"])[:5],
            }
        )
    results.sort(key=lambda r: -r["avs"]["score"])
    return {"clusters": results, "noise_count": noise["count"], "analyzed_at": datetime.now().isoformat(timespec="seconds")}


PERSONA_WEIGHTS = {name: weight for name, _, weight in PERSONA_DEFS}
PERSONA_WEIGHTS[DEFAULT_PERSONA[0]] = DEFAULT_PERSONA[1]


# ---------------------------------------------------------------------------
# 写回增长引擎（Signal + Opportunity，幂等）
# ---------------------------------------------------------------------------

def _day_stamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def sync_to_engine(report: dict[str, Any], product_id: str, dataset_ref: str = "") -> dict[str, int]:
    """把分析结果写成 Signal + GrowthOpportunity。opportunity_id 带日期戳，同日重跑 upsert 幂等。"""
    stamp = _day_stamp()
    existing_signal_ids = {s.signal_id for s in store.list_signals(product_id, limit=5000)}

    signals: list[Signal] = []
    opportunities: list[GrowthOpportunity] = []
    for r in report["clusters"]:
        cluster = r["cluster"]
        conf = min(0.9, 0.3 + 0.05 * min(r["demand_count"], 12))
        signals.append(
            Signal(
                signal_id=f"aud-{cluster}-{stamp}",
                product_id=product_id,
                source_type=SignalSourceType.EXTERNAL_COMMENT,
                source_platform="bilibili",
                dataset_ref=dataset_ref,
                evidence_refs=[s["comment_id"] for s in r["samples"] if s["comment_id"]][:5],
                collected_at=report["analyzed_at"],
                signal_type=f"audience_cluster::{cluster}",
                need_or_problem=f"{cluster}（{r['demand_count']} 条提问 / {r['video_count']} 视频）",
                ai_classification={
                    "avs": r["avs"],
                    "persona_dist": r["persona_dist"],
                    "lifecycle_dist": r["lifecycle_dist"],
                    "pay_intent_ratio": r["pay_intent_ratio"],
                    "topic_lifecycle": r["topic_lifecycle"],
                },
                confidence=round(conf, 2),
                evidence_quality=EvidenceQuality.MEDIUM,
            )
        )
        opportunities.append(
            GrowthOpportunity(
                opportunity_id=f"aud-opp-{cluster}-{stamp}",
                product_id=product_id,
                target_segment=f"{r['top_persona']}（{r['top_lifecycle']}阶段）",
                problem=f"{cluster}：{r['demand_count']} 条提问 / {r['video_count']} 视频 / 赞 {r['likes']}",
                evidence_refs=[f"aud-{cluster}-{stamp}"],
                linked_value=r["match_reason"],
                growth_mechanism="评论区需求聚类 → 做法型内容承接 → 主页/站内搜索转化",
                opportunity_kind="demand_first",
                production_need=(
                    f"面向{r['top_persona']}的「{cluster}」内容；生命周期定位：{r['top_lifecycle']}阶段"
                    f"；选题生命周期：{r['topic_lifecycle']}（{r['lifecycle_play']}）"
                ),
                recommended_action=(
                    "按 AVS 排序纳入选题；配完整做法钩子（要提示词的喊我）" if r["verdict"] == "recommend" else "暂缓或小样本试做"
                ),
                risks=["评论区样本 ≠ 全量目标用户", "传播潜力取自宿主视频数据，为代理指标"],
                confidence=round(conf, 2),
                uncertainty_level="inference",
                verdict=OpportunityVerdict(r["verdict"]),
                verdict_rationale=r["rationale"],
                metrics_to_verify=["收藏率", "主页访问率", "站内搜索命中数"],
                created_by="agent",
                data_nature="real",
                created_at=report["analyzed_at"],
            )
        )

    new_signals = [s for s in signals if s.signal_id not in existing_signal_ids]
    added = store.add_signals(new_signals) if new_signals else 0
    for opp in opportunities:
        store.upsert_opportunity(opp)
    return {"signals_added": added, "opportunities_upserted": len(opportunities)}


# ---------------------------------------------------------------------------
# 数据入口：读 B 站采集 jsonl
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIRS = [PROJECT_ROOT / "data" / "comments", PROJECT_ROOT / "data" / "automation" / "comments"]


def load_bili_comments(data_dirs: list[Path] | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str]:
    """读多个采集目录（默认主扫描目录 + 自动化目录），合并后交给 analyze_comments。
    同一 comment_id 多轮采集重复 → analyze 内按 comment_id 去重。"""
    dirs = [Path(d) for d in (data_dirs or DEFAULT_DATA_DIRS)]
    video_map: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    dataset_parts: list[str] = []
    for data_dir in dirs:
        for path in sorted(data_dir.glob("contents_*.jsonl")):
            dataset_parts.append(f"{data_dir.name}/{path.name}")
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    v = json.loads(line)
                    video_map[str(v.get("video_id"))] = v
        for path in sorted(data_dir.glob("comments_*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
    return rows, video_map, " + ".join(dataset_parts[-4:])


def refresh_default(product_id: str = "youvibe", data_dirs: list[Path] | None = None) -> dict[str, Any]:
    """数据飞轮自动刷新：全量数据 → 受众分析 → 写回引擎（信号+机会，幂等）。
    供采集周期结束后调用；失败由调用方色 try/except 兑底，不影响主流程。"""
    rows, video_map, dataset_ref = load_bili_comments(data_dirs)
    if not rows:
        return {"ok": False, "error": "no data"}
    report = analyze_comments(rows, video_map)
    sync = sync_to_engine(report, product_id, dataset_ref=dataset_ref)
    top = [
        {"cluster": c["cluster"], "avs": c["avs"]["score"], "lifecycle": c["topic_lifecycle"], "verdict": c["verdict"]}
        for c in report["clusters"][:3]
    ]
    return {
        "ok": True,
        "clusters": len(report["clusters"]),
        "total_rows": len(rows),
        "top": top,
        "sync": sync,
    }
