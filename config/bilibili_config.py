# bilili platform configuration

# Bilibili-specific crawl pacing (used when ENABLE_SAFE_CRAWL_MODE is True)
BILI_CRAWL_SLEEP_SEC = 4
BILI_CRAWL_SLEEP_JITTER_SEC = 2
BILI_COMMENT_EXTRA_PAUSE_EVERY = 8
BILI_COMMENT_EXTRA_PAUSE_SEC = 12
BILI_SUB_COMMENT_DELAY_SEC = 2
BILI_RATE_LIMIT_COOLDOWN_SEC = 35

# Creator comment rank defaults
BILI_CREATOR_RANK_TOP_N = 10
BILI_CREATOR_RANK_MAX_VIDEOS = 0

# Control the number of videos/posts crawled per day
MAX_NOTES_PER_DAY = 1

# Specify Bilibili video URL list (supports complete URL or BV number)
# Example:
# - Full URL: "https://www.bilibili.com/video/BV1dwuKzmE26/?spm_id_from=333.1387.homepage.video_card.click"
# - BV number: "BV1d54y1g7db"
BILI_SPECIFIED_ID_LIST = [
    "https://www.bilibili.com/video/BV1dwuKzmE26/?spm_id_from=333.1387.homepage.video_card.click",
    "BV1Sz4y1U77N",
    "BV14Q4y1n7jz",
    # ........................
]

# Specify the URL list of Bilibili creators (supports full URL or UID)
# Example:
# - Full URL: "https://space.bilibili.com/434377496?spm_id_from=333.1007.0.0"
# - UID: "20813884"
BILI_CREATOR_ID_LIST = [
    "https://space.bilibili.com/434377496?spm_id_from=333.1007.0.0",
    "20813884",
    # ........................
]

# Specify time range
START_DAY = "2024-01-01"
END_DAY = "2024-01-01"

# Search mode
BILI_SEARCH_MODE = "normal"

# Video definition (qn) configuration, common values:
# 16=360p, 32=480p, 64=720p, 80=1080p, 112=1080p high bit rate, 116=1080p60, 120=4K
# Note: Higher definition requires account/video support
BILI_QN = 80

# Whether to crawl user information
CREATOR_MODE = True

# Start crawling user information page number
START_CONTACTS_PAGE = 1

# Maximum number of crawled comments for a single video/post
CRAWLER_MAX_CONTACTS_COUNT_SINGLENOTES = 100

# Maximum number of crawled dynamics for a single video/post
CRAWLER_MAX_DYNAMICS_COUNT_SINGLENOTES = 50
