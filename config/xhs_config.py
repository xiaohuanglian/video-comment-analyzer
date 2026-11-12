# Xiaohongshu platform configuration

# Sorting method, the specific enumeration value is in media_platform/xhs/field.py
SORT_TYPE = "popularity_descending"

# Specify the note URL list, which must carry the xsec_token parameter
XHS_SPECIFIED_NOTE_URL_LIST = [
    "https://www.xiaohongshu.com/explore/64b95d01000000000c034587?xsec_token=AB0EFqJvINCkj6xOCKCQgfNNh8GdnBC_6XecG4QOddo3Q=&xsec_source=pc_cfeed"
    # ........................
]

# Specify the creator URL list, which needs to carry xsec_token and xsec_source parameters.

XHS_CREATOR_ID_LIST = [
    "https://www.xiaohongshu.com/user/profile/5f58bd990000000001003753?xsec_token=ABYVg1evluJZZzpMX-VWzchxQ1qSNVW3r-jOEnKqMcgZw=&xsec_source=pc_search"
    # ........................
]

# ---- 采集节奏（2026-11-12 事故后新增）----
# 12 个搜索词按通用 3–4.5s 间隔在 40 秒内打完，3 个词连续返回 461 CAPTCHA，
# 账号进入异常状态。小红书账号不可替换，间隔必须比通用值大一个量级。
# 风控冷却同时由 tools/crawl_pacing 的 crawl_guard 落盘（撞一次就停整平台）。
XHS_CRAWL_SLEEP_SEC = 20
XHS_CRAWL_SLEEP_JITTER_SEC = 12

# ---- 搜索接口单独一档（2026-11-12 加）----
# 同一天里：detail/feed 模式（2026-11-09，20 篇笔记 + 386 条评论）零风控信号；
# search 模式（2026-11-11，12 个关键词）40 秒后吃到 12 小时验证码。
# 差别不在签名——前 9 个词全部成功，说明签名是有效的——而在「主动搜库」这个动作。
# 所以 search 单独用更慢的节奏：单次间隔 45–90 秒，接近人在搜索框里换词的速度。
XHS_SEARCH_SLEEP_SEC = 45
XHS_SEARCH_JITTER_SEC = 45

# ---- 搜索的次数预算（2026-11-12 加，见 tools/xhs_safety.py）----
# 间隔只能降低速率，治不了「一天问 12 个不相关的话题」这个形态本身。
# 真人不会在 40 秒里连问 12 个话题；一天 6 次搜索、单批最多 4 个词，
# 更接近正常使用，也给账号留出恢复余地。
XHS_SEARCH_DAILY_LIMIT = 6
XHS_MAX_KEYWORDS_PER_BATCH = 4

# 账号级风控的冷却时长：平台封的是账号不是 IP，半小时不够降温。
# 12 小时内该平台任何采集（含 Web 面板）都会被 crawl_guard 直接拦下。
XHS_BLOCKED_COOLDOWN_SEC = 43200
