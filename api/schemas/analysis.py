# -*- coding: utf-8 -*-
"""Crawler-independent contracts for future comment analysis."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class DatasetStatus(str, Enum):
    COLLECTING = "collecting"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Content(BaseModel):
    content_id: str
    platform: str
    url: str = ""
    title: str = ""
    creator_id: str = ""
    creator_name: str = ""
    published_at: Optional[datetime] = None
    metrics: Dict[str, int] = Field(default_factory=dict)
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)


class Comment(BaseModel):
    comment_id: str
    content_id: str
    platform: str
    text: str
    parent_comment_id: Optional[str] = None
    author_id: str = ""
    author_name: str = ""
    published_at: Optional[datetime] = None
    like_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Dataset(BaseModel):
    dataset_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: Optional[str] = None
    workspace_id: Optional[str] = None
    job_id: Optional[str] = None
    status: DatasetStatus = DatasetStatus.COLLECTING
    content: Content
    comments: List[Comment] = Field(default_factory=list)
    source_files: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class AnalysisJob(BaseModel):
    analysis_job_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: Optional[str] = None
    workspace_id: Optional[str] = None
    dataset_id: str
    status: AnalysisStatus = AnalysisStatus.PENDING
    requested_modules: List[str] = Field(
        default_factory=lambda: ["opportunities", "pain_points", "competitors"]
    )
    result: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
