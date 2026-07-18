# Weibo platform configuration

# Search type, the specific enumeration value is in media_platform/weibo/field.py
WEIBO_SEARCH_TYPE = "default"

# Specify Weibo ID list
WEIBO_SPECIFIED_ID_LIST = [
    "4982041758140155",
    # ........................
]

# Specify Weibo user ID list
WEIBO_CREATOR_ID_LIST = [
    "5756404150",
    # ........................
]

# Whether to enable the function of crawling the full text of Weibo. It is enabled by default.
# If turned on, it will increase the probability of being risk controlled, which is equivalent to a keyword search request that will traverse all posts and request the post details again.
ENABLE_WEIBO_FULL_TEXT = True
