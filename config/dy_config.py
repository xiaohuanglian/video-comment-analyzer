# Douyin platform configuration
PUBLISH_TIME_TYPE = 0

# Specify DY video URL list (supports multiple formats)
# Supported formats:
# 1. Full video URL: "https://www.douyin.com/video/7525538910311632128"
# 2. URL with modal_id: "https://www.douyin.com/user/xxx?modal_id=7525538910311632128"
# 3. The search page has modal_id: "https://www.douyin.com/root/search/python?modal_id=7525538910311632128"
# 4. Short link: "https://v.douyin.com/drIPtQ_WPWY/"
# 5. Pure video ID: "7280854932641664319"
DY_SPECIFIED_ID_LIST = [
    "https://www.douyin.com/video/7525538910311632128",
    "https://v.douyin.com/drIPtQ_WPWY/",
    "https://www.douyin.com/user/MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE?from_tab_name=main&modal_id=7525538910311632128",
    "7202432992642387233",
    # ........................
]

# Specify DY creator URL list (supports full URL or sec_user_id)
# Supported formats:
# 1. Complete creator homepage URL: "https://www.douyin.com/user/MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE?from_tab_name=main"
# 2. sec_user_id: "MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE"
DY_CREATOR_ID_LIST = [
    "https://www.douyin.com/user/MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE?from_tab_name=main",
    "MS4wLjABAAAATJPY7LAlaa5X-c8uNdWkvz0jUGgpw4eeXIwu_8BhvqE"
    # ........................
]

# ---- 采集节奏（2026-11-12 与小红书同步收紧）----
# 抖音同样走浏览器签名 + 单一账号，沿用通用 3s 是同一类风险。
DY_CRAWL_SLEEP_SEC = 12
DY_CRAWL_SLEEP_JITTER_SEC = 8

# ---- 搜索接口单独一档（2026-11-12 复核时加）----
# 与小红书同一结论：detail（按视频 ID 取评论）是"我知道我要哪一条"，
# search 是"我在平台库里主动捞东西"，后者风控敏感度高一个量级。
# 此前抖音 search 用的是 config.CRAWLER_MAX_SLEEP_SEC（3s 原始值）——
# 比 detail 档还快 4 倍，是整条链路上最裸的一段。现在单列 45–90 秒。
DY_SEARCH_SLEEP_SEC = 45
DY_SEARCH_JITTER_SEC = 45

# ---- 搜索的次数预算（2026-11-12 加，见 tools/crawl_safety.py）----
# 比小红书更紧（4 次/天、单批 3 个词）：抖音只能用同一个登录态，
# 且搜索接口一撞就是账号级限制，恢复代价比小红书更高。
DY_SEARCH_DAILY_LIMIT = 4
DY_MAX_KEYWORDS_PER_BATCH = 3

# 账号级风控的冷却时长（与小红书同理，抖音同样只能用单一登录态）
# 6 小时：抖音的风控比小红书"短而凶"，多数情况几小时后自行解除；
# 撞一次停 6 小时，比"停 12 小时"更容易被执行（人不会因为太长而绕过去）。
DY_BLOCKED_COOLDOWN_SEC = 21600

# ---- 夜间静默（2026-11-12 加，见 tools/crawl_safety.py）----
# 与小红书共用同一套规则（真人要睡觉），时段也一致，但保留独立键：
# 万一以后要用"抖音只在白天采"来进一步降风险，改这里就行。
DY_QUIET_HOURS_START = 1
DY_QUIET_HOURS_END = 6

# ---- 请求超时（2026-11-12 加）----
# 抖音接口偶尔挂住（响应迟迟不来），默认 10s 太短、无限等又会占着浏览器。
# 只作用于**业务接口**；媒体下载（CDN 大文件）另有下限，见
# `media_platform/douyin/client.py:MEDIA_MIN_TIMEOUT_SEC`。
DY_REQUEST_TIMEOUT_SEC = 20

# 关于「连续 N 次空响应才判风控」：**故意不做**。
# `_classify_response` 只在 body 为空 / 是挑战页 / 业务码报错时才判拦截，
# "这一页评论就是没有了"（`comments: []` + `has_more: 0`）走的是正常分支，
# 本来就不会误伤。剩下的单次空 body 要么是签名失效、要么是被标记，
# 两种情况都不该再打第二枪——多打一次是拿账号换一次确认。

# ---- TLS 指纹（2026-11-12 加，见 tools/httpx_util.py）----
# 抖音业务接口走 curl_cffi 的 Chrome TLS 指纹：裸 httpx 的 JA3/HTTP2 指纹
# 本身就是"这是脚本"的证据。实测同一个 favicon 地址，httpx 302 / curl_cffi
# impersonate="chrome" 200，UA 与 header 完全一致，差别只在握手。
# 可填 "chrome"（跟随 curl_cffi 推荐的当前版本）或钉死某一版（如 "chrome131"）。
# 钉死版本会随 Chrome 升级逐渐变成一个"不存在的旧浏览器"，只在排查时用。
DY_TLS_IMPERSONATE_PROFILE = "chrome"

# ---- 登录滑块（2026-11-12 收敛）----
# 以前：20 次尝试，失败还会点"刷新验证码"再继续，而那个刷新**不扣次数**。
# 对已经被标记的账号反复刷滑块不是解题，是加刑（小红书 461 事故同型：
# 越重试越深）。现在主动尝试 3 次，刷新验证码最多 1 次，仍失败就抛
# CaptchaError → 平台冷却 → 停下来等人。
# 人可以在浏览器窗口里手动过验证码；机器不行。
DY_SLIDER_MAX_ATTEMPTS = 3
DY_SLIDER_MAX_REFRESH = 1
