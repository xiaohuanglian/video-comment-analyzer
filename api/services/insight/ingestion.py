# -*- coding: utf-8 -*-
"""Load comment CSV/XLSX from data directory into source records."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from api.services.dataset_normalizer import infer_platform, normalize_rows

from .field_mapping import (
    derive_bilibili_links,
    detect_field_mapping,
    infer_creator_type_from_path,
    row_value,
)
from .schemas import FieldMapping, SourceRecord
from .utils import extract_video_label, safe_int

APP_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = APP_DIR / "data"


def list_comment_sources() -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    if not DATA_DIR.exists():
        return files
    for path in sorted(DATA_DIR.rglob("comments_*.csv")):
        try:
            rel = str(path.relative_to(DATA_DIR))
            stat = path.stat()
            platform = infer_platform(rel, [])
            creator_type = infer_creator_type_from_path(rel)
            folder = str(path.parent.relative_to(DATA_DIR))
            parts = Path(folder).parts
            category = parts[0] if parts else "其他"
            creator = parts[1] if len(parts) > 1 else "未知"
            comment_count = 0
            try:
                _, rows = _read_csv_rows(path)
                for row in rows:
                    text = str(
                        row.get("content")
                        or row.get("comment_text")
                        or row.get("text")
                        or row.get("desc")
                        or ""
                    ).strip()
                    if text:
                        comment_count += 1
            except Exception:
                comment_count = 0
            files.append(
                {
                    "path": rel,
                    "name": path.name,
                    "size": stat.st_size,
                    "platform_hint": platform,
                    "creator_type_hint": creator_type,
                    "folder": folder,
                    "category": category,
                    "creator": creator,
                    "video_label": extract_video_label(folder),
                    "comment_count": comment_count,
                }
            )
        except OSError:
            continue
    return files


def list_comment_sources_grouped() -> Dict[str, Any]:
    files = list_comment_sources()
    groups: Dict[str, Dict[str, Any]] = {}
    total_comments = 0
    for item in files:
        total_comments += item.get("comment_count") or 0
        category = item["category"]
        creator = item["creator"]
        groups.setdefault(category, {"category": category, "creators": {}, "file_count": 0, "comment_count": 0})
        cat = groups[category]
        cat["file_count"] += 1
        cat["comment_count"] += item.get("comment_count") or 0
        cat["creators"].setdefault(creator, {"creator": creator, "files": [], "file_count": 0, "comment_count": 0})
        cr = cat["creators"][creator]
        cr["files"].append(item)
        cr["file_count"] += 1
        cr["comment_count"] += item.get("comment_count") or 0

    ordered = []
    for category in sorted(groups.keys()):
        group = groups[category]
        creators = []
        for creator_name in sorted(group["creators"].keys()):
            cr = group["creators"][creator_name]
            cr["files"].sort(key=lambda f: f.get("comment_count") or 0, reverse=True)
            creators.append(cr)
        ordered.append(
            {
                "category": category,
                "file_count": group["file_count"],
                "comment_count": group["comment_count"],
                "creators": creators,
            }
        )
    return {"groups": ordered, "total_files": len(files), "total_comments": total_comments}


def _read_csv_rows(file_path: Path) -> tuple[List[str], List[Dict[str, Any]]]:
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            df = pd.read_csv(
                file_path,
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
                on_bad_lines="skip",
            )
            df = df.fillna("")
            columns = [str(col) for col in df.columns]
            rows = [{str(k): ("" if v is None else str(v)) for k, v in row.items()} for row in df.to_dict(orient="records")]
            return columns, rows
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            continue
    raise ValueError(f"无法读取 CSV：{file_path.name} ({last_error})")


def preview_file(rel_path: str, limit: int = 20) -> Dict[str, Any]:
    from .run_locations import resolve_under_data

    full_path = resolve_under_data(rel_path)
    if not full_path.exists():
        raise FileNotFoundError(rel_path)
    columns, rows = _read_csv_rows(full_path)
    mapping = detect_field_mapping(columns, rel_path)
    return {
        "path": rel_path,
        "columns": columns,
        "suggested_mapping": mapping.model_dump(),
        "preview_rows": rows[:limit],
        "total_rows": len(rows),
    }


def ingest_files(
    file_paths: List[str],
    field_mapping: Optional[FieldMapping] = None,
    fixed_creator_type: Optional[str] = None,
    fixed_platform: Optional[str] = None,
) -> List[SourceRecord]:
    from .run_locations import resolve_under_data

    records: List[SourceRecord] = []
    for rel_path in file_paths:
        full_path = resolve_under_data(rel_path)
        if not full_path.exists():
            raise FileNotFoundError(rel_path)
        columns, rows = _read_csv_rows(full_path)
        mapping = field_mapping or detect_field_mapping(columns, rel_path)
        platform = fixed_platform or infer_platform(rel_path, rows)
        if mapping.platform and mapping.platform in columns:
            platform = row_value(rows[0], mapping.platform) if rows else platform
        creator_type = fixed_creator_type or mapping.creator_type or infer_creator_type_from_path(rel_path)
        dataset = normalize_rows(rows, source_path=rel_path, platform=platform)
        video_title = dataset.content.title
        if mapping.video_title:
            first_title = row_value(rows[0], mapping.video_title) if rows else ""
            if first_title:
                video_title = first_title
        if not video_title or video_title == Path(rel_path).stem:
            video_title = extract_video_label(str(Path(rel_path).parent))
        creator_name = dataset.content.creator_name
        if mapping.creator_name:
            first_creator = row_value(rows[0], mapping.creator_name) if rows else ""
            if first_creator:
                creator_name = first_creator
        if not creator_name:
            parts = Path(rel_path).parent.parts
            if len(parts) >= 2:
                creator_name = parts[1]
        for index, row in enumerate(rows, start=2):
            comment_text = row_value(row, mapping.comment_text)
            if not comment_text:
                continue
            user_id = row_value(row, mapping.user_id)
            video_id = str(row.get("video_id") or row.get("note_id") or row.get("aweme_id") or "")
            comment_id = str(row.get("comment_id") or row.get("id") or "")
            homepage = row_value(row, mapping.user_homepage_url)
            comment_url = row_value(row, mapping.comment_url)
            derived_homepage, derived_comment = derive_bilibili_links(platform, user_id, video_id, comment_id)
            if not homepage:
                homepage = derived_homepage
            if not comment_url:
                comment_url = derived_comment
            internal_id = f"{rel_path}:{index}:{uuid.uuid4().hex[:8]}"
            records.append(
                SourceRecord(
                    internal_record_id=internal_id,
                    source_file=rel_path,
                    source_row_number=index,
                    raw_data=dict(row),
                    comment_text=comment_text,
                    parent_comment=row_value(row, "parent_comment") or "",
                    creator_reply=row_value(row, "creator_reply") or "",
                    username=row_value(row, mapping.username),
                    user_id=user_id,
                    user_homepage_url=homepage,
                    comment_url=comment_url,
                    video_title=video_title,
                    video_url=str(row.get("video_url") or dataset.content.url or ""),
                    creator_name=creator_name,
                    creator_type=creator_type,
                    platform=platform,
                    like_count=safe_int(row.get("like_count") or row.get("liked_count")),
                    reply_count=safe_int(row.get("sub_comment_count") or row.get("reply_count")),
                )
            )
    return records
