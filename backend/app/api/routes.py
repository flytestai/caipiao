from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from app.models import (
    AIModelListRequest,
    AIModelListResponse,
    AnalyticsResponse,
    BacktestJobListResponse,
    BacktestJobResponse,
    BacktestRequest,
    BacktestResponse,
    DivinationRequest,
    DivinationResponse,
    FullHistoryCacheRebuildJob,
    FullHistoryCacheStatus,
    LottoDraw,
    ManualDrawResult,
    ManualDrawResultUpsertRequest,
    SavedScheme,
    SavedSchemeBatchCreateRequest,
    SavedSchemeCreateRequest,
    SavedSchemeListResponse,
    SavedSchemeManualCreateRequest,
    SyncResult,
    SyncStatus,
)
from app.services.ai_gateway import fetch_model_list
from app.services.analytics import build_analytics
from app.services.backtest_jobs import cancel_backtest_job, create_backtest_job, get_backtest_job, list_backtest_jobs
from app.services.backtest_service import (
    FullHistoryCacheStaleError,
    create_full_history_cache_rebuild_job,
    get_full_history_cache_rebuild_job,
    get_full_history_cache_status,
    run_backtest,
    run_divination_with_backtest_logic,
)
from app.services.meihua import AIConfigurationError, AIGenerationError
from app.services.repository import (
    delete_saved_scheme,
    delete_saved_schemes_by_issue,
    delete_manual_draw_result,
    get_history,
    get_sync_status,
    list_saved_schemes,
    save_manual_scheme,
    save_scheme,
    save_schemes,
    upsert_manual_draw_result,
)
from app.services.sync_service import sync_official_history

router = APIRouter()


@router.get("/history", response_model=list[LottoDraw], summary="Draw history")
def history(limit: int = Query(5000, ge=1, le=5000)) -> list[LottoDraw]:
    return get_history(limit=limit)


@router.get("/analytics", response_model=AnalyticsResponse, summary="Analytics")
def analytics(limit: int = Query(5000, ge=10, le=5000)) -> AnalyticsResponse:
    return build_analytics(get_history(limit=limit))


@router.post("/divination", response_model=DivinationResponse, summary="Mei Hua divination with dynamic scheme count")
def divination(payload: DivinationRequest) -> DivinationResponse:
    try:
        return run_divination_with_backtest_logic(
            issue=payload.issue,
            timestamp=payload.timestamp,
            scheme_count=payload.scheme_count,
            strategy_mode=payload.strategy_mode,
            ai_config=payload.ai_config,
        )
    except AIConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except FullHistoryCacheStaleError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "cache_status": exc.status.model_dump(mode="json"),
            },
        ) from exc


@router.post("/ai/models", response_model=AIModelListResponse, summary="Fetch available AI models")
def ai_models(payload: AIModelListRequest) -> AIModelListResponse:
    try:
        return AIModelListResponse(models=fetch_model_list(payload.base_url, payload.api_key))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Fetch model list failed: {exc}") from exc


@router.get("/sync/status", response_model=SyncStatus, summary="Sync status")
def sync_status() -> SyncStatus:
    return get_sync_status()


@router.post("/sync/run", response_model=SyncResult, summary="Run sync now")
def sync_run(full_refresh: bool = False) -> SyncResult:
    return sync_official_history(full_refresh=full_refresh)


@router.get("/full-history-cache/status", response_model=FullHistoryCacheStatus, summary="Full-history cache status")
def full_history_cache_status(
    scheme_count: int = Query(3, ge=1, le=50),
    ticket_mode: str = Query("basic", pattern="^(basic|additional)$"),
) -> FullHistoryCacheStatus:
    return get_full_history_cache_status(scheme_count=scheme_count, ticket_mode=ticket_mode)


@router.post("/full-history-cache/rebuild", response_model=FullHistoryCacheRebuildJob, summary="Rebuild full-history cache")
def full_history_cache_rebuild(
    scheme_count: int = Query(3, ge=1, le=50),
    ticket_mode: str = Query("basic", pattern="^(basic|additional)$"),
    force: bool = Query(False),
) -> FullHistoryCacheRebuildJob:
    return create_full_history_cache_rebuild_job(scheme_count=scheme_count, ticket_mode=ticket_mode, force=force)


@router.get("/full-history-cache/jobs/{job_id}", response_model=FullHistoryCacheRebuildJob, summary="Get full-history cache rebuild job")
def full_history_cache_job_get(job_id: str) -> FullHistoryCacheRebuildJob:
    job = get_full_history_cache_rebuild_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Full-history cache rebuild job not found")
    return job


@router.get("/saved-schemes", response_model=SavedSchemeListResponse, summary="Saved schemes with evaluation stats")
def saved_schemes(limit: int = Query(100, ge=1, le=500)) -> SavedSchemeListResponse:
    return list_saved_schemes(limit=limit)


@router.post("/saved-schemes", response_model=SavedScheme, summary="Save one generated scheme")
def saved_scheme_create(payload: SavedSchemeCreateRequest) -> SavedScheme:
    return save_scheme(payload)


@router.post("/saved-schemes/batch", response_model=list[SavedScheme], summary="Save generated schemes in one batch")
def saved_scheme_batch_create(payload: SavedSchemeBatchCreateRequest) -> list[SavedScheme]:
    return save_schemes(payload.items)


@router.post(
    "/saved-schemes/manual",
    response_model=SavedScheme,
    summary="Save one manually purchased ticket (auto-evaluates after draw)",
)
def saved_scheme_manual_create(payload: SavedSchemeManualCreateRequest) -> SavedScheme:
    try:
        return save_manual_scheme(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/saved-schemes/issues/{issue}/manual-result",
    response_model=ManualDrawResult,
    summary="Upsert manual winning numbers for one issue",
)
def saved_scheme_manual_result_upsert(issue: str, payload: ManualDrawResultUpsertRequest) -> ManualDrawResult:
    try:
        return upsert_manual_draw_result(issue, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/saved-schemes/issues/{issue}/manual-result",
    status_code=204,
    summary="Delete manual winning numbers override for one issue",
)
def saved_scheme_manual_result_delete(issue: str) -> Response:
    if not delete_manual_draw_result(issue):
        raise HTTPException(status_code=404, detail="Manual draw result not found")
    return Response(status_code=204)


@router.delete("/saved-schemes/{saved_id}", status_code=204, summary="Delete one saved scheme")
def saved_scheme_delete(saved_id: int) -> Response:
    if not delete_saved_scheme(saved_id):
        raise HTTPException(status_code=404, detail="Saved scheme not found")
    return Response(status_code=204)


@router.delete("/saved-schemes/issues/{issue}", summary="Delete all saved schemes for one issue")
def saved_scheme_issue_delete(issue: str) -> dict[str, int]:
    deleted = delete_saved_schemes_by_issue(issue)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Saved schemes not found")
    return {"deleted": deleted}


@router.post("/backtest", response_model=BacktestResponse, summary="Run historical backtest")
def backtest(payload: BacktestRequest) -> BacktestResponse:
    try:
        return run_backtest(
            recent_issues=payload.recent_issues,
            scheme_count=payload.scheme_count,
            strategy_mode=payload.strategy_mode,
            ticket_mode=payload.ticket_mode,
            ai_replay_mode=payload.ai_replay_mode,
            compare_modes=payload.compare_modes,
            ai_config=payload.ai_config,
            tuning_profile_override=payload.tuning_profile_override,
            multiple=payload.multiple,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/backtest/jobs", response_model=BacktestJobResponse, summary="Create historical backtest job")
def backtest_job_create(payload: BacktestRequest) -> BacktestJobResponse:
    try:
        return create_backtest_job(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/backtest/jobs", response_model=BacktestJobListResponse, summary="List historical backtest jobs")
def backtest_job_list(limit: int = Query(20, ge=1, le=100)) -> BacktestJobListResponse:
    return list_backtest_jobs(limit=limit)


@router.get("/backtest/jobs/{job_id}", response_model=BacktestJobResponse, summary="Get historical backtest job")
def backtest_job_get(job_id: str) -> BacktestJobResponse:
    job = get_backtest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Backtest job not found")
    return job


@router.post("/backtest/jobs/{job_id}/cancel", response_model=BacktestJobResponse, summary="Cancel historical backtest job")
def backtest_job_cancel(job_id: str) -> BacktestJobResponse:
    job = cancel_backtest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Backtest job not found")
    return job
