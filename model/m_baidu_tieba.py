# -*- coding: utf-8 -*-
from typing import Optional

from pydantic import BaseModel, Field


class TiebaNote(BaseModel):
    """
    Baidu Tieba post
    """
    note_id: str = Field(..., description="Post ID")
    title: str = Field(..., description="Post title")
    desc: str = Field(default="", description="Post description")
    note_url: str = Field(..., description="Post link")
    publish_time: str = Field(default="", description="Publish time")
    user_link: str = Field(default="", description="User homepage link")
    user_nickname: str = Field(default="", description="User nickname")
    user_avatar: str = Field(default="", description="User avatar URL")
    tieba_name: str = Field(..., description="Tieba name")
    tieba_link: str = Field(..., description="Tieba link")
    total_replay_num: int = Field(default=0, description="Total reply count")
    total_replay_page: int = Field(default=0, description="Total reply pages")
    ip_location: Optional[str] = Field(default="", description="IP location")
    source_keyword: str = Field(default="", description="Source keyword")


class TiebaComment(BaseModel):
    """
    Baidu Tieba comment
    """

    comment_id: str = Field(..., description="Comment ID")
    parent_comment_id: str = Field(default="", description="Parent comment ID")
    content: str = Field(..., description="Comment content")
    user_link: str = Field(default="", description="User homepage link")
    user_nickname: str = Field(default="", description="User nickname")
    user_avatar: str = Field(default="", description="User avatar URL")
    publish_time: str = Field(default="", description="Publish time")
    ip_location: Optional[str] = Field(default="", description="IP location")
    sub_comment_count: int = Field(default=0, description="Sub-comment count")
    note_id: str = Field(..., description="Post ID")
    note_url: str = Field(..., description="Post link")
    tieba_id: str = Field(..., description="Tieba ID")
    tieba_name: str = Field(..., description="Tieba name")
    tieba_link: str = Field(..., description="Tieba link")


class TiebaCreator(BaseModel):
    """
    Baidu Tieba creator
    """
    user_id: str = Field(..., description="User ID")
    user_name: str = Field(..., description="Username")
    nickname: str = Field(..., description="User nickname")
    gender: str = Field(default="", description="User gender")
    avatar: str = Field(..., description="User avatar URL")
    ip_location: Optional[str] = Field(default="", description="IP location")
    follows: int = Field(default=0, description="Follows count")
    fans: int = Field(default=0, description="Fans count")
    registration_duration: str = Field(default="", description="Registration duration")
