# -*- coding: utf-8 -*-
# @Time    : 2023/12/23 15:41
# @Desc    :
from enum import Enum


class SearchType(Enum):
    # Comprehensive
    DEFAULT = "1"

    # Real-time
    REAL_TIME = "61"

    # Popular
    POPULAR = "60"

    # Video
    VIDEO = "64"
