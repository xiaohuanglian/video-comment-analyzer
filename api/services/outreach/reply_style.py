# -*- coding: utf-8 -*-
"""活人感回复风格：硬禁令 lint + 平台风控频率默认值。

风格规则改编自 human-writing skill（KKKKhazix/human-writing，MIT），
从长文写作裁剪为「他人评论区短回复」场景：
- 材料先行：只基于对方评论里明确说过的内容，不编造对方经历
- 判断正面下，禁翻案腔
- 白话打底，禁模型腔/营销腔黑话
- 清除硬禁令（破折号、提示性冒号、翻案句式等）

lint 只做本地硬检查，命中的条目不阻断流程，而是标出
``style_warnings`` 提示人工闸门注意修改。
"""

from __future__ import annotations

import re
from typing import List

# ---------------------------------------------------------------------------
# 硬禁令（命中即在 style_warnings 里标出，人工闸门决定是否修改）
# ---------------------------------------------------------------------------

# 翻案腔：先立一个对方并没有的误解，再推翻它抬价
_REVERSAL_PATTERNS: list[tuple[str, str]] = [
    (r"不是[^。；？！]{1,20}而是", "翻案句式「不是……而是……」"),
    (r"并非[^。；？！]{1,20}而是", "翻案句式「并非……而是……」"),
    (r"不在于[^。；？！]{1,20}而在于", "翻案句式「不在于……而在于……」"),
    (r"与其说[^。；？！]{1,20}不如说", "翻案句式「与其说……不如说……」"),
    (r"(表面|看似|表面上)[^。；？！]{0,20}(实际|实则|其实)", "翻案句式「表面……实际……」"),
    (r"你以为[^。；？！]{1,20}其实", "翻案句式「你以为……其实……」"),
    (r"说到底", "翻案腔「说到底」"),
    (r"答案恰恰", "翻案腔「答案恰恰相反」"),
]

# 模型腔/营销腔黑话（评论区回复里直接禁）
_JARGON_WORDS: list[str] = [
    "赋能",
    "抓手",
    "闭环",
    "底层逻辑",
    "顶层设计",
    "颗粒度",
    "对齐一下",
    "认知升级",
    "破圈",
    "私域",
    "干货满满",
    "宝藏博主",
    "码住",
    "建议收藏",
    "值得关注",
    "值得注意的是",
    "需要指出的是",
    "从某种意义上说",
    "说白了",
    "说穿了",
    "先说结论",
    "更微妙的是",
    "还有一层",
    "只说对了一半",
]

# 连接号式破折号一律禁
_DASH_CHARS = "—–−—―"


# 居高临下/施压式表述（伤害对方自尊，与专业热心形象相悳）
_CONDESCENDING_PATTERNS: list[tuple[str, str]] = [
    (r"再[多]?翻翻看|再找找看|仔细找找", "施压式表述（让对方觉得没找到是自己笨），改为直接给出方法或入口位置"),
    (r"别急着[放弃换]", "施压式表述，删除"),
    (r"其实很[简单容易]", "居高临下（暗示对方觉得难是能力问题），改为具体步骤或「入口藏得深」这类归因于产品"),
    (r"不怪你|你细品|你品品", "居高临下表述，删除"),
]

# 指路式/元评论（回复的目的是给便利：答案直接给全，不把工作推给对方）
# 2026-10-13 用户真实案例反馈固化
_POINTING_PATTERNS: list[tuple[str, str]] = [
    (r"博主|up主|楼主|up本人", "提到博主（答案直接给，不借助博主转述）"),
    (r"(往下|回头|自己|去)翻|评论区里翻|自己(去)?(找|看|搜)一下", "指路式表述（把查找工作推给对方），答案直接给全"),
    (r"(好多人|很多人|大家)都?在?(评论区)?(找|问|求|蹲)", "无信息量元评论，删除"),
]

# 结尾开放反问(AI味最强特征:真人接话陈述完就走,抛回去的是运营号)
# 只打引导互动式(你觉得/怎么看/哪个好/是不是这样),不打针对对方处境的具体提问
_RE_TAIL_OPEN_QUESTION = re.compile(
    r"(你觉得|你们觉得|大家觉得|大伙觉得|怎么(看|想|说)|哪个(更)?好|"
    r"是不是.{0,14}(呢|吗)[?？。]?$|你说?是不是|(不是吗|对吧|对不对)$|"
    r"你们说|评论区.{0,6}(聊聊|讨论)|欢迎.{0,6}(讨论|分享))"
)

# 金句收尾(观点可留,收束句像文案;粗检,warning 级)
_RE_TAIL_PUNCHLINE = re.compile(
    r"(本质上|归根结底|真正的?.{0,12}(是|在于)|从来不是|缺的不是|差的不是|"
    r"补不了|拼的是|才是(关键|根本|核心|真相)|说到底)"
)

# 套话开场(模型高频共情模板)
_RE_CLICHE_OPEN = re.compile(r"^(太真实了|太对了|说到心坎|深有同感|感同身受|简直说到)")

# 翻译腔(进行X/句首作为基于关于)
_RE_TRANSLATION_TONE = re.compile(r"进行(一|了|一次)?(分析|处理|优化|排查|部署|沟通)|^(作为|基于|关于)[^，。]{0,18}(，|:|：)")

# 群发味称呼
_RE_BROADCAST_TONE = re.compile(r"亲[，,!！]|家人们")

# 编造感精确数字:小数点参数真人开口极少说(0.2秒/12.5%),整数约数(3到5秒)正常
_RE_FAKE_PRECISION = re.compile(r"\d+\.\d+\s*(秒|分钟|小时|%|倍|张|条|次|个点)")

# 固定连接词(堆叠才报)
_RE_CONNECTIVES = re.compile(r"然而|事实上|值得注意的是|更重要的是|与此同时|不得不说")


def _tail_sentence(text: str) -> str:
    """取末句:先去尾部标点,再按句读切取最后一段(末尾分隔符不会再产生空段)。"""
    t = (text or "").strip().rstrip("。！!？?～~\n ")
    if not t:
        return ""
    parts = re.split(r"[。！!？?]", t)
    tail = parts[-1] if parts[-1] else (parts[-2] if len(parts) > 1 else t)
    return tail.strip()


def check_reply_style(text: str) -> List[str]:
    """返回硬禁令命中列表（空列表 = 干净）。"""
    warnings: List[str] = []
    text = text or ""

    for ch in _DASH_CHARS:
        if ch in text:
            warnings.append("含有破折号（评论区回复一律不用破折号）")
            break

    # 冒号只允许引出直接原话（「他说：……」）。短回复里更简单：
    # 冒号后跟引号才算合法，其余视为提示性冒号。
    for match in re.finditer(r"[：:]", text):
        idx = match.start()
        rest = text[idx + 1 : idx + 2]
        if rest not in ("“", "「", "\"", "『"):
            warnings.append(f"第 {idx + 1} 字附近有提示性冒号（冒号只能用来引直接原话）")
            break

    for pattern, label in _REVERSAL_PATTERNS:
        if re.search(pattern, text):
            warnings.append(label)

    for pattern, label in _CONDESCENDING_PATTERNS:
        if re.search(pattern, text):
            warnings.append(label)

    for pattern, label in _POINTING_PATTERNS:
        if re.search(pattern, text):
            warnings.append(label)

    for word in _JARGON_WORDS:
        if word in text:
            warnings.append(f"黑话/模型腔词「{word}」")

    # 三项以上同构排比（顿号连接三个以上同长短语）粗检
    if re.search(r"[^，。；、]{2,8}、[^，。；、]{2,8}、[^，。；、]{2,8}", text):
        warnings.append("疑似三项以上同构排比（最多两项，第三项换说法或删掉）")

    # 动词名词化粗检
    for pat, fix in (
        (r"完成了对.{1,8}的", "动词名词化（「完成了对X的Y」改成「把X的Y做完了/做顺了」）"),
        (r"实现了.{1,8}的提升", "动词名词化（「实现了提升」改成「快了多少/省了几步」）"),
    ):
        if re.search(pat, text):
            warnings.append(fix)

    # 结尾开放反问:真人接话陈述完就走,结尾抛引导式问题=运营号/机器人腔
    tail = _tail_sentence(text)
    if _RE_TAIL_OPEN_QUESTION.search(tail):
        warnings.append(f"结尾开放反问「{tail[:24]}…」(AI味最强特征;删掉末句或换陈述,具体到对方处境的提问除外)")
    elif _RE_TAIL_PUNCHLINE.search(tail):
        warnings.append(f"金句收尾「{tail[:24]}…」(观点可留,收束句删掉平淡收)")

    # 套话开场
    if _RE_CLICHE_OPEN.search(text.strip()[:12]):
        warnings.append("套话开场(太真实了/深有同感式高频模板,换成:确实/是这样的)")

    # 翻译腔/群发味
    if _RE_TRANSLATION_TONE.search(text):
        warnings.append("翻译腔(进行X/句首作为基于;这句你嘴上会怎么说就怎么写)")
    if _RE_BROADCAST_TONE.search(text):
        warnings.append("群发味称呼(亲/家人们)")

    # 固定连接词堆叠(≥2次)
    if len(_RE_CONNECTIVES.findall(text)) >= 2:
        warnings.append("固定连接词堆叠(然而/事实上/值得注意的是;删掉一半,读者自己感觉得到话锋)")

    # 编造感精确数字(小数点参数)
    m = _RE_FAKE_PRECISION.search(text)
    if m:
        warnings.append(f"编造感精确数字「{m.group(0)}」(没量过的不写小数点,改成约数:留一点空隙/快了近半)")

    return warnings


# ---------------------------------------------------------------------------
# 平台风控安全频率默认值（仿人工节奏，非机器人匀速）
# 原则：短间隔随机波动 + 集群内连发 + 集群间长休息，模拟真人刷评论区行为
# ---------------------------------------------------------------------------

PLATFORM_REPLY_DEFAULTS: dict[str, dict] = {
    # 仿人工节奏：短间隔随机波动 + 集群内连发 + 集群间长休息 + 高日限
    # interval/jitter：单条间隔区间（秒）；session_replies：集群内连发条数上限；
    # break_seconds/break_jitter：集群间休息区间（秒）；daily_limit：日限
    "bilibili": {"interval_seconds": 60, "jitter_seconds": 120, "session_replies": 8, "break_seconds": 900, "break_jitter": 1200, "daily_limit": 60},
    "douyin": {"interval_seconds": 90, "jitter_seconds": 150, "session_replies": 6, "break_seconds": 1200, "break_jitter": 1500, "daily_limit": 40},
    "xhs": {"interval_seconds": 120, "jitter_seconds": 180, "session_replies": 5, "break_seconds": 1500, "break_jitter": 1800, "daily_limit": 30},
    "kuaishou": {"interval_seconds": 90, "jitter_seconds": 150, "session_replies": 6, "break_seconds": 1200, "break_jitter": 1500, "daily_limit": 40},
    "weibo": {"interval_seconds": 75, "jitter_seconds": 135, "session_replies": 7, "break_seconds": 1050, "break_jitter": 1350, "daily_limit": 50},
    "zhihu": {"interval_seconds": 100, "jitter_seconds": 160, "session_replies": 6, "break_seconds": 1200, "break_jitter": 1500, "daily_limit": 40},
    "tieba": {"interval_seconds": 75, "jitter_seconds": 135, "session_replies": 7, "break_seconds": 1050, "break_jitter": 1350, "daily_limit": 50},
}

_PLATFORM_ALIASES = {
    "bili": "bilibili",
    "bilibili": "bilibili",
    "dy": "douyin",
    "douyin": "douyin",
    "xhs": "xhs",
    "xiaohongshu": "xhs",
    "red": "xhs",
    "ks": "kuaishou",
    "kuaishou": "kuaishou",
    "weibo": "weibo",
    "zhihu": "zhihu",
    "tieba": "tieba",
}


def resolve_platform_defaults(platform: str) -> dict:
    """按平台返回仿人工节奏默认值；未知平台返回保守值。"""
    key = _PLATFORM_ALIASES.get((platform or "").strip().lower())
    if key and key in PLATFORM_REPLY_DEFAULTS:
        return dict(PLATFORM_REPLY_DEFAULTS[key])
    return {"interval_seconds": 90, "jitter_seconds": 150, "session_replies": 6, "break_seconds": 1200, "break_jitter": 1500, "daily_limit": 40}


# ---------------------------------------------------------------------------
# 草稿相似度防线(P0-2):同账号短期内发出高度相似的回复是平台风控的典型信号。
# 参考 autoshu「避免重复评论」;LLM 逐条独立起草也会风格趋同,必须有量化闸。
# ---------------------------------------------------------------------------

# Jaccard 阈值:block 以上拒绝入队;warn-block 之间放行但标警告。互动型话术更容易趋同,阈值更严。
SIMILARITY_BLOCK_HELP = 0.55
SIMILARITY_WARN_HELP = 0.40
SIMILARITY_BLOCK_ENGAGE = 0.45
SIMILARITY_WARN_ENGAGE = 0.30


def _char_bigrams(text: str) -> set:
    """中文短文本用字符二元组;过滤空白,大小写不敏感。"""
    s = "".join((text or "").split()).lower()
    if len(s) < 2:
        return set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def draft_similarity(a: str, b: str) -> float:
    """两条草稿的 char-bigram Jaccard 相似度,0-1;任一太短返回 0。"""
    ga, gb = _char_bigrams(a), _char_bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def similarity_against(draft: str, recent_drafts: List[str]) -> tuple[float, str]:
    """与一批近期草稿比,返回 (最高相似度, 最相似的那条);空集返回 (0.0, '')。"""
    best_score, best_text = 0.0, ""
    for other in recent_drafts:
        score = draft_similarity(draft, other)
        if score > best_score:
            best_score, best_text = score, other
    return round(best_score, 3), best_text


def similarity_verdict(draft: str, recent_drafts: List[str], lane: str = "help") -> tuple[str, float]:
    """返回 ('ok'|'warn'|'block', 最高相似度)。互动型阈值更严。"""
    score, _ = similarity_against(draft, recent_drafts)
    if lane == "engage":
        if score >= SIMILARITY_BLOCK_ENGAGE:
            return "block", score
        if score >= SIMILARITY_WARN_ENGAGE:
            return "warn", score
    else:
        if score >= SIMILARITY_BLOCK_HELP:
            return "block", score
        if score >= SIMILARITY_WARN_HELP:
            return "warn", score
    return "ok", score
