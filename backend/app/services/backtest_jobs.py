from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
import logging
from threading import Lock
from uuid import uuid4

from app.models import BacktestJobListResponse, BacktestJobResponse, BacktestRequest, BacktestResponse
from app.services.backtest_service import run_backtest

logger = logging.getLogger(__name__)

_MAX_JOBS = 24
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="backtest-job")
_lock = Lock()


@dataclass
class _BacktestJobState:
    job_id: str
    payload: BacktestRequest
    status: str = "queued"
    stage: str = "queued"
    message: str | None = None
    progress: float = 0.0
    processed_issues: int = 0
    total_issues: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: BacktestResponse | None = None
    cancel_requested: bool = False


_jobs: dict[str, _BacktestJobState] = {}


class BacktestJobCanceled(Exception):
    pass


def _trim_jobs() -> None:
    if len(_jobs) <= _MAX_JOBS:
        return
    removable = sorted(_jobs.values(), key=lambda item: item.created_at)
    while len(removable) > 0 and len(_jobs) > _MAX_JOBS:
        item = removable.pop(0)
        if item.status in {"completed", "failed", "canceled"}:
            _jobs.pop(item.job_id, None)


def _serialize_job(job: _BacktestJobState, *, include_result: bool = True) -> BacktestJobResponse:
    return BacktestJobResponse(
        job_id=job.job_id,
        status=job.status,  # type: ignore[arg-type]
        stage=job.stage,
        message=job.message,
        progress=job.progress,
        processed_issues=job.processed_issues,
        total_issues=job.total_issues,
        scheme_count=job.payload.scheme_count,
        strategy_mode=job.payload.strategy_mode,
        ticket_mode=job.payload.ticket_mode,
        ai_replay_mode=job.payload.ai_replay_mode,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        result=job.result if include_result and job.status == "completed" else None,
    )


def _update_progress(
    job_id: str,
    *,
    stage: str,
    progress: float,
    message: str | None = None,
    processed_issues: int | None = None,
    total_issues: int | None = None,
) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        if job.cancel_requested and job.status in {"queued", "running", "canceling"}:
            job.status = "canceling"
            job.stage = "canceling"
            job.message = "正在取消回测任务"
            raise BacktestJobCanceled("Backtest job canceled")
        job.stage = stage
        job.progress = max(0.0, min(1.0, progress))
        job.message = message
        if processed_issues is not None:
            job.processed_issues = processed_issues
        if total_issues is not None:
            job.total_issues = total_issues


def _cancel_check(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        if job.cancel_requested:
            job.status = "canceling"
            job.stage = "canceling"
            job.message = "正在取消回测任务"
            raise BacktestJobCanceled("Backtest job canceled")


def _run_job(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.stage = "preparing"
        job.started_at = datetime.utcnow()
        job.message = "正在准备回测任务"

    try:
        result = run_backtest(
            recent_issues=job.payload.recent_issues,
            scheme_count=job.payload.scheme_count,
            strategy_mode=job.payload.strategy_mode,
            ticket_mode=job.payload.ticket_mode,
            ai_replay_mode=job.payload.ai_replay_mode,
            compare_modes=job.payload.compare_modes,
            ai_config=job.payload.ai_config,
            tuning_profile_override=job.payload.tuning_profile_override,
            progress_callback=lambda **kwargs: _update_progress(job_id, **kwargs),
            cancel_check=lambda: _cancel_check(job_id),
        )
    except BacktestJobCanceled:
        with _lock:
            canceled_job = _jobs.get(job_id)
            if not canceled_job:
                return
            canceled_job.status = "canceled"
            canceled_job.stage = "canceled"
            canceled_job.message = "回测已取消"
            canceled_job.finished_at = datetime.utcnow()
        return
    except Exception as exc:
        logger.exception("Backtest job failed: %s", job_id)
        with _lock:
            failed_job = _jobs.get(job_id)
            if not failed_job:
                return
            failed_job.status = "failed"
            failed_job.stage = "failed"
            failed_job.error = str(exc)
            failed_job.message = "回测任务失败"
            failed_job.finished_at = datetime.utcnow()
        return

    with _lock:
        completed_job = _jobs.get(job_id)
        if not completed_job:
            return
        completed_job.status = "completed"
        completed_job.stage = "completed"
        completed_job.progress = 1.0
        completed_job.message = "回测完成"
        completed_job.result = result
        completed_job.processed_issues = result.total_issues
        completed_job.total_issues = result.total_issues
        completed_job.finished_at = datetime.utcnow()


def create_backtest_job(payload: BacktestRequest) -> BacktestJobResponse:
    if payload.ai_replay_mode == "external_rerank":
        if not (
            payload.ai_config
            and payload.ai_config.enabled
            and payload.ai_config.base_url
            and payload.ai_config.api_key
            and payload.ai_config.model
        ):
            raise ValueError("历史回测切换到 AI 重排时，需要先启用并完整配置外部 AI。")
    job_id = uuid4().hex
    job = _BacktestJobState(job_id=job_id, payload=payload)
    with _lock:
        _jobs[job_id] = job
        _trim_jobs()
    _executor.submit(_run_job, job_id)
    return _serialize_job(job, include_result=False)


def get_backtest_job(job_id: str) -> BacktestJobResponse | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return _serialize_job(job)


def list_backtest_jobs(limit: int = 20) -> BacktestJobListResponse:
    with _lock:
        items = sorted(_jobs.values(), key=lambda item: item.created_at, reverse=True)[:limit]
        return BacktestJobListResponse(items=[_serialize_job(item) for item in items])


def cancel_backtest_job(job_id: str) -> BacktestJobResponse | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        if job.status in {"completed", "failed", "canceled"}:
            return _serialize_job(job)
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "canceled"
            job.stage = "canceled"
            job.message = "回测已取消"
            job.finished_at = datetime.utcnow()
        else:
            job.status = "canceling"
            job.stage = "canceling"
            job.message = "正在取消回测任务"
        return _serialize_job(job)
