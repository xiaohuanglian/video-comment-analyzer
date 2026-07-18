from enum import Enum
from typing import Optional, Literal
from pathlib import PurePath

from pydantic import BaseModel, Field, field_validator


MAX_API_LIMIT_COUNT = 50000


class PlatformEnum(str, Enum):
    """Supported media platforms"""
    XHS = "xhs"
    DOUYIN = "dy"
    KUAISHOU = "ks"
    BILIBILI = "bili"
    WEIBO = "wb"
    TIEBA = "tieba"
    ZHIHU = "zhihu"


class LoginTypeEnum(str, Enum):
    """Login method"""
    QRCODE = "qrcode"
    PHONE = "phone"
    COOKIE = "cookie"


class CrawlerTypeEnum(str, Enum):
    """Crawler type"""
    SEARCH = "search"
    DETAIL = "detail"
    CREATOR = "creator"


class SaveDataOptionEnum(str, Enum):
    """Data save option"""
    CSV = "csv"
    DB = "db"
    JSON = "json"
    JSONL = "jsonl"
    SQLITE = "sqlite"
    MONGODB = "mongodb"
    EXCEL = "excel"


class CrawlerStartRequest(BaseModel):
    """Crawler start request"""
    platform: PlatformEnum
    login_type: LoginTypeEnum = LoginTypeEnum.QRCODE
    crawler_type: CrawlerTypeEnum = CrawlerTypeEnum.DETAIL
    keywords: str = ""  # Keywords for search mode
    specified_ids: str = ""  # Post/video ID list for detail mode, comma-separated
    creator_ids: str = ""  # Creator ID list for creator mode, comma-separated
    start_page: int = 1
    enable_comments: bool = True
    enable_sub_comments: bool = False
    save_option: SaveDataOptionEnum = SaveDataOptionEnum.JSONL
    save_data_path: str = "./data/comments"
    cookies: str = ""
    headless: bool = False
    max_notes_count: Optional[int] = Field(default=1, ge=1, le=MAX_API_LIMIT_COUNT)
    max_comments_count: Optional[int] = None
    enable_safe_crawl: bool = True
    crawler_max_sleep_sec: float = Field(default=4.0, ge=1.0, le=30.0)
    split_by_video: bool = True
    fresh_crawl: bool = False

    @field_validator("save_data_path")
    @classmethod
    def validate_save_data_path(cls, value: str) -> str:
        """Keep all WebUI output inside the project data directory."""
        raw = (value or "./data/comments").strip().replace("\\", "/")
        if PurePath(raw).is_absolute():
            raise ValueError("保存根目录必须使用 data/ 下的相对路径")
        normalized = raw[2:] if raw.startswith("./") else raw
        parts = PurePath(normalized).parts
        if ".." in parts or not parts or parts[0] != "data":
            raise ValueError("保存根目录只能位于项目 data/ 目录内")
        return f"./{normalized}"


class CrawlerStatusResponse(BaseModel):
    """Crawler status response"""
    status: Literal["idle", "running", "stopping", "error"]
    platform: Optional[str] = None
    crawler_type: Optional[str] = None
    started_at: Optional[str] = None
    error_message: Optional[str] = None
    comments_crawled: Optional[int] = None
    comments_target: Optional[int] = None
    progress_updated_at: Optional[str] = None
    result_kind: Optional[Literal["completed", "partial", "stopped", "error"]] = None
    result_title: Optional[str] = None
    result_message: Optional[str] = None
    finished_at: Optional[str] = None


class LogEntry(BaseModel):
    """Log entry"""
    id: int
    timestamp: str
    level: Literal["info", "warning", "error", "success", "debug"]
    message: str


class DataFileInfo(BaseModel):
    """Data file information"""
    name: str
    path: str
    size: int
    modified_at: str
    record_count: Optional[int] = None
