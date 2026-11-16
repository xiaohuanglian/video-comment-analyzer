# -*- coding: utf-8 -*-
"""洞察运行时产物：导出与草稿内容。

从 `api/routers/analysis.py` 拆出（2026-11-11）：原文件 1578 行 / 47 条路由，
导出与内容生成是其中最独立的一块，混在同一个文件里让「改导出要读完整路由表」。

**URL 与响应格式完全不变**，仍挂在 `/api/analysis` 前缀下。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.services.insight.export import (
    build_candidates_csv,
    build_outreach_csv,
    build_report_json,
    build_report_markdown,
    build_results_csv,
)
from api.services.insight.storage import load_config

router = APIRouter()




def _attachment_headers(filename: str, fallback: str) -> Dict[str, str]:
    from urllib.parse import quote

    encoded = quote(filename)
    return {"Content-Disposition": f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'}


@router.get("/runs/{run_id}/export/results.csv")
async def export_run_results_csv(run_id: str) -> Response:
    try:
        load_config(run_id)
        content = build_results_csv(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"{run_id}_results.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=_attachment_headers(filename, "analysis_results.csv"),
    )


@router.get("/runs/{run_id}/export/report.md")
async def export_run_report_md(run_id: str) -> Response:
    try:
        content = build_report_markdown(run_id).encode("utf-8")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    filename = f"{run_id}_report.md"
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers=_attachment_headers(filename, "analysis_report.md"),
    )


@router.get("/runs/{run_id}/export/report.json")
async def export_run_report_json(run_id: str) -> Dict[str, Any]:
    try:
        return build_report_json(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.get("/runs/{run_id}/export/candidates.csv")
async def export_run_candidates_csv(run_id: str) -> Response:
    try:
        load_config(run_id)
        content = build_candidates_csv(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"{run_id}_candidates.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=_attachment_headers(filename, "candidates.csv"),
    )


@router.get("/runs/{run_id}/export/outreach.csv")
async def export_run_outreach_csv(run_id: str) -> Response:
    try:
        load_config(run_id)
        content = build_outreach_csv(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"{run_id}_outreach.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=_attachment_headers(filename, "outreach.csv"),
    )



# ---- 内容草稿 -------------------------------------------------------------
