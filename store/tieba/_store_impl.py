# -*- coding: utf-8 -*-
# @Time    : 2025/9/5 19:34
# @Desc    : Tieba storage implementation class
import asyncio
import csv
import json
import os
import pathlib
from typing import Dict

import aiofiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from base.base_crawler import AbstractStore
from database.models import TiebaNote, TiebaComment, TiebaCreator
from tools import utils, words
from database.db_session import get_session
from var import crawler_type_var
from tools.async_file_writer import AsyncFileWriter
from database.mongodb_store_base import MongoDBStoreBase


def calculate_number_of_files(file_store_path: str) -> int:
    """Calculate the prefix sorting number for data save files, supporting writing to different files for each run
    Args:
        file_store_path;
    Returns:
        file nums
    """
    if not os.path.exists(file_store_path):
        return 1
    try:
        return max([int(file_name.split("_")[0]) for file_name in os.listdir(file_store_path)]) + 1
    except ValueError:
        return 1


class TieBaCsvStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="tieba", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        """
        tieba content CSV storage implementation
        Args:
            content_item: note item dict

        Returns:

        """
        await self.writer.write_to_csv(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        """
        tieba comment CSV storage implementation
        Args:
            comment_item: comment item dict

        Returns:

        """
        await self.writer.write_to_csv(item_type="comments", item=comment_item)

    async def store_creator(self, creator: Dict):
        """
        tieba content CSV storage implementation
        Args:
            creator: creator dict

        Returns:

        """
        await self.writer.write_to_csv(item_type="creators", item=creator)


class TieBaDbStoreImplement(AbstractStore):
    async def store_content(self, content_item: Dict):
        """
        tieba content DB storage implementation
        Args:
            content_item: content item dict
        """
        note_id = content_item.get("note_id")
        async with get_session() as session:
            stmt = select(TiebaNote).where(TiebaNote.note_id == note_id)
            res = await session.execute(stmt)
            db_note = res.scalar_one_or_none()
            if db_note:
                for key, value in content_item.items():
                    setattr(db_note, key, value)
            else:
                db_note = TiebaNote(**content_item)
                session.add(db_note)
            await session.commit()

    async def store_comment(self, comment_item: Dict):
        """
        tieba content DB storage implementation
        Args:
            comment_item: comment item dict
        """
        comment_id = comment_item.get("comment_id")
        async with get_session() as session:
            stmt = select(TiebaComment).where(TiebaComment.comment_id == comment_id)
            res = await session.execute(stmt)
            db_comment = res.scalar_one_or_none()
            if db_comment:
                for key, value in comment_item.items():
                    setattr(db_comment, key, value)
            else:
                db_comment = TiebaComment(**comment_item)
                session.add(db_comment)
            await session.commit()

    async def store_creator(self, creator: Dict):
        """
        tieba content DB storage implementation
        Args:
            creator: creator dict
        """
        user_id = creator.get("user_id")
        async with get_session() as session:
            stmt = select(TiebaCreator).where(TiebaCreator.user_id == user_id)
            res = await session.execute(stmt)
            db_creator = res.scalar_one_or_none()
            if db_creator:
                for key, value in creator.items():
                    setattr(db_creator, key, value)
            else:
                db_creator = TiebaCreator(**creator)
                session.add(db_creator)
            await session.commit()


class TieBaJsonStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="tieba", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        """
        tieba content JSON storage implementation
        Args:
            content_item: note item dict

        Returns:

        """
        await self.writer.write_single_item_to_json(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        """
        tieba comment JSON storage implementation
        Args:
            comment_item: comment item dict

        Returns:

        """
        await self.writer.write_single_item_to_json(item_type="comments", item=comment_item)

    async def store_creator(self, creator: Dict):
        """
        tieba content JSON storage implementation
        Args:
            creator: creator dict

        Returns:

        """
        await self.writer.write_single_item_to_json(item_type="creators", item=creator)


class TieBaJsonlStoreImplement(AbstractStore):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.writer = AsyncFileWriter(platform="tieba", crawler_type=crawler_type_var.get())

    async def store_content(self, content_item: Dict):
        await self.writer.write_to_jsonl(item_type="contents", item=content_item)

    async def store_comment(self, comment_item: Dict):
        await self.writer.write_to_jsonl(item_type="comments", item=comment_item)

    async def store_creator(self, creator: Dict):
        await self.writer.write_to_jsonl(item_type="creators", item=creator)


class TieBaSqliteStoreImplement(TieBaDbStoreImplement):
    """
    Tieba sqlite store implement
    """
    pass


class TieBaMongoStoreImplement(AbstractStore):
    """Tieba MongoDB storage implementation"""

    def __init__(self):
        self.mongo_store = MongoDBStoreBase(collection_prefix="tieba")

    async def store_content(self, content_item: Dict):
        """
        Store post content to MongoDB
        Args:
            content_item: Post content data
        """
        note_id = content_item.get("note_id")
        if not note_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="contents",
            query={"note_id": note_id},
            data=content_item
        )
        utils.logger.info(f"[TieBaMongoStoreImplement.store_content] Saved note {note_id} to MongoDB")

    async def store_comment(self, comment_item: Dict):
        """
        Store comment to MongoDB
        Args:
            comment_item: Comment data
        """
        comment_id = comment_item.get("comment_id")
        if not comment_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="comments",
            query={"comment_id": comment_id},
            data=comment_item
        )
        utils.logger.info(f"[TieBaMongoStoreImplement.store_comment] Saved comment {comment_id} to MongoDB")

    async def store_creator(self, creator_item: Dict):
        """
        Store creator information to MongoDB
        Args:
            creator_item: Creator data
        """
        user_id = creator_item.get("user_id")
        if not user_id:
            return

        await self.mongo_store.save_or_update(
            collection_suffix="creators",
            query={"user_id": user_id},
            data=creator_item
        )
        utils.logger.info(f"[TieBaMongoStoreImplement.store_creator] Saved creator {user_id} to MongoDB")


class TieBaExcelStoreImplement:
    """Tieba Excel storage implementation - Global singleton"""

    def __new__(cls, *args, **kwargs):
        from store.excel_store_base import ExcelStoreBase
        return ExcelStoreBase.get_instance(
            platform="tieba",
            crawler_type=crawler_type_var.get()
        )
