from .crawler import router as crawler_router
from .data import router as data_router
from .websocket import router as websocket_router
from .bilibili import router as bilibili_router
from .creator import router as creator_router
from .analysis import router as analysis_router

__all__ = [
    "crawler_router",
    "data_router",
    "websocket_router",
    "bilibili_router",
    "creator_router",
    "analysis_router",
]
