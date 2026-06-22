from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.db import ensure_database
from app.services.sync_service import sync_official_history

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _scheduled_recent_sync() -> None:
    try:
        result = sync_official_history(full_refresh=False)
        logger.info("Scheduled sync complete: %s", result.model_dump())
    except Exception:
        logger.exception("Scheduled sync failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_database()
    try:
        result = sync_official_history(full_refresh=False)
        logger.info("Initial full sync complete: %s", result.model_dump())
    except Exception:
        logger.exception("Initial sync failed")

    scheduler.add_job(
        _scheduled_recent_sync,
        CronTrigger(minute=5),
        id="lotto_recent_sync",
        replace_existing=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Super Lotto Analyzer",
    version="0.2.0",
    description="Super Lotto API with full-history sync, analytics, and Mei Hua recommendation flow",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
