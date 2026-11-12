# Zhihu platform configuration

# Specify Zhihu user URL list
ZHIHU_CREATOR_URL_LIST = [
    "https://www.zhihu.com/people/yd1234567",
    # ........................
]

# Specify Zhihu ID list
ZHIHU_SPECIFIED_ID_LIST = [
    "https://www.zhihu.com/question/826896610/answer/4885821440",  # answer
    "https://zhuanlan.zhihu.com/p/673461588",  # article
    "https://www.zhihu.com/zvideo/1539542068422144000",  # video
]

# ---- 采集节奏（2026-11-12 加）----
# 知乎此前**没有任何平台级节奏**：每个请求固定 sleep 3s，没有冷却、没有并发槽，
# 403 只抛 ForbiddenError 不记账——等于裸奔。知乎对同 IP 高频 API 很敏感，
# 典型返回 403/412 或弹人机验证，所以按「宁可慢」给一档：8s + 0–4s 抖动。
# 风控冷却与并发槽由 tools/crawl_pacing 统一管理（撞一次就停整平台）。
ZHIHU_CRAWL_SLEEP_SEC = 8
ZHIHU_CRAWL_SLEEP_JITTER_SEC = 4
