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
