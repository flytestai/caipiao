from __future__ import annotations

from datetime import datetime

from app.models import SyncResult
from app.services.official_source import fetch_history_page
from app.services.repository import get_sync_status, set_meta, upsert_draws


def sync_official_history(*, full_refresh: bool = False) -> SyncResult:
    first_page_draws, pages = fetch_history_page(page_no=1)
    all_draws = list(first_page_draws)
    fetched_pages = 1

    if full_refresh:
        for page_no in range(2, pages + 1):
            page_draws, _ = fetch_history_page(page_no=page_no)
            all_draws.extend(page_draws)
        fetched_pages = pages
    else:
        for page_no in range(2, min(pages, 3) + 1):
            page_draws, _ = fetch_history_page(page_no=page_no)
            all_draws.extend(page_draws)
        fetched_pages = min(pages, 3)

    inserted, updated = upsert_draws(all_draws)
    synced_at = datetime.now().astimezone()
    set_meta("last_synced_at", synced_at.isoformat())

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
