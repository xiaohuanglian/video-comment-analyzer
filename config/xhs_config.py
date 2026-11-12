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

# 账号级风控的冷却时长：平台封的是账号不是 IP，半小时不够降温。
# 12 小时内该平台任何采集（含 Web 面板）都会被 crawl_guard 直接拦下。
XHS_BLOCKED_COOLDOWN_SEC = 43200
