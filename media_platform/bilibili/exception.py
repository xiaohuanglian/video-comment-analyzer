# -*- coding: utf-8 -*-
# @Time    : 2023/12/2 18:44
# @Desc    :

from httpx import RequestError


class DataFetchError(RequestError):
    """something error when fetch"""

    def __init__(self, message: str, *, code: int | None = None, rate_limited: bool = False):
        super().__init__(message)
        self.code = code
        self.rate_limited = rate_limited


class IPBlockError(RequestError):
    """fetch so fast that the server block us ip"""
