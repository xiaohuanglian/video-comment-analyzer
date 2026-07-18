# -*- coding: utf-8 -*-
# @Time    : 2023/12/3 16:20
# @Desc    :

from enum import Enum


class SearchOrderType(Enum):
    # Comprehensive sorting
    DEFAULT = ""

    # Most clicks
    MOST_CLICK = "click"

    # Latest published
    LAST_PUBLISH = "pubdate"

    # Most danmu (comments)
    MOST_DANMU = "dm"

    # Most bookmarks
    MOST_MARK = "stow"


class CommentOrderType(Enum):
    # By popularity only
    DEFAULT = 0

    # By popularity + time
    MIXED = 1

    # By time
    TIME = 2
