# -*- coding: utf-8 -*-
"""FastAPI routes for comment insight analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.services.insight.analyzer import build_summary, run_analysis_batch
from api.services.insight.export import (
    auto_export_candidates_outreach,
    build_candidates_csv,
    build_outreach_csv,
    build_report_json,
    build_report_markdown,
    build_results_csv,
)
from api.services.insight.ingestion import ingest_files, list_comment_sources, list_comment_sources_grouped, preview_file
from api.services.insight.llm_analyzer import estimate_cost
from api.services.insight.pricing import DEFAULT_BASE_URL, DEFAULT_MODEL, normalize_model_settings, resolve_pricing
from api.services.insight.run_naming import build_run_id
from api.services.insight.sampling import DEFAULT_SAMPLE_SEED, stratified_sample
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import (
    create_run,
    ensure_run_config,
    load_candidates,
    load_config,
    load_document_warnings,
    load_evidence_cards,
    load_outreach,
    load_progress,
    load_research_analysis,
    load_results,
    load_source_records,
    load_summary,
    load_themes,
    load_trial_sample,
    list_runs,
    reset_failed_records,
    results_for_candidates,
    save_candidates,
    save_config,
    save_outreach,
    save_progress,
    save_trial_sample,
    sync_progress_from_results,
)
from api.services.insight.run_locations import run_exists_in_csv_dir
from api.services.insight.task_runner import is_running, request_cancel, start_background
from api.services.insight.research_matching import parse_research_targets
from api.services.insight.candidates import build_candidates, merge_candidate_updates
from api.services.insight.outreach import generate_outreach_drafts, merge_outreach_update
from api.services.insight.outreach_prompts import DEFAULT_BASE_TEMPLATE
from api.services.insight.query_filters import paginate_candidates, paginate_results
from api.services.insight.theme_clustering import run_theme_clustering
from api.services.insight.trial_report import build_trial_report

router = APIRouter(prefix="/analysis", tags=["analysis"])

AVG_SECONDS_PER_COMMENT = 4.0


def _attachment_headers(filename: str, fallback: str) -> Dict[str, str]:
    encoded = quote(filename)
    return {"Content-Disposition": f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'}


class ModelSettings(BaseModel):
    model_name: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    budget_limit: float = Field(default=0.0, ge=0, description="0 means no limit")


class CreateRunRequest(BaseModel):
    name: str = "评论洞察任务"
    file_paths: List[str] = Field(min_length=1)
    field_mapping: Optional[FieldMapping] = None
    fixed_creator_type: Optional[str] = None
    fixed_platform: Optional[str] = None
    analysis_limit: int = Field(default=100, ge=0, description="0 = analyze all pending per batch")
    use_mock: bool = False
    research_targets: str = ""
    model: ModelSettings = Field(default_factory=ModelSettings)
    # Product default is evidence_items_v1; legacy_per_record only for advanced fallback
    analysis_version: str = "evidence_items_v1"


class AnalyzeRequest(BaseModel):
    limit: Optional[int] = None
    record_ids: Optional[List[str]] = None
    retry_failed_only: bool = False
    use_mock: Optional[bool] = None
    api_key: Optional[str] = None
    background: bool = True
    force_reanalyze: bool = False


class ThemeClusterRequest(BaseModel):
    api_key: Optional[str] = None
    use_mock: Optional[bool] = None


class OutreachGenerateRequest(BaseModel):
    user_keys: List[str] = Field(min_length=1)
    base_template: str = ""
    api_key: Optional[str] = None
    use_mock: Optional[bool] = None
    force: bool = False  # True = regenerate even if draft exists


class CandidateUpdateRequest(BaseModel):
    contact_status: Optional[str] = None
    product_manager_note: Optional[str] = None


class OutreachUpdateRequest(BaseModel):
    edited_content: Optional[str] = None
    contact_status: Optional[str] = None
    product_manager_note: Optional[str] = None


class UpdateRunConfigRequest(BaseModel):
    research_targets: str = ""


class TrialSampleRequest(BaseModel):
    sample_size: int = Field(default=100, ge=1)
    seed: int = Field(default=DEFAULT_SAMPLE_SEED, ge=0)


class EstimateRequest(BaseModel):
    sample_size: int = Field(default=1, ge=1, description="Number of comments to estimate")
    avg_prompt_tokens: int = Field(default=900, ge=100)
    avg_completion_tokens: int = Field(default=350, ge=50)
    model: ModelSettings = Field(default_factory=ModelSettings)


class VerifyModelRequest(BaseModel):
    api_key: str = Field(min_length=1)
    model: ModelSettings = Field(default_factory=ModelSettings)


@router.get("/sources")
async def get_sources(grouped: bool = True) -> Dict[str, Any]:
    if grouped:
        return list_comment_sources_grouped()
    return {"files": list_comment_sources()}


@router.get("/sources/preview")
async def get_source_preview(path: str, limit: int = 20) -> Dict[str, Any]:
    try:
        return preview_file(path, limit=limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs")
async def get_runs() -> Dict[str, Any]:
    return {"runs": list_runs()}


@router.get("/pricing")
async def get_pricing(base_url: str = DEFAULT_BASE_URL, model_name: str = DEFAULT_MODEL) -> Dict[str, Any]:
    return normalize_model_settings(base_url=base_url, model_name=model_name)


@router.post("/estimate")
async def post_estimate(body: EstimateRequest) -> Dict[str, Any]:
    pricing = normalize_model_settings(base_url=body.model.base_url, model_name=body.model.model_name)
    prompt_tokens = body.sample_size * body.avg_prompt_tokens
    completion_tokens = body.sample_size * body.avg_completion_tokens
    cost = estimate_cost(
        prompt_tokens,
        completion_tokens,
        input_price=float(pricing["input_price"]),
        output_price=float(pricing["output_price"]),
    )
    return {
        "sample_size": body.sample_size,
        "estimated_prompt_tokens": prompt_tokens,
        "estimated_completion_tokens": completion_tokens,
        "estimated_cost": cost,
        "estimated_duration_seconds": int(body.sample_size * AVG_SECONDS_PER_COMMENT),
        "estimated_duration_label": _format_duration(int(body.sample_size * AVG_SECONDS_PER_COMMENT)),
        "currency": pricing["currency"],
        "provider_label": pricing["provider_label"],
        "input_price": pricing["input_price"],
        "output_price": pricing["output_price"],
        "budget_limit": body.model.budget_limit,
        "within_budget": body.model.budget_limit <= 0 or cost <= body.model.budget_limit,
    }


@router.post("/verify-model")
async def post_verify_model(body: VerifyModelRequest) -> Dict[str, Any]:
    """One-shot LLM connectivity check; api_key is not stored."""
    from api.services.insight.llm_analyzer import analyze_record_llm
    from api.services.insight.schemas import RunConfig, SourceRecord

    pricing = normalize_model_settings(base_url=body.model.base_url, model_name=body.model.model_name)
    config = RunConfig(
        run_id="verify",
        name="verify",
        file_paths=[],
        field_mapping={"comment_text": "content"},
        model_name=str(pricing["model_name"]),
        base_url=str(pricing["base_url"]),
        input_price=float(pricing["input_price"]),
        output_price=float(pricing["output_price"]),
        currency=str(pricing["currency"]),
    )
    record = SourceRecord(
        internal_record_id="verify:1",
        source_file="verify",
        source_row_number=1,
        comment_text="这个动作一周练几次？",
        creator_type="普通健身类",
        platform="bilibili",
    )
    try:
        response = analyze_record_llm(record, config, body.api_key.strip())
        analysis = response.analysis
        cost = estimate_cost(
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            input_price=config.input_price,
            output_price=config.output_price,
            prompt_cache_hit_tokens=response.usage.prompt_cache_hit_tokens,
            input_price_cache_hit=float(pricing["input_price_cache_hit"]),
        )
        return {
            "ok": True,
            "provider_label": pricing["provider_label"],
            "model_name": config.model_name,
            "model_display": pricing.get("model_display"),
            "primary_intent": analysis.primary_intent.value if hasattr(analysis.primary_intent, "value") else analysis.primary_intent,
            "single_video_relation": analysis.single_video_relation.value if hasattr(analysis.single_video_relation, "value") else analysis.single_video_relation,
            "confidence": analysis.confidence,
            "prompt_tokens": response.usage.prompt_tokens,
            "prompt_cache_hit_tokens": response.usage.prompt_cache_hit_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "estimated_cost": cost,
            "currency": config.currency,
            "message": "API 连接正常，结构化输出校验通过",
        }
    except Exception as exc:
        detail = str(exc)
        if "401" in detail or "authentication" in detail.lower() or "api key" in detail.lower():
            raise HTTPException(status_code=401, detail="API Key 无效或未授权，请检查 DeepSeek 控制台") from exc
        raise HTTPException(status_code=400, detail=detail[:300]) from exc


@router.post("/runs")
async def post_create_run(body: CreateRunRequest) -> Dict[str, Any]:
    try:
        records = ingest_files(
            body.file_paths,
            field_mapping=body.field_mapping,
            fixed_creator_type=body.fixed_creator_type,
            fixed_platform=body.fixed_platform,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not records:
        raise HTTPException(status_code=400, detail="所选文件中没有有效评论")
    suggested = preview_file(body.file_paths[0])
    mapping = body.field_mapping or FieldMapping.model_validate(suggested["suggested_mapping"])
    run_id = build_run_id(body.name, exists=lambda candidate: run_exists_in_csv_dir(body.file_paths, candidate))
    pricing = normalize_model_settings(base_url=body.model.base_url, model_name=body.model.model_name)
    version = (body.analysis_version or "evidence_items_v1").strip()
    if version not in {"evidence_items_v1", "legacy_per_record"}:
        raise HTTPException(
            status_code=400,
            detail="analysis_version 仅支持 evidence_items_v1 或 legacy_per_record",
        )
    config = RunConfig(
        run_id=run_id,
        name=body.name,
        file_paths=body.file_paths,
        field_mapping=mapping,
        model_name=str(pricing["model_name"]),
        base_url=str(pricing["base_url"]),
        input_price=float(pricing["input_price"]),
        output_price=float(pricing["output_price"]),
        currency=str(pricing["currency"]),
        budget_limit=body.model.budget_limit,
        analysis_limit=body.analysis_limit,
        use_mock=body.use_mock,
        research_targets=parse_research_targets(body.research_targets),
        created_at=datetime.now(timezone.utc).isoformat(),
        analysis_version=version,
        allow_legacy_fallback=True,
    )
    create_run(config, records)
    return {
        "run_id": run_id,
        "total_records": len(records),
        "analysis_limit": body.analysis_limit,
        "use_mock": body.use_mock,
        "analysis_version": version,
        "pricing": pricing,
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> Dict[str, Any]:
    try:
        config = load_config(run_id)
        progress = sync_progress_from_results(run_id) if is_running(run_id) else load_progress(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    summary = {}
    try:
        from api.services.insight.storage import _read_json, _run_dir

        summary_path = _run_dir(run_id) / "summary.json"
        if summary_path.exists():
            summary = _read_json(summary_path)
    except Exception:
        summary = {}
    config_dump = ensure_run_config(config).model_dump()
    config_dump.pop("api_key", None)
    pricing = resolve_pricing(config_dump.get("base_url", ""), config_dump.get("model_name", ""))
    doc_warnings = load_document_warnings(run_id)
    return {
        "config": config_dump,
        "progress": progress.model_dump(),
        "summary": summary,
        "pricing": pricing,
        "is_running": is_running(run_id),
        "default_outreach_template": DEFAULT_BASE_TEMPLATE,
        "export_paths": summary.get("export_paths") or {},
        "document_warnings": doc_warnings,
    }


def _format_duration(total_seconds: int) -> str:
    if total_seconds <= 0:
        return "少于 1 分钟"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: List[str] = []
    if hours:
        parts.append(f"{hours} 小时")
    if minutes:
        parts.append(f"{minutes} 分钟")
    if not parts and seconds:
        parts.append(f"{seconds} 秒")
    return " ".join(parts) or "少于 1 分钟"


def _run_background_analysis(
    run_id: str,
    *,
    limit: Optional[int],
    record_ids: Optional[List[str]],
    retry_failed_only: bool,
    use_mock: bool,
    api_key: Optional[str],
    cancel_event,
    force_reanalyze: bool = False,
) -> None:
    try:
        id_set = set(record_ids) if record_ids else None
        result = run_analysis_batch(
            run_id,
            limit=limit,
            record_ids=id_set,
            retry_failed_only=retry_failed_only,
            use_mock=use_mock,
            api_key=api_key,
            cancel_event=cancel_event,
            force_reanalyze=force_reanalyze,
        )
        if result.get("completed", 0) > 0:
            build_summary(run_id)
    except Exception as exc:
        progress = load_progress(run_id)
        progress.status = "failed"
        progress.last_error = str(exc)
        save_progress(run_id, progress)


def _start_analyze_job(run_id: str, body: AnalyzeRequest, use_mock: bool) -> Dict[str, Any]:
    if is_running(run_id):
        progress = load_progress(run_id)
        return {
            "run_id": run_id,
            "background": True,
            "already_running": True,
            "status": progress.status,
            "completed": progress.completed,
            "total_records": progress.total_records,
            "eta_seconds": progress.eta_seconds,
        }

    def job(cancel_event) -> None:
        _run_background_analysis(
            run_id,
            limit=body.limit,
            record_ids=body.record_ids,
            retry_failed_only=body.retry_failed_only,
            use_mock=use_mock,
            api_key=body.api_key,
            cancel_event=cancel_event,
            force_reanalyze=body.force_reanalyze,
        )

    if not start_background(run_id, job):
        raise HTTPException(status_code=409, detail="任务正在分析中")
    progress = load_progress(run_id)
    progress.status = "running"
    save_progress(run_id, progress)
    return {
        "run_id": run_id,
        "background": True,
        "status": "running",
        "completed": progress.completed,
        "total_records": progress.total_records,
        "message": "分析已在后台启动，请查看下方进度",
    }


@router.post("/runs/{run_id}/analyze")
async def post_analyze(run_id: str, body: AnalyzeRequest) -> Dict[str, Any]:
    try:
        config = load_config(run_id)
        use_mock = config.use_mock if body.use_mock is None else body.use_mock
        if not use_mock and not (body.api_key or "").strip():
            raise HTTPException(status_code=400, detail="真实 API 分析需要填写 API Key")
        if body.background:
            return _start_analyze_job(run_id, body, use_mock)

        id_set = set(body.record_ids) if body.record_ids else None
        result = run_analysis_batch(
            run_id,
            limit=body.limit,
            record_ids=id_set,
            retry_failed_only=body.retry_failed_only,
            use_mock=use_mock,
            api_key=body.api_key,
            force_reanalyze=body.force_reanalyze,
        )
        if result.get("completed", 0) > 0:
            build_summary(run_id)
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/trial-sample")
async def post_trial_sample(run_id: str, body: TrialSampleRequest) -> Dict[str, Any]:
    try:
        records = load_source_records(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    if not records:
        raise HTTPException(status_code=400, detail="任务中没有可分析评论")
    sample_ids = stratified_sample(records, body.sample_size, seed=body.seed)
    payload = {
        "sample_size": len(sample_ids),
        "seed": body.seed,
        "record_ids": sample_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_trial_sample(run_id, payload)
    return payload


@router.get("/runs/{run_id}/trial-report")
async def get_trial_report(run_id: str) -> Dict[str, Any]:
    try:
        return build_trial_report(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/trial-run")
async def post_trial_run(run_id: str, body: AnalyzeRequest) -> Dict[str, Any]:
    try:
        config = load_config(run_id)
        trial = load_trial_sample(run_id)
        if not trial.get("record_ids"):
            raise HTTPException(status_code=400, detail="请先生成试跑样本")
        use_mock = config.use_mock if body.use_mock is None else body.use_mock
        if not use_mock and not (body.api_key or "").strip():
            raise HTTPException(status_code=400, detail="真实 API 分析需要填写 API Key")
        body.record_ids = trial["record_ids"]
        body.retry_failed_only = False
        if body.background:
            return _start_analyze_job(run_id, body, use_mock)
        result = run_analysis_batch(
            run_id,
            record_ids=set(trial["record_ids"]),
            use_mock=use_mock,
            api_key=body.api_key,
        )
        if result.get("completed", 0) > 0:
            build_summary(run_id)
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@router.post("/runs/{run_id}/retry-failed")
async def post_retry_failed(run_id: str, body: AnalyzeRequest) -> Dict[str, Any]:
    try:
        config = load_config(run_id)
        progress = load_progress(run_id)
        if not progress.failed_record_ids:
            raise HTTPException(status_code=400, detail="当前没有失败项可重试")
        use_mock = config.use_mock if body.use_mock is None else body.use_mock
        if not use_mock and not (body.api_key or "").strip():
            raise HTTPException(status_code=400, detail="真实 API 分析需要填写 API Key")
        body.retry_failed_only = True
        body.record_ids = None
        if body.background:
            return _start_analyze_job(run_id, body, use_mock)
        result = run_analysis_batch(
            run_id,
            retry_failed_only=True,
            use_mock=use_mock,
            api_key=body.api_key,
        )
        if result.get("completed", 0) > 0:
            build_summary(run_id)
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel")
async def post_cancel(run_id: str) -> Dict[str, Any]:
    try:
        progress = load_progress(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc

    progress.cancel_requested = True
    if progress.status == "running":
        progress.status = "cancelling"
    save_progress(run_id, progress)

    cancelled_in_memory = request_cancel(run_id)
    if not cancelled_in_memory and progress.status not in {"cancelled", "completed"}:
        progress = sync_progress_from_results(run_id)
        progress.status = "cancelled"
        progress.last_error = "用户已停止分析"
        save_progress(run_id, progress)

    progress = load_progress(run_id)
    return {
        "run_id": run_id,
        "status": progress.status,
        "completed": progress.completed,
        "total_records": progress.total_records,
        "cancelled_in_memory": cancelled_in_memory,
        "message": "已请求停止分析，当前批次处理完一条后会暂停",
    }


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


@router.get("/runs/{run_id}/themes")
async def get_themes(run_id: str) -> Dict[str, Any]:
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return load_themes(run_id).model_dump()


@router.post("/runs/{run_id}/themes/cluster")
async def post_cluster_themes(run_id: str, body: ThemeClusterRequest) -> Dict[str, Any]:
    try:
        config = load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    use_mock = config.use_mock if body.use_mock is None else body.use_mock
    if not use_mock and not (body.api_key or "").strip():
        raise HTTPException(status_code=400, detail="主题归并需要填写 API Key")
    try:
        doc = run_theme_clustering(run_id, api_key=body.api_key, use_mock=use_mock)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Refresh markdown report so themes appear in auto-exported report
    try:
        build_summary(run_id)
    except Exception:
        pass
    return doc.model_dump()


@router.get("/runs/{run_id}/results")
async def get_results(run_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """Full aggregate payload — prefer /results/items + /summary for large runs."""
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    results = load_results(run_id, limit=limit)
    if results:
        summary = load_summary(run_id) or build_summary(run_id)
    else:
        summary = {}
    themes = load_themes(run_id).model_dump()
    candidates = load_candidates(run_id).model_dump()
    outreach = load_outreach(run_id).model_dump()
    return {
        "results": results,
        "summary": summary,
        "themes": themes,
        "candidates": candidates,
        "outreach": outreach,
        "default_outreach_template": DEFAULT_BASE_TEMPLATE,
        "document_warnings": load_document_warnings(run_id),
    }


@router.patch("/runs/{run_id}/config")
async def patch_run_config(run_id: str, body: UpdateRunConfigRequest) -> Dict[str, Any]:
    try:
        config = load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    config.research_targets = parse_research_targets(body.research_targets)
    save_config(run_id, config)
    return config.model_dump()


@router.get("/runs/{run_id}/results/items")
async def get_result_items(
    run_id: str,
    page: int = 1,
    page_size: int = 100,
    keyword: str = "",
    primary_intent: str = "",
    intent_valid: bool = False,
    signal: str = "",
    single_video_relation: str = "",
    product_fit: str = "",
    hypothesis_id: str = "",
    hypothesis_relation: str = "",
    has_new_signal: Optional[bool] = None,
    record_ids: str = "",
) -> Dict[str, Any]:
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    rows = load_results(run_id)
    id_list = [item.strip() for item in record_ids.split(",") if item.strip()] if record_ids else None
    return paginate_results(
        rows,
        page=page,
        page_size=page_size,
        keyword=keyword.strip(),
        primary_intent=primary_intent,
        intent_valid=intent_valid,
        signal=signal,
        single_video_relation=single_video_relation,
        product_fit=product_fit,
        hypothesis_id=hypothesis_id,
        hypothesis_relation=hypothesis_relation,
        has_new_signal=has_new_signal,
        record_ids=id_list,
    )


@router.get("/runs/{run_id}/candidates/items")
async def get_candidate_items(
    run_id: str,
    page: int = 1,
    page_size: int = 50,
    priority: str = "",
    contactability: str = "",
    platform: str = "",
    product_fit: str = "",
    contact_status: str = "",
    research_matched: str = "",
) -> Dict[str, Any]:
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    doc = load_candidates(run_id)
    return paginate_candidates(
        doc.candidates,
        page=page,
        page_size=page_size,
        priority=priority,
        contactability=contactability,
        platform=platform,
        product_fit=product_fit,
        contact_status=contact_status,
        research_matched=research_matched,
    )


@router.post("/runs/{run_id}/candidates/build")
async def post_build_candidates(run_id: str) -> Dict[str, Any]:
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    results = results_for_candidates(run_id)
    if not results:
        raise HTTPException(status_code=400, detail="尚无分析结果")
    config = load_config(run_id)
    doc = build_candidates(results, research_targets=config.research_targets)
    save_candidates(run_id, doc)
    summary = build_summary(run_id)
    try:
        export_paths = auto_export_candidates_outreach(run_id)
    except OSError:
        export_paths = {}
    payload = doc.model_dump()
    payload["export_paths"] = {**(summary.get("export_paths") or {}), **export_paths}
    return payload


@router.get("/runs/{run_id}/candidates")
async def get_candidates(run_id: str) -> Dict[str, Any]:
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return load_candidates(run_id).model_dump()


@router.patch("/runs/{run_id}/candidates/{user_key}")
async def patch_candidate(run_id: str, user_key: str, body: CandidateUpdateRequest) -> Dict[str, Any]:
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    doc = load_candidates(run_id)
    updated = merge_candidate_updates(
        doc,
        user_key=user_key,
        contact_status=body.contact_status,
        product_manager_note=body.product_manager_note,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="候选用户不存在")
    save_candidates(run_id, doc)
    return updated.model_dump()


@router.post("/runs/{run_id}/outreach/generate")
async def post_generate_outreach(run_id: str, body: OutreachGenerateRequest) -> Dict[str, Any]:
    try:
        config = load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    candidates_doc = load_candidates(run_id)
    if not candidates_doc.candidates:
        raise HTTPException(status_code=400, detail="请先生成候选用户列表")
    use_mock = config.use_mock if body.use_mock is None else body.use_mock
    if not use_mock and not (body.api_key or "").strip():
        raise HTTPException(status_code=400, detail="生成私信草稿需要 API Key")
    try:
        doc = generate_outreach_drafts(
            candidates_doc.candidates,
            ensure_run_config(config),
            user_keys=body.user_keys,
            base_template=body.base_template or DEFAULT_BASE_TEMPLATE,
            api_key=body.api_key,
            use_mock=use_mock,
            existing=load_outreach(run_id),
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_outreach(run_id, doc)
    for key in body.user_keys:
        merge_candidate_updates(candidates_doc, user_key=key, contact_status="preparing")
    save_candidates(run_id, candidates_doc)
    try:
        export_paths = auto_export_candidates_outreach(run_id)
    except OSError:
        export_paths = {}
    payload = doc.model_dump()
    payload["export_paths"] = export_paths
    return payload


@router.get("/runs/{run_id}/outreach")
async def get_outreach(run_id: str) -> Dict[str, Any]:
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return load_outreach(run_id).model_dump()


@router.patch("/runs/{run_id}/outreach/{user_key}")
async def patch_outreach(run_id: str, user_key: str, body: OutreachUpdateRequest) -> Dict[str, Any]:
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    doc = load_outreach(run_id)
    updated = merge_outreach_update(
        doc,
        user_key,
        edited_content=body.edited_content,
        contact_status=body.contact_status,
        product_manager_note=body.product_manager_note,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="私信记录不存在")
    save_outreach(run_id, doc)
    if body.contact_status:
        candidates_doc = load_candidates(run_id)
        merge_candidate_updates(candidates_doc, user_key=user_key, contact_status=body.contact_status)
        save_candidates(run_id, candidates_doc)
    return updated.model_dump()


@router.get("/runs/{run_id}/evidence/items")
async def get_evidence_items(
    run_id: str,
    page: int = 1,
    page_size: int = 50,
    keyword: str = "",
    record_status: str = "",
    primary_expression: str = "",
    evidence_type: str = "",
) -> Dict[str, Any]:
    """Paginated evidence_items_v1 cards for second-column UI."""
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    rows = load_evidence_cards(run_id)
    keyword_l = (keyword or "").strip().lower()
    status_f = (record_status or "").strip()
    expr_f = (primary_expression or "").strip()
    type_f = (evidence_type or "").strip()

    filtered: List[Dict[str, Any]] = []
    for row in rows:
        card = row.get("card") or {}
        source = row.get("source") or {}
        if status_f and (card.get("record_status") or "") != status_f:
            continue
        if expr_f and (card.get("primary_expression") or "") != expr_f:
            continue
        if type_f:
            items = card.get("evidence_items") or []
            if not any((it or {}).get("type") == type_f for it in items if isinstance(it, dict)):
                continue
        if keyword_l:
            blob = " ".join(
                [
                    str(source.get("comment_text") or ""),
                    str(source.get("username") or ""),
                    str(card.get("record_id") or ""),
                ]
            ).lower()
            if keyword_l not in blob:
                continue
        filtered.append(row)

    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 50)))
    total = len(filtered)
    start = (page - 1) * page_size
    items = filtered[start : start + page_size]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size) if total else 1,
        "analysis_version": "evidence_items_v1",
    }


@router.get("/runs/{run_id}/research-report")
async def get_research_report(run_id: str) -> Dict[str, Any]:
    """Readable research markdown + structured analysis for evidence path."""
    try:
        load_config(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    from api.services.insight.storage import load_research_report

    markdown = load_research_report(run_id)
    research = load_research_analysis(run_id)
    return {
        "run_id": run_id,
        "markdown": markdown,
        "research": research,
        "has_report": bool(markdown or research),
    }
