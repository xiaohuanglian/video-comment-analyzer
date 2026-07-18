from enum import Enum


class SearchChannelType(Enum):
    """search channel type"""
    GENERAL = "aweme_general"  # General
    VIDEO = "aweme_video_web"  # Video
    USER = "aweme_user_web"  # User
    LIVE = "aweme_live"  # Live


class SearchSortType(Enum):
    """search sort type"""
    GENERAL = 0  # Comprehensive sorting
    MOST_LIKE = 1  # Most likes
    LATEST = 2  # Latest published

class PublishTimeType(Enum):
    """publish time type"""
    UNLIMITED = 0  # Unlimited
    ONE_DAY = 1  # Within one day
    ONE_WEEK = 7  # Within one week
    SIX_MONTH = 180  # Within six months
