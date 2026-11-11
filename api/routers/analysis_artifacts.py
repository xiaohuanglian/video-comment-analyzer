# -*- coding: utf-8 -*-
"""洞察运行时产物：导出与草稿内容。

从 `api/routers/analysis.py` 拆出（2026-11-11）：原文件 1578 行 / 47 条路由，
导出与内容生成是其中最独立的一块，混在同一个文件里让「改导出要读完整路由表」。

**URL 与响应格式完全不变**，仍挂在 `/api/analysis` 前缀下。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.services.insight.export import (
    build_candidates_csv,
    build_outreach_csv,
    build_report_json,
    build_report_markdown,
    build_results_csv,
)
from api.services.insight.storage import load_config, load_content_plan

router = APIRouter()


class ContentPlanRequest(BaseModel):
    api_key: Optional[str] = None
    use_mock: Optional[bool] = None
    max_topics: int = Field(default=12, ge=1, le=50)
    draft_topics: int = Field(default=5, ge=0, le=20)
    with_hot: bool = Field(default=False, description="附加外部热点信号")
    hot_boost: bool = Field(default=False, description="按「需求×热度」重排（需 with_hot）")
    with_quality: bool = Field(default=True, description="跑发布前质检（纯代码，零成本）")


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

@router.post("/runs/{run_id}/content/generate")
async def post_generate_content(run_id: str, body: ContentPlanRequest) -> Dict[str, Any]:
    """Build ranked content topics from insights and optionally AI-draft them."""
    from api.services.insight.content_plan import build_content_plan, content_plan_markdown
    from api.services.insight.storage import _run_dir, save_content_plan

    try:
        config = load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    use_mock = config.use_mock if body.use_mock is None else body.use_mock
    doc = build_content_plan(
        run_id,
        use_mock=use_mock,
        api_key=body.api_key or "",
        max_topics=body.max_topics,
        draft_topics=body.draft_topics,
        with_hot=body.with_hot,
        hot_boost=body.hot_boost,
        with_quality=body.with_quality,
    )
    payload = doc.model_dump()
    save_content_plan(run_id, payload)
    try:
        (_run_dir(run_id) / "content_plan.md").write_text(
            content_plan_markdown(doc), encoding="utf-8"
        )
    except OSError:
        pass
    return payload


@router.get("/runs/{run_id}/content")
async def get_content_plan(run_id: str) -> Dict[str, Any]:

    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return load_content_plan(run_id)


@router.get("/runs/{run_id}/export/content.md")
async def export_content_markdown(run_id: str) -> Response:
    from api.services.insight.content_plan import ContentPlanDocument, content_plan_markdown

    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    payload = load_content_plan(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="尚未生成内容选题")
    doc = ContentPlanDocument.model_validate(payload)
    markdown = content_plan_markdown(doc)
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers=_attachment_headers(f"{run_id}_内容选题.md", "content_plan.md"),
    )
