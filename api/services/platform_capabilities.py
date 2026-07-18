# -*- coding: utf-8 -*-
"""Consumer-facing platform capability metadata."""

PLATFORM_CAPABILITIES = {
    "xhs": {
        "label": "小红书",
        "content_term": "笔记",
        "creator_term": "博主",
        "engagement_metric": "点赞",
        "supports_creator_rank": "true",
        "supports_sub_comments": "true",
        "direct_placeholder": "小红书笔记链接或笔记 ID",
    },
    "dy": {
        "label": "抖音",
        "content_term": "视频",
        "creator_term": "博主",
        "engagement_metric": "播放",
        "supports_creator_rank": "true",
        "supports_sub_comments": "true",
        "direct_placeholder": "抖音视频链接或视频 ID",
    },
    "ks": {
        "label": "快手",
        "content_term": "视频",
        "creator_term": "博主",
        "engagement_metric": "播放",
        "supports_creator_rank": "true",
        "supports_sub_comments": "true",
        "direct_placeholder": "快手视频链接或视频 ID",
    },
    "bili": {
        "label": "B站",
        "content_term": "视频",
        "creator_term": "UP 主",
        "engagement_metric": "播放",
        "supports_creator_rank": "true",
        "supports_sub_comments": "true",
        "direct_placeholder": "BV 号或 B 站视频完整链接",
    },
    "wb": {
        "label": "微博",
        "content_term": "微博",
        "creator_term": "博主",
        "engagement_metric": "转发",
        "supports_creator_rank": "true",
        "supports_sub_comments": "true",
        "direct_placeholder": "微博正文链接或微博 ID",
    },
    "tieba": {
        "label": "百度贴吧",
        "content_term": "帖子",
        "creator_term": "用户",
        "engagement_metric": "回复",
        "supports_creator_rank": "true",
        "supports_sub_comments": "true",
        "direct_placeholder": "贴吧帖子链接或帖子 ID",
    },
    "zhihu": {
        "label": "知乎",
        "content_term": "内容",
        "creator_term": "用户",
        "engagement_metric": "赞同",
        "supports_creator_rank": "true",
        "supports_sub_comments": "true",
        "direct_placeholder": "知乎回答、文章或视频链接",
    },
}


def get_platform_capabilities(platform: str) -> dict[str, str]:
    return dict(PLATFORM_CAPABILITIES.get(platform, {}))
