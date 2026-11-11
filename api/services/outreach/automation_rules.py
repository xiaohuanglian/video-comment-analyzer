# -*- coding: utf-8 -*-
"""回复自动化的「静态」部分：路径、平台默认值、筛选规则与出站硬校验。

从 `reply_automation.py` 拆出（2026-11-11）：原文件 2200+ 行，
其中这一大块是纯数据与纯函数——路径常量、三平台配额默认值、十余条
筛选正则、`classify_comment()`、出站违禁词校验。它们不依赖存储、
不依赖网络，改一行配额或一条正则却要在 2000 行的文件里翻找。

**拆分后 `reply_automation` 仍原样转出这些名字**（见那边的 import），
所以 `from ...reply_automation import DEFAULT_CONFIG` 之类的既有写法不受影响。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STORE_PATH = PROJECT_ROOT / "data" / "automation" / "bili_reply.json"
COMMENT_DIR = PROJECT_ROOT / "data" / "automation" / "comments"
XHS_COMMENT_DIR = PROJECT_ROOT / "data" / "automation" / "comments_xhs"
COOKIE_PATH = PROJECT_ROOT / "data" / "automation" / "bili_cookie.json"
BILI_PROFILE_DIR = PROJECT_ROOT / "browser_data" / "cdp_bili_user_data_dir"

# 自动化通道按平台分库：B 站(bili)保持原路径与行为不变，小红书(xhs)/抖音(dy)独立状态/配额/节奏
PLATFORMS = ("bili", "xhs", "dy")

DY_COMMENT_DIR = PROJECT_ROOT / "data" / "automation" / "comments_dy"


def store_path_for(platform: str) -> Path:
    if platform == "xhs":
        return PROJECT_ROOT / "data" / "automation" / "xhs_reply.json"
    if platform == "dy":
        return PROJECT_ROOT / "data" / "automation" / "dy_reply.json"
    return STORE_PATH


def comment_dir_for(platform: str) -> Path:
    """采集子进程的落盘目录。xhs/dy 单独目录，避免与 bili 的 jsonl 混写同名文件。"""
    if platform == "xhs":
        return XHS_COMMENT_DIR
    if platform == "dy":
        return DY_COMMENT_DIR
    return COMMENT_DIR


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "keywords": ["AI工具", "AI实测", "AI工作流", "AI编程", "数字人", "一人公司", "独立开发", "超级个体", "AI副业"],
    # 采集模式：auto=有竞品笔记清单走 detail，否则关键词 search；list/search 可强制
    "collect_mode": "auto",
    # 竞品笔记链接清单（小红书 detail 模式要求带 xsec_token 的完整链接）
    "note_urls": [],
    "collect_interval_hours": 6,
    "max_notes_per_keyword": 20,  # B 站搜索按页 20 条，代码里低于 20 会被抬到 20
    "max_comments_per_video": 100,
    "collect_timeout_minutes": 100,
    "freshness_a_hours": 48,
    "freshness_b_hours": 168,
    "max_new_candidates_per_cycle": 8,
    "max_per_video_per_day": 1,
    "daily_send_limit": 10,
    "send_interval_seconds": 180,
    "send_jitter_seconds": 240,
    "send_window_start": "09:00",
    "send_window_end": "22:00",
    "auto_draft": True,
    "llm_screen": True,
    "llm_screen_threshold": 6,
    "opinion_like_bypass": 50,
    "user_cooldown_days": 14,
    # 停损：发送撞风控后整条通道暂停的小时数（0=不启用停损）
    "sender_pause_hours": 24,
}

# 小红书截流通道的收紧默认值（该账号曾被警告：读发两侧都压到"正常真人"量级）。
# freshness_b_hours 放宽到 720(30天,2026-11-10 实测):B 站默认 168h 是按其评论区节奏
# 设计的;小红书关键词搜出的笔记偏老(超龄组中位 164 天),但回复通知照样触达评论者,
# 7 天窗口曾把 498 条内容过关的目标整层杀掉。已保存的用户配置始终优先于此默认。
XHS_CONFIG_OVERRIDES: dict[str, Any] = {
    "collect_interval_hours": 24,
    "max_notes_per_keyword": 10,
    "max_comments_per_video": 60,
    "max_new_candidates_per_cycle": 6,
    "freshness_b_hours": 720,
    "daily_send_limit": 6,
    "send_interval_seconds": 600,
    "send_jitter_seconds": 900,
    "user_cooldown_days": 21,
}

# 抖音截流通道默认值（2026-11-10）——按抖音平台特性独立定，不照抄小红书：
# - 评论文化高频：正常活跃用户一天几十条评论不显眼 → 日发取 10
#   （xhs 的 6 是「被警告账号」的收紧值；知识库记录过源作者抖音 4 号同封的教训，不取 bili 的 20）
# - 抖音风控盯机器式规律（等间隔/相似文案）而非绝对量 → 间隔基线降到 5 分钟、
#   抖动拉宽到 20 分钟：不规则节奏比「更慢但规律」更像真人（xhs 是 10-25 分钟高基线低抖动）
# - 楼中楼来回对话是抖音评论区常态，同一人 21 天冷却属过度防御 → 14 天（与 bili 一致）
# - 新鲜度 30 天：搜索结果偏老 + 回复通知照样触达评论者，跨平台共性，保留
# - 发送通道默认不启用（enabled=False 即 sender_loop 跳过 dy）：
#   采集→筛选→起草→人工批准先跑通，发送侧经干跑验证后由用户手动打开
DY_CONFIG_OVERRIDES: dict[str, Any] = {
    "collect_interval_hours": 24,
    # 抖音搜索每词固定一页 10 条（crawler 内部强制 max_notes ≥ 10），这是平台语义不是安全参数
    "max_notes_per_keyword": 10,
    "max_comments_per_video": 60,
    "max_new_candidates_per_cycle": 6,
    "freshness_b_hours": 720,
    "daily_send_limit": 10,
    "send_interval_seconds": 300,
    "send_jitter_seconds": 900,
    "user_cooldown_days": 14,
}

# ---------------------------------------------------------------------------
# 筛选规则（与 docs/回复待审清单 及记分卡标准一致）
# ---------------------------------------------------------------------------

_RE_SPAM = re.compile(r"成品号|出售|低价出|代充|加[vV薇微]|微信号|带赚|稳赚|项目私|求关注|免费(分享|领取)|私我|滴滴")
# 使用渠道类（用户规则：不碰）
_RE_ACCESS = re.compile(
    r"用上|怎么用gpt|怎么用claude|如何用gpt|注册|翻墙|科学上网|镜像|账号|会员|充值|买.{0,4}号|"
    r"支付|报销|订阅|低价pro|直充|封了|封号|中转"
)
# 变现类排除已删(2026-10-27 定位转向):想用AI赚钱的实干者是核心受众;
# 卖课拉人头的行为由 _RE_SPAM 排除,焦虑/求带/实干之分交 LLM 精筛 persona 分层
# 个案报错/调试（需个案验证，规则排除）
_RE_DEBUG = re.compile(
    r"报错|错误|崩了|闪退|无法|检测不到|安装失败|装不上|黑屏|白屏|内存不足|跑不动|"
    r"加载器|工作流.{0,6}(失败|不行)|一直(卡|转|等)"
)
# 求 UP 主私有资源（漏斗礼让：自动化一律不碰，人工可加）
_RE_RESOURCE_BEG = re.compile(
    r"求skill|求知识库|求资源|求资料|球球skill|三连.{0,10}求|已?三连.{0,8}(求|蹲)|"
    r"求(提示词|模板|打包|整合包|参数文档|操作手册)|蹲一波|求发|求分享|需要.{0,4}(skill|知识库|资料)"
)
# 导演式提问（问 UP 本人的做法/素材/参数——只有 UP 能答；不拦「您好/请您」这类礼貌用语）
_RE_DIRECTOR = re.compile(r"您的|你的|你(这|那)个|up你|楼主你|老师你|k神|ksr桑")
# AI 水评（B 站流行的 AI 生成总结式评论）
_RE_AI_WATER = re.compile(r"值得琢磨|值得深思|这道选择题|也挺直观|从某种角度|某种意义|确实也")
# AI 生成评论的装饰符签名(首尾包边口号体/✨;2026-10-27 实测三类全中)
_RE_AI_DECO = re.compile(r"^[\u2756\u2740\u2726\u273f\u2746\u25c8\u2605\u2606].{4,}[\u2756\u2740\u2726\u273f\u2746\u25c8\u2605\u2606]$|\u2728|\ud83d\udcab")
# 感叹/纯情绪（无提问内容）
_RE_EXCLAIM = re.compile(
    r"^(好的|谢谢|感谢|厉害|绝了|哇|牛|冲|收藏了|mark|马克|支持|好看|太|确实|哈哈|笑死|"
    r"打卡|前排|来了|222|hhh|666|顶|赞)[!！。～~\s]*$|^\d+$"
)

# 反问/抒情/赞叹(纯修辞,无观点内容;「还要什么自行车」等习语常见于实质观点中,不再拦)
_RE_RHETORIC = re.compile(r"没人(夸|说|提|注意)|我从没觉得|多愁善感|破防|泪目|哭死")
# A 档：看得到学不会（问工具/怎么做;含商业动作:获客/接单/定价）
_RE_HOWTO = re.compile(
    r"什么(软件|工具|app|模型|程序|网站)|哪个(软件|工具|app|平台)|"
    r"怎么(做|弄|用|生成|实现|做到|衔接|设置|入门|开始|学|获客|接单|定价|找客户|引流|成交|变现|赚钱)|"
    r"如何(做|用|实现|生成|入门|获客|接单|定价)|"
    r"用什么|求(教|指导|推荐)|怎么做同款|怎么才能"
)
# B 档：想动手缺路径（新手自述，需带提问感）
_RE_NEWBIE = re.compile(r"新手|小白|零基础|入坑|萌新|手残|想学|想试|我也想|入门")
_RE_QUESTION_CUE = re.compile(r"？|\?|吗|呢|什么|怎么|哪|求|请教|能不能|有没有")
# 求助动词（弱疑问必须同时命中，否则视为现后讨论）
_RE_SEEKING = re.compile(
    r"想学|想做|想试|想用|想了解|想知道|好奇|请教|请问|求教|求助|打算|想上手|想入|"
    r"能不能|可不可以|有没有办法|怎么才能|能实现|能做"
)
# C 档：AI×商业相关实体（观点/讨论评论的召回判据;2026-10-27 扩商业词）
_RE_AI_ENTITY = re.compile(
    r"(?<![a-zA-Z])[aA][iI](?![a-zA-Z])|人工智能|大模型|llm|智能体|agent|生成式|"
    r"gpt|claude|gemini|opus|astra|deepseek|sora|veo|"
    r"可灵|即梦|seedance|千问|qwen|豆包|智谱|nano banana|"
    r"提示词|数字人|ai视频|ai动画|ai修图|ai绘图|ai画|ai配音|ai生成|"
    r"副业|创业|做生意|生意|变现|搞钱|赚钱|接单|获客|一人公司|超级个体|独立开发",
    re.IGNORECASE,
)


# 营销号昵称(卖号/代充/接单工作室——评论再像样也不值得回)
_RE_SPAM_NICK = re.compile(r"订阅|可开票|低价|代充|出号|回收|接单|工作室|招商|代理")

# ---------------------------------------------------------------------------
# 小红书出站硬校验（发送侧红线：截流评论绝不能带链接/联系方式/引流话术）
# ---------------------------------------------------------------------------

_RE_OUTBOUND_LINK = re.compile(
    r"https?://|www\.|[a-zA-Z0-9-]+\.(com|cn|net|org|io|me|xyz|top)\b|"
    r"小红书号|抖音号|公众号|视频号|快手号|B站[号名]|知乎号"
)
_RE_OUTBOUND_CONTACT = re.compile(
    r"加\s*[vV薇微❤]|微信号|[vVxX][：:]\s*[a-zA-Z0-9_-]{3,}|"
    r"[qQ]{1,2}\s*[：: ]\s*\d{5,}|扣扣|企鹅号|飞机号"
)
_RE_OUTBOUND_CTA = re.compile(
    r"私我|私信我|滴滴我|看我主页|主页有|简介有|关注我|带你(做|赚|飞)|收徒|上车|私聊"
)


def xhs_draft_violations(text: str) -> list[str]:
    """小红书出站草稿硬校验。返回违禁原因列表，空列表=可发。

    批准与发送两处都会调用：这是平台警告/举报的直接诱因，模型写得再好也不放行。
    """
    violations: list[str] = []
    t = str(text or "")
    if _RE_OUTBOUND_LINK.search(t):
        violations.append("含链接或站外账号指向")
    if _RE_OUTBOUND_CONTACT.search(t):
        violations.append("含联系方式")
    if _RE_OUTBOUND_CTA.search(t):
        violations.append("含引流话术")
    return violations


# 抖音出站校验与小红书同一套（链接/联系方式/引流话术都是降权直接诱因）
dy_draft_violations = xhs_draft_violations


def classify_comment(text: str, platform: str = "bili") -> tuple[str, str]:
    """返回 (状态, 信号标签)。状态：target_a / target_b / excluded。"""
    text = (text or "").strip()
    is_short = len(text) < 8
    # 小红书/抖音短问句例外(2026-11-10 实测):「要钱吗」「什么软件」是截流场景
    # 最优质的购买/工具意图线索,且短问句是这两平台的评论常态;B 站该长度多为
    # 「哈哈哈哈」式水评,维持排除。放行的短问句仍要过下方垃圾/渠道/报错等
    # 内容闸,再交 LLM 精筛。
    if is_short and not (platform in ("xhs", "dy") and _RE_QUESTION_CUE.search(text)):
        return "excluded", "太短"
    for pat, label in (
        (_RE_SPAM, "垃圾广告"),
        (_RE_ACCESS, "使用渠道类"),
        (_RE_DEBUG, "个案报错"),
        (_RE_RESOURCE_BEG, "求UP私有资源"),
        (_RE_DIRECTOR, "导演式提问"),
        (_RE_RHETORIC, "反问/抒情"),
        (_RE_AI_WATER, "AI水评"),
        (_RE_AI_DECO, "AI装饰符"),
        (_RE_EXCLAIM, "纯感叹"),
    ):
        if pat.search(text):
            return "excluded", label
    if _RE_HOWTO.search(text):
        return "target_a", "问工具/怎么做"
    if _RE_NEWBIE.search(text) and _RE_QUESTION_CUE.search(text):
        return "target_b", "新手求路径"
    if (
        _RE_QUESTION_CUE.search(text)
        and _RE_SEEKING.search(text)
        and re.search(r"提示词|skill|软件|工具|模型|视频|动画|修图|配音", text)
    ):
        # 弱疑问 + 明确求助意图 + 实体词，交给人工闸门细看
        # (实体表已去掉 数学/学习/笔记——离域提问由 LLM 精筛判 lane=skip 拦下)
        return "target_b", "想动手求路径"
    if len(text) >= 12 and _RE_AI_ENTITY.search(text):
        # C 档:AI 相关且有实质内容的观点/体验/讨论——不求助也值得互动接话
        return "target_c", "AI相关观点/讨论"
    if is_short and platform in ("xhs", "dy"):
        # 走到这里 = xhs/dy 短问句且未撞任何内容闸(HOWTO/新手类已在前面上档)
        return "target_b", "短疑问(购买/工具线索)"
    return "excluded", "无提问"


