from .crawler import router as crawler_router
from .data import router as data_router
from .websocket import router as websocket_router
from .bilibili import router as bilibili_router
from .creator import router as creator_router
from .analysis import router as analysis_router
from .growth import router as growth_router
from .automation import router as automation_router
from .chat import router as chat_router
from .topics import router as topics_router
from .writer import router as writer_router
from .youvibe import router as youvibe_router
from .comments import router as comments_router
from .strategy import router as strategy_router
from .wechat import router as wechat_router

__all__ = [
    "crawler_router",
    "data_router",
    "websocket_router",
    "bilibili_router",
    "creator_router",
    "analysis_router",
    "growth_router",
    "automation_router",
    "chat_router",
    "topics_router",
    "writer_router",
    "youvibe_router",
    "comments_router",
    "strategy_router",
    "wechat_router",
]
