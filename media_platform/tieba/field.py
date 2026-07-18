from enum import Enum


class SearchSortType(Enum):
    """search sort type"""
    # Sort by time in descending order
    TIME_DESC = "1"
    # Sort by time in ascending order
    TIME_ASC = "0"
    # Sort by relevance
    RELEVANCE_ORDER = "2"


class SearchNoteType(Enum):
    # Only view main posts
    MAIN_THREAD = "1"
    # Mixed mode (posts + replies)
    FIXED_THREAD = "0"
