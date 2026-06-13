from __future__ import annotations

from datetime import datetime

from app.models import SyncResult
from app.services.official_source import fetch_history_page
from app.services.repository import get_sync_status, set_meta, upsert_draws


def _queue_incremental_full_history_cache_updates() -> None:
    # 常用推演组数优先自动补最新增量，避免每次刷新页面都要求手动更新缓存。
    from app.services.backtest_service import create_full_history_cache_rebuild_job

    for scheme_count in (3, 5, 8, 10):
        try:
            create_full_history_cache_rebuild_job(scheme_count=scheme_count, ticket_mode="basic", force=True)
        except Exception:
            # 缓存补齐是增强体验的后台任务，不应阻断开奖同步主流程。
            pass


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
