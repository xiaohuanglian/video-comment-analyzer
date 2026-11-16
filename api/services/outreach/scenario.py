# -*- coding: utf-8 -*-
"""切场景：从一个产品定位，推出「可以在哪里、对谁、说什么」的具体切入场景。

## 这个模块解决什么

用户的原话：
> youvibe 上都是 AI 做的好看的图、视频，用户复制提示词或 skill 就能做同款。
> 这个定位让我自己想，只能想到「求模板、求提示词、新人小白」，
> 但实际上还有非常多的场景可以切入。

难点在于：**人只能从产品功能反推场景**（"我有模板 → 所以找求模板的人"），
而真正的场景活在用户的生活里（"要发小红书没有图"、"被老板说图太假"）。
前者竞争激烈且有存量，后者才是蓝海。

## 六个轴（不依赖具体行业）

任何一个产品，用户的"要买/要用"都可以从六条路径到达：

1. **身份**　谁在做这件事（职业/人生阶段/角色）
2. **困境**　卡在哪一步（哪个动作做不出来/做不好）
3. **替代**　现在怎么凑合解决的（旧工具、找人代做、放弃）
4. **触发**　什么时刻逼出了这个需求（截止日期、被批评、看到别人）
5. **否认**　为什么明明需要却不做（"AI 做的都是垃圾"、"我学不会"）
6. **邻近**　谁已经在旁边的场景里（相邻工具的用户、弃坑用户）

## 三条硬约束（沿用项目一贯口径）

1. **场景必须能被搜索词验证**：每个场景给出可直接粘进采集的关键词；
2. **场景必须能被现有语料证伪**：跑一次采集，看"真有人这么问吗"；
3. **数字只由代码算**：命中数、独立用户数、涉及视频数全部回查原始行，
   模型只负责提出场景与措辞，不许自己报数字。

## 输出粒度

**默认 5 个**，且每个都要细到"能直接去搜"。宁可少而准，不要 20 个空话——
粒度太粗（"母婴人群"）等于没切。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from api.services.llm_json import extract_json_object

#: 六个切入轴。key 用于稳定引用，label 给人看。
AXES: tuple[tuple[str, str, str], ...] = (
    ("identity", "身份", "谁在做这件事：职业、人生阶段、角色、所处行业位置"),
    ("struggle", "困境", "卡在哪一步：哪个具体动作做不出来、做不好、做太慢"),
    ("alternative", "替代", "现在怎么凑合：旧工具、找人代做、硬扛、干脆放弃"),
    ("trigger", "触发", "什么时刻逼出需求：截止日期、被批评、看到别人做成、花钱前的犹豫"),
    ("denial", "否认", "明明需要却不做：觉得假、觉得学不会、觉得没必要、试过失败"),
    ("adjacent", "邻近", "谁已经在旁边的场景里：相邻工具用户、刚弃坑的人、刚入行的人"),
)

AXIS_LABELS = {key: label for key, label, _ in AXES}
AXIS_DESCRIPTIONS = {key: desc for key, _, desc in AXES}


@dataclass
class Scenario:
    """一个可执行的切入场景。"""

    name: str                      # 一句话说清"对谁、在什么情境下"
    axis: str                      # 来自哪个轴（identity/struggle/...）
    trigger: str = ""              # 具体触发情境（When & Why）
    pain: str = ""                 # 这个情境下的痛/痒
    entry: str = ""                # 我们的产品在这里提供什么（一句话）
    keywords: list[str] = field(default_factory=list)   # 可直接搜索的关键词
    platforms: list[str] = field(default_factory=list)  # 建议投放/观察的平台
    why_underused: str = ""        # 为什么这个场景容易被忽略
    competitor_density: str = ""   # 竞争密度评估：低/中/高 + 一句理由
    # 验证结果（由代码填充，模型不得写入）
    hits: Optional[int] = None
    users: Optional[int] = None
    videos: Optional[int] = None
    sample_quotes: list[str] = field(default_factory=list)
    verdict: str = ""              # 由代码判定：有信号 / 弱信号 / 无信号
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "axis": self.axis,
            "axis_label": AXIS_LABELS.get(self.axis, self.axis),
            "trigger": self.trigger,
            "pain": self.pain,
            "entry": self.entry,
            "keywords": self.keywords,
            "platforms": self.platforms,
            "why_underused": self.why_underused,
            "competitor_density": self.competitor_density,
            "hits": self.hits,
            "users": self.users,
            "videos": self.videos,
            "sample_quotes": self.sample_quotes,
            "verdict": self.verdict,
        }


SCENARIO_SYSTEM = """你是增长策略分析师，任务是**从产品定位推导出具体可执行的切入场景**。

# 输入
- 产品/内容定位：它是什么、用户能得到什么
- 目标人群（若有）
- 已有的定位描述（若有）

# 你要理解的核心难点
人天然会**从产品功能反推场景**（"我有模板 → 找求模板的人"），
但这条路竞争最激烈。真正的机会在**用户的生活情境**里：
他要发小红书但没图、他被老板说图太假、他花 300 找人做觉得贵。

所以你必须**换六条路径**去想，而不是从功能出发：

1. 身份（identity）：谁在做这件事？细分到"刚被裁的 35 岁运营"这种程度，
   不要停在"年轻人/宝妈"。
2. 困境（struggle）：卡在哪个**具体动作**上？"会写 prompt 但出图廉价"
   比"不会 AI"精确得多。
3. 替代（alternative）：他现在怎么凑合？在用什么旧工具、找谁代做、
   还是干脆放弃？替代方案的用户就是我们最好的候选。
4. 触发（trigger）：什么**时刻**逼出这个需求？截止日期、被客户退稿、
   看到同行爆了、比价之前的那一晚。
5. 否认（denial）：明明需要却不动手，理由是什么？"AI 做的都是垃圾"、
   "我试过学不会"、"再等等"。否认本身就是最好的内容切入点。
6. 邻近（adjacent）：谁已经在**旁边的场景**里？刚弃坑别的工具的人、
   刚入行的人、正要升级的人。

# 硬要求
- **只输出 5 个场景**，宁少勿滥。每个都必须细到"能直接拿去搜"。
- 每个场景必须给出 **3-6 个可直接粘进搜索框的关键词**。
  关键词要是**用户的原话**，不是营销术语。比如用"图太假怎么办"，
  不要用"AI 图像质量优化需求"。
- 关键词之间要有区分度，不要五个场景都给"求模板"这种同质词。
- 必须**覆盖至少 4 个不同的轴**，不允许五个场景全挤在"困境"或"替代"里。
- `entry` 要写清"我们的产品在这个情境下具体解决什么"，不要写空泛的价值主张。
- `competitor_density` 必须诚实评估：这个词已经被大量内容占满就写"高"。
  写"高"比写"中"更有用。
- `why_underused` 要写清"为什么大家容易忽略这个场景"。
- 不许编造数据、用户数、搜索量。你只负责提出场景与措辞，数字由程序去查。

# 输出（只输出 JSON，不要解释）
{{"scenarios": [
  {{
    "name": "对谁 + 在什么情境下（一句话，≤30字）",
    "axis": "identity|struggle|alternative|trigger|denial|adjacent",
    "trigger": "具体触发情境，写得像一个人的真实瞬间",
    "pain": "这个情境下的痛或痒（一句话）",
    "entry": "我们的产品在这里提供什么（一句话）",
    "keywords": ["用户原话式的搜索词", "..."],
    "platforms": ["小红书", "B站", "知乎", "抖音", "YouTube"],
    "why_underused": "为什么这个场景容易被忽略",
    "competitor_density": "低|中|高 + 一句理由"
  }}
]}}"""


def _as_str(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _as_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = _as_str(item, 60)
        if text and text not in out:
            out.append(text)
    return out[:limit]


def parse_scenarios(payload: Any) -> list[Scenario]:
    """把模型输出解析成 Scenario 列表，并丢弃不合规的项。

    丢弃规则（宁可少，不可脏）：
    - 缺 name 或 keywords 的丢弃（无法搜索 = 无法验证 = 无法执行）
    - axis 非法的归到 struggle（不丢，但标注）
    """
    if isinstance(payload, str):
        payload = extract_json_object(payload) or {}
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("scenarios")
    if not isinstance(raw_items, list):
        return []

    scenarios: list[Scenario] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = _as_str(item.get("name"), 60)
        keywords = _as_list(item.get("keywords"), 6)
        if not name or not keywords:
            continue
        axis = _as_str(item.get("axis"), 20).lower()
        if axis not in AXIS_LABELS:
            axis = "struggle"
        scenarios.append(
            Scenario(
                name=name,
                axis=axis,
                trigger=_as_str(item.get("trigger")),
                pain=_as_str(item.get("pain")),
                entry=_as_str(item.get("entry")),
                keywords=keywords,
                platforms=_as_list(item.get("platforms"), 5),
                why_underused=_as_str(item.get("why_underused")),
                competitor_density=_as_str(item.get("competitor_density"), 80),
                raw=item,
            )
        )
        if len(scenarios) >= 8:
            break
    return scenarios


def axis_coverage(scenarios: list[Scenario]) -> dict[str, int]:
    """统计各轴覆盖情况，用于判断模型是否偷懒只给一类场景。"""
    counts = {key: 0 for key, _, _ in AXES}
    for scenario in scenarios:
        counts[scenario.axis] = counts.get(scenario.axis, 0) + 1
    return counts


def coverage_warnings(scenarios: list[Scenario]) -> list[str]:
    """给出「场景不够分散」这类可执行提示（不阻断，只提醒）。"""
    warnings: list[str] = []
    if not scenarios:
        return ["没有解析出任何场景"]
    covered = [k for k, v in axis_coverage(scenarios).items() if v > 0]
    if len(covered) < 4:
        labels = "、".join(AXIS_LABELS[k] for k in covered)
        warnings.append(
            f"只覆盖了 {len(covered)} 个轴（{labels}），建议至少覆盖 4 个——"
            "全都挤在同一个轴里，说明还是从功能反推场景"
        )
    # 关键词同质化检查
    word_count: dict[str, int] = {}
    for scenario in scenarios:
        for keyword in scenario.keywords:
            word_count[keyword] = word_count.get(keyword, 0) + 1
    repeated = [w for w, n in word_count.items() if n >= 2]
    if repeated:
        warnings.append("这些关键词在多个场景里重复出现（同质化）：" + "、".join(repeated[:5]))

    if any(not scenario.keywords for scenario in scenarios):
        warnings.append("有场景没有关键词，无法验证，建议丢弃或补词")
    return warnings


def build_user_message(
    *,
    positioning: str,
    audience: str = "",
    value: str = "",
    existing_hint: str = "",
) -> str:
    """组装发给模型的输入。"""
    parts = [f"产品/内容定位：{positioning.strip()}"]
    if audience.strip():
        parts.append(f"目标人群：{audience.strip()}")
    if value.strip():
        parts.append(f"用户能得到什么：{value.strip()}")
    if existing_hint.strip():
        parts.append(
            "用户自己已经想到的场景（说明这类场景他容易想到，竞争可能更激烈，"
            f"可以少给或换角度）：{existing_hint.strip()}"
        )
    parts.append(
        "请按六条路径认真推演，给出 5 个细到能直接搜索的场景。"
        "特别注意：不要只给「求模板/求教程/新人小白」这类从功能反推的场景。"
    )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 验证：用已有语料判断「这个场景真有人这么问吗」
# ---------------------------------------------------------------------------

#: 判定阈值。刻意保守：宁可判"弱信号"，也不要拿 2 条评论就宣布找到蓝海。
MIN_HITS_FOR_SIGNAL = 8
MIN_USERS_FOR_SIGNAL = 5
#: 语料少于此条数时，占比统计不可靠，不做泛词降权。
MIN_CORPUS_FOR_SPECIFICITY = 200


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _match_tokens(keywords: list[str], rows: list[dict[str, Any]]) -> set[str]:
    """把「搜索词组」拆成能落地到评论区的词根。

    2026-11-11 修正（实测踩到的坑）：
    关键词是给**搜索引擎**用的（"小红书代运营 怎么做图"），
    而评论区里的人是**随便说**的（"一个人做代运营出图真要命"）。
    直接拿整条关键词去评论里找子串，命中率是 0 —— 实测 5 个场景全部
    "无信号"，但同一个产品的短词根有几百条命中。

    正确做法分两层：
    - **搜索词**（原样保留）：拿去平台搜内容、看竞品密度；
    - **验证词根**（从搜索词里拆出来）：拿去评论区验证"真有人这么问吗"。

    拆法：按空格/标点切分，丢掉疑问词与虚词，保留 ≥2 字的实词。
    """
    stop = {
        "怎么", "什么", "如何", "为什么", "哪个", "哪些", "多少", "多久", "能不能",
        "可以", "要不要", "是不是", "有没有", "的话", "自己", "一个人", "怎么弄",
        "怎么办", "用什么", "做什么", "有没有办法", "请问", "求", "问",
    }
    tokens: set[str] = set()
    for keyword in keywords:
        for piece in re.split(r"[\s、/|,，。?？!！:：;；（）()\[\]\"']+", str(keyword)):
            piece = piece.strip()
            if len(piece) < 2 or piece in stop:
                continue
            tokens.add(piece)
    return tokens


def _token_specificity(tokens: set[str], rows: list[dict[str, Any]], text_field: str = "content") -> dict[str, float]:
    """算每个词根的「区分度」：在多少比例的评论里出现。

    2026-11-11 修正（第二个实测坑）：
    词根匹配修好之后跑出相反问题——"AI" 这个词命中 4384 条，
    于是三个完全不同的场景全被判成"有信号"。泛词等于没验证。

    这里按语料出现率给权重：出现在 >20% 评论里的词视为泛词（权重 0），
    只在少数评论里出现的词才是真信号。阈值不看绝对值看占比，
    这样换一个语料规模也不用重调。
    """
    total = len(rows)
    if total == 0:
        return {t: 1.0 for t in tokens}
    counts: dict[str, int] = {t: 0 for t in tokens}
    for row in rows:
        text = _normalize(row.get(text_field) or row.get("content") or row.get("text") or "")
        if not text:
            continue
        for token in tokens:
            if _normalize(token) in text:
                counts[token] = counts.get(token, 0) + 1
    # 语料不足时占比没有统计意义（9 条里出现 8 条 = "82%" 并不说明它是泛词）。
    # 少于 200 条评论时不做区分度降权，否则小样本会把真信号误判成泛词。
    if total < MIN_CORPUS_FOR_SPECIFICITY:
        return {t: 1.0 for t in tokens}

    weights: dict[str, float] = {}
    for token, count in counts.items():
        ratio = count / total
        if ratio > 0.20:
            weights[token] = 0.0      # 泛词：到处都是，不构成信号
        elif ratio > 0.05:
            weights[token] = 0.4      # 常见词：有参考价值但不算强
        else:
            weights[token] = 1.0      # 稀有词：真正指向这个场景
    return weights


def verify_scenario(
    scenario: Scenario,
    rows: list[dict[str, Any]],
    *,
    text_field: str = "content",
    user_field: str = "user_id",
    video_field: str = "video_id",
) -> Scenario:
    """用已采集的评论验证场景：命中多少条、涉及多少独立用户与视频。

    **验证的是"这个问题有人遇到吗"，不是"这个搜索词有人打吗"**——
    后者是平台搜索量的事，我们拿不到、也不该假装拿得到。

    命中口径：任一**词根**出现在评论文本里即算命中。
    数字全部由代码回算——模型不许报数字，这是项目一贯的硬约束。
    """
    tokens = _match_tokens(scenario.keywords, rows)
    if not tokens:
        scenario.verdict = "无法验证（关键词拆不出可用词根）"
        scenario.hits = 0
        scenario.users = 0
        scenario.videos = 0
        return scenario

    needles = [_normalize(t) for t in tokens if _normalize(t)]
    token_list = [t for t in tokens if _normalize(t)]
    # 区分度由 token 原文计算，索引时用归一化形式
    raw_weights = _token_specificity(set(token_list), rows, text_field)
    weights = {_normalize(t): w for t, w in raw_weights.items()}
    hits = 0
    users: set[str] = set()
    videos: set[str] = set()
    quotes: list[str] = []
    matched_tokens: dict[str, int] = {}

    for row in rows:
        text_raw = str(row.get(text_field) or row.get("content") or row.get("text") or "")
        text = _normalize(text_raw)
        if not text:
            continue
        found = [needle for needle in needles if needle in text]
        if not found:
            continue
        # 只统计「高区分度」词根的命中。
        # 0.4 档（如 "ai"/"工具"，语料里 5%-20% 的评论都会提）只是"沾边"，
        # 拿它当证据会让任何 AI 相关场景都判成有信号——等于没验证。
        specific = [n for n in found if weights.get(n, 1.0) >= 0.9]
        if not specific:
            continue
        hits += 1
        for needle in specific:
            matched_tokens[needle] = matched_tokens.get(needle, 0) + 1
        uid = str(row.get(user_field) or row.get("commenter") or row.get("nickname") or "")
        if uid:
            users.add(uid)
        vid = str(row.get(video_field) or row.get("note_id") or "")
        if vid:
            videos.add(vid)
        if len(quotes) < 3:
            quotes.append(text_raw[:80])

    scenario.hits = hits
    scenario.users = len(users) if users else (hits if hits else 0)
    scenario.videos = len(videos)
    scenario.sample_quotes = quotes
    # 把实际命中的词根记进 raw，供人核对「到底哪几个词在起作用」
    scenario.raw = dict(scenario.raw or {})
    scenario.raw["matched_tokens"] = sorted(matched_tokens.items(), key=lambda kv: -kv[1])[:6]

    if hits >= MIN_HITS_FOR_SIGNAL and scenario.users >= MIN_USERS_FOR_SIGNAL:
        top = "、".join(t for t, _ in sorted(matched_tokens.items(), key=lambda kv: -kv[1])[:3])
        scenario.verdict = f"有信号（主要靠「{top}」命中）"
    elif hits > 0:
        scenario.verdict = f"弱信号（命中 {hits} 条，低于 {MIN_HITS_FOR_SIGNAL} 条门槛）"
    else:
        scenario.verdict = "无信号（当前语料里没人提过这些词根）"
    return scenario


def verify_scenarios(
    scenarios: list[Scenario],
    rows: list[dict[str, Any]],
    **kwargs: Any,
) -> list[Scenario]:
    return [verify_scenario(s, rows, **kwargs) for s in scenarios]


def rank_scenarios(scenarios: list[Scenario]) -> list[Scenario]:
    """按「有信号优先、命中数降序、竞争密度低优先」排序。

    排序只是为了让人先看值得看的，不代表生成质量。
    """
    def density_rank(value: str) -> int:
        text = str(value or "")
        if text.startswith("低"):
            return 0
        if text.startswith("高"):
            return 2
        return 1

    return sorted(
        scenarios,
        key=lambda s: (
            0 if s.verdict.startswith("有信号") else 1,
            -(s.hits or 0),
            density_rank(s.competitor_density),
        ),
    )


def summary_stats(scenarios: list[Scenario]) -> dict[str, Any]:
    """给前端的汇总。数字全部来自验证结果（代码算的）。"""
    verified = [s for s in scenarios if s.hits is not None]
    return {
        "total": len(scenarios),
        "with_signal": sum(1 for s in scenarios if s.verdict.startswith("有信号")),
        "weak_signal": sum(1 for s in scenarios if s.verdict.startswith("弱信号")),
        "no_signal": sum(1 for s in scenarios if s.verdict.startswith("无信号")),
        "verified": len(verified),
        "axis_coverage": axis_coverage(scenarios),
        "warnings": coverage_warnings(scenarios),
    }


# ---------------------------------------------------------------------------
# 生成编排
# ---------------------------------------------------------------------------

async def generate_scenarios(
    *,
    positioning: str,
    audience: str = "",
    value: str = "",
    existing_hint: str = "",
    complete_fn: Optional[Any] = None,
    timeout: float = 120,
) -> tuple[list[Scenario], list[str]]:
    """调模型生成场景，返回 (场景列表, 警告)。

    返回警告而不是抛错的情况：模型给了场景但覆盖轴太少 / 关键词同质化。
    这些不是失败，是「提示人这版可能偷懒了」。
    """
    if not positioning.strip():
        raise ValueError("需要先给出产品/内容定位，否则无法推导场景")

    if complete_fn is None:
        from api.services.llm import complete as complete_fn  # type: ignore[assignment]

    user_message = build_user_message(
        positioning=positioning,
        audience=audience,
        value=value,
        existing_hint=existing_hint,
    )
    reply = await complete_fn(
        [
            {"role": "system", "content": SCENARIO_SYSTEM},
            {"role": "user", "content": user_message},
        ],
        temperature=0.8,  # 场景需要发散，温度比事实类任务高
        timeout=timeout,
        feature="outreach.scenario",
    )
    scenarios = parse_scenarios(reply)
    warnings = coverage_warnings(scenarios)
    return scenarios, warnings
