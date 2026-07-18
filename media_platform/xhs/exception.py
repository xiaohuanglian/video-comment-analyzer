from httpx import RequestError


class DataFetchError(RequestError):
    """something error when fetch"""


class IPBlockError(RequestError):
    """fetch so fast that the server block us ip"""


class NoteNotFoundError(RequestError):
    """Note does not exist or is abnormal"""
