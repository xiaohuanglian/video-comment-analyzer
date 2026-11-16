# -*- coding: utf-8 -*-
"""数据文件浏览/预览/下载接口。

安全约束（2026-11-11 审计修复）：
    本路由曾是**默认全开**——`data/` 下任何文件都能列出来、预览、下载。
    而 `data/` 同时放着 `model_settings.json`（LLM 网关密钥）和
    `automation/bili_cookie.json`（可接管账号的登录 Cookie），
    等于把凭据挂在无鉴权 HTTP 接口上明文取走。

    现在的口径是**默认拒绝**：
    1. 只认白名单目录（`ALLOWED_DIRS`）——新增的内部状态目录默认不可见；
    2. 只认数据文件扩展名（`ALLOWED_SUFFIXES`）——`.md`/`.html` 等原文可见，
       `.json/.jsonl/.csv/.xlsx` 之外一律 403；
    3. 文件名命中 `_SENSITIVE_NAME`（cookie/secret/token/settings/credential…）
       一律 403，作为白名单失守时的第二道闸；
    4. 符号链接按 `resolve()` 后的真实路径判定，不能借软链跳出白名单。

浏览是只读能力，不做任何写操作。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from tools.save_path_utils import count_csv_rows

from ..services.dataset_normalizer import normalize_rows

router = APIRouter(prefix="/data", tags=["data"])

# Data directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"

#: 允许浏览的目录（相对 DATA_DIR）。**新增目录要显式加进来**，
#: 内部状态目录与派生素材目录（队列、cookie、密钥、中间态和内部语料）
#: 以及 data 根目录一律不开放——那里放的不是用户要下载的采集结果。
ALLOWED_DIRS: tuple[str, ...] = (
    "comments",
    "wechat",
    "youtube_comments",
    "xhs_browse",
    "analysis",
    "bench",
)

#: 允许读取/预览/下载的扩展名。
ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {".json", ".jsonl", ".csv", ".xlsx", ".xls", ".md", ".html", ".htm", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
)

#: 命中即拒绝的文件名片段（白名单失守时的兜底）。
_SENSITIVE_NAME = (
    "cookie",
    "secret",
    "token",
    "credential",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "settings",
    "private",
    "session",
)

_LIST_CACHE_TTL_SECONDS = 10.0
_list_cache_lock = threading.Lock()
_list_cache: dict[tuple[str, tuple[tuple[str, int, int], ...]], tuple[float, list[dict]]] = {}


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _SENSITIVE_NAME)


def _assert_browsable(rel: str) -> None:
    """白名单校验：目录必须允许、扩展名必须允许、名字不能像凭据。"""
    parts = [p for p in Path(rel).parts if p not in ("", ".")]
    if not parts:
        raise _forbidden("不能访问 data 根目录")
    if any(part.startswith(".") for part in parts):
        raise _forbidden("不能访问隐藏目录或隐藏文件")
    if parts[0] not in ALLOWED_DIRS:
        raise _forbidden(f"目录 {parts[0]} 不在可浏览白名单内")
    name = parts[-1]
    if _is_sensitive_name(name):
        raise _forbidden("该文件名被标记为敏感，不允许通过此接口读取")
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise _forbidden(f"不支持的文件类型：{Path(name).suffix or '无扩展名'}")


def _resolve_data_file(file_path: str) -> Path:
    """把相对路径解析成 DATA_DIR 内的真实文件，越界/不在白名单一律 403。"""
    try:
        full_path = (DATA_DIR / file_path).resolve()
        root = DATA_DIR.resolve()
        rel = full_path.relative_to(root)
    except ValueError as exc:
        raise _forbidden("Access denied") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"无法解析路径：{exc}") from exc

    _assert_browsable(str(rel))

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")
    return full_path


def _count_csv_rows(path: Path, *, quick: bool = False) -> Optional[int]:
    return count_csv_rows(path, quick=quick)


#: 单文件条数缓存：key=(相对路径, mtime_ns, size) → (解析时间, 条数)。
#: 列表接口原先对每个 json 都做一次完整 `json.load`，261 个文件意味着
#: 每次刷新都要把几十 MB 重新解析一遍；文件没变就不该重复算。
_info_cache: dict[tuple[str, int, int], tuple[float, Optional[int]]] = {}
_info_cache_lock = threading.Lock()


def _record_count(file_path: Path, rel: str) -> Optional[int]:
    try:
        stat = file_path.stat()
    except OSError:
        return None
    key = (rel, stat.st_mtime_ns, stat.st_size)
    now = time.time()
    with _info_cache_lock:
        hit = _info_cache.get(key)
        if hit and now - hit[0] < 3600:
            return hit[1]

    record_count: Optional[int] = None
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".json":
            # 只为拿条数：list 才数，dict 视为 1 条，不递归。
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            record_count = len(data) if isinstance(data, list) else 1
        elif suffix == ".csv":
            record_count = _count_csv_rows(file_path, quick=True)
        elif suffix == ".jsonl":
            if stat.st_size <= 512 * 1024:
                with open(file_path, "r", encoding="utf-8") as f:
                    record_count = sum(1 for line in f if line.strip())
            else:
                record_count = None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        record_count = None

    with _info_cache_lock:
        _info_cache[key] = (now, record_count)
        if len(_info_cache) > 4096:  # 防止长期运行无限增长
            _info_cache.clear()
            _info_cache[key] = (now, record_count)
    return record_count


def get_file_info(file_path: Path) -> dict:
    """Get file information"""
    stat = file_path.stat()
    rel = str(file_path.relative_to(DATA_DIR))
    return {
        "name": file_path.name,
        "path": rel,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "record_count": _record_count(file_path, rel),
        "type": file_path.suffix[1:] if file_path.suffix else "unknown",
    }


def _iter_browsable_files() -> list[tuple[Path, str]]:
    """遍历白名单目录下所有允许浏览的文件（相对路径一并返回）。"""
    found: list[tuple[Path, str]] = []
    if not DATA_DIR.exists():
        return found
    root = DATA_DIR.resolve()
    for dirname in ALLOWED_DIRS:
        base = DATA_DIR / dirname
        if not base.is_dir():
            continue
        for current, subdirs, filenames in os.walk(base):
            subdirs[:] = [d for d in subdirs if not d.startswith(".")]
            for filename in filenames:
                if filename.startswith("."):
                    continue
                file_path = Path(current) / filename
                try:
                    rel = str(file_path.resolve().relative_to(root))
                except (ValueError, OSError):
                    continue
                try:
                    _assert_browsable(rel)
                except HTTPException:
                    continue
                found.append((file_path, rel))
    return found


def _list_signature() -> tuple[tuple[str, int, int], ...]:
    """目录指纹：任一文件的 mtime/size 变化即视为需要重扫。"""
    sig: list[tuple[str, int, int]] = []
    for file_path, rel in _iter_browsable_files():
        try:
            stat = file_path.stat()
        except OSError:
            continue
        sig.append((rel, stat.st_mtime_ns, stat.st_size))
    sig.sort()
    return tuple(sig)


@router.get("/files")
async def list_data_files(platform: Optional[str] = None, file_type: Optional[str] = None):
    """Get data file list"""
    if not DATA_DIR.exists():
        return {"files": []}

    signature = _list_signature()
    cache_key = (str(DATA_DIR), signature)
    now = time.time()
    with _list_cache_lock:
        cached = _list_cache.get(cache_key)
        if cached and now - cached[0] < _LIST_CACHE_TTL_SECONDS:
            entries = [dict(item) for item in cached[1]]
        else:
            entries = []
            for file_path, _rel in _iter_browsable_files():
                try:
                    entries.append(get_file_info(file_path))
                except (OSError, ValueError):
                    continue
            _list_cache.clear()
            _list_cache[cache_key] = (now, [dict(item) for item in entries])

    files = []
    for item in entries:
        rel_path = item["path"]
        if platform and platform.lower() not in rel_path.lower():
            continue
        if file_type and item["type"].lower() != file_type.lower():
            continue
        files.append(item)

    files.sort(key=lambda x: x["modified_at"], reverse=True)
    return {"files": files}


@router.get("/dataset/{file_path:path}")
async def get_normalized_dataset(
    file_path: str,
    limit: int = Query(default=5000, ge=1, le=10000),
):
    """Convert a crawler result file to the stable analysis contract."""
    full_path = _resolve_data_file(file_path)
    rows = []
    try:
        if full_path.suffix.lower() == ".csv":
            import csv

            with open(full_path, "r", encoding="utf-8") as file:
                for index, row in enumerate(csv.DictReader(file)):
                    if index >= limit:
                        break
                    rows.append(row)
        elif full_path.suffix.lower() == ".jsonl":
            with open(full_path, "r", encoding="utf-8") as file:
                for line in file:
                    if len(rows) >= limit:
                        break
                    if line.strip():
                        rows.append(json.loads(line))
        elif full_path.suffix.lower() == ".json":
            with open(full_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            rows = (payload if isinstance(payload, list) else [payload])[:limit]
        else:
            raise HTTPException(
                status_code=400,
                detail="标准化接口当前支持 CSV、JSONL 与 JSON 文件",
            )
    except HTTPException:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"无法读取数据文件：{exc}") from exc

    return normalize_rows(rows, source_path=file_path).model_dump(mode="json")


def _preview_payload(full_path: Path, limit: int) -> dict:
    suffix = full_path.suffix.lower()
    if suffix == ".json":
        with open(full_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {"data": data[:limit], "total": len(data), "truncated": len(data) > limit}
        return {"data": data, "total": 1, "truncated": False}

    if suffix == ".csv":
        import csv

        with open(full_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = []
            for i, row in enumerate(reader):
                if i >= limit:
                    break
                rows.append(row)
        total = _count_csv_rows(full_path, quick=True)
        return {"data": rows, "total": total, "approximate": total is None}

    if suffix in (".xlsx", ".xls"):
        import pandas as pd

        df = pd.read_excel(full_path, nrows=limit)
        df_count = pd.read_excel(full_path, usecols=[0])
        rows = df.where(pd.notnull(df), None).to_dict(orient="records")
        return {"data": rows, "total": len(df_count), "columns": list(df.columns)}

    if suffix == ".jsonl":
        records = []
        total = 0
        with open(full_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                if len(records) < limit:
                    records.append(json.loads(line))
        return {"data": records, "total": total}

    # 文本/图片类素材（article.md 等）：直接给原文，不再 500。
    text = full_path.read_text(encoding="utf-8", errors="replace")
    return {
        "data": text[: max(limit, 1) * 4000],
        "total": 1,
        "truncated": len(text) > max(limit, 1) * 4000,
        "raw": True,
    }


@router.get("/files/{file_path:path}")
async def get_file_content(
    file_path: str,
    preview: bool = True,
    limit: int = Query(default=100, ge=1, le=200),
):
    """Get file content or preview"""
    full_path = _resolve_data_file(file_path)

    if not preview:
        return FileResponse(
            path=full_path,
            filename=full_path.name,
            media_type="application/octet-stream",
        )

    try:
        return _preview_payload(full_path, limit)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON file") from exc
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"无法读取文件：{exc}") from exc


@router.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """Download file"""
    full_path = _resolve_data_file(file_path)
    return FileResponse(
        path=full_path,
        filename=full_path.name,
        media_type="application/octet-stream",
    )


@router.get("/stats")
async def get_data_stats():
    """Get data statistics（只统计白名单内可浏览的文件）"""
    stats = {
        "total_files": 0,
        "total_size": 0,
        "by_platform": {},
        "by_type": {},
    }
    if not DATA_DIR.exists():
        return stats

    for file_path, rel_path in _iter_browsable_files():
        try:
            stat = file_path.stat()
        except OSError:
            continue
        stats["total_files"] += 1
        stats["total_size"] += stat.st_size

        file_type = file_path.suffix[1:].lower()
        stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1

        for platform in ("xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"):
            if platform in rel_path.lower():
                stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + 1
                break

    return stats
