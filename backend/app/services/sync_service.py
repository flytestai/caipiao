from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from app.models import SyncResult
from app.services.official_source import fetch_history_page, fetch_history_pages
from app.services.repository import get_sync_status, set_meta, upsert_draws

FULL_HISTORY_CACHE_QUEUE_MAX_WORKERS = 4


def _queue_incremental_full_history_cache_updates() -> None:
    from app.services.backtest_service import create_full_history_cache_rebuild_job

    scheme_counts = (3, 5, 8, 10)
    max_workers = min(FULL_HISTORY_CACHE_QUEUE_MAX_WORKERS, len(scheme_counts))
    if max_workers <= 1:
        for scheme_count in scheme_counts:
            try:
                create_full_history_cache_rebuild_job(scheme_count=scheme_count, ticket_mode="basic", force=True)
            except Exception:
                pass
        return

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cache-queue") as executor:
        futures = [
            executor.submit(
                create_full_history_cache_rebuild_job,
                scheme_count=scheme_count,
                ticket_mode="basic",
                force=True,
            )
            for scheme_count in scheme_counts
        ]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass


def sync_official_history(*, full_refresh: bool = False) -> SyncResult:
    first_page_draws, pages = fetch_history_page(page_no=1)
    all_draws = list(first_page_draws)
    fetched_pages = 1

    if full_refresh:
        extra_pages = list(range(2, pages + 1))
        all_draws.extend(fetch_history_pages(extra_pages))
        fetched_pages = pages
    else:
        extra_pages = list(range(2, min(pages, 3) + 1))
        all_draws.extend(fetch_history_pages(extra_pages))
        fetched_pages = min(pages, 3)

    inserted, updated = upsert_draws(all_draws)
    synced_at = datetime.now().astimezone()
    set_meta("last_synced_at", synced_at.isoformat())
    if inserted or updated:
        set_meta("full_history_cache_invalidated_at", synced_at.isoformat())
        _queue_incremental_full_history_cache_updates()

    status = get_sync_status()
    return SyncResult(
        source="official:webapi.sporttery.cn",
        fetched_pages=fetched_pages,
        inserted=inserted,
        updated=updated,
        total_in_db=status.total_draws,
        latest_issue=status.latest_issue,
        synced_at=synced_at,
    )
