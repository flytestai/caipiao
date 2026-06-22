from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from functools import lru_cache
import json
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

from app.db import get_connection
from app.models import (
    BacktestCoverageMetrics,
    BacktestIssueResult,
    BacktestPrizeLevelSummary,
    BacktestResponse,
    DivinationResponse,
    DivinationRun,
    DivinationRunListResponse,
    DivinationRunScheme,
    DivinationRunStats,
    FinalScheme,
    LottoDraw,
    ManualDrawResult,
    ManualDrawResultUpsertRequest,
    PrizeEvaluation,
    PrizeLevelItem,
    PrizeRateItem,
    SavedScheme,
    SavedSchemeCreateRequest,
    SavedSchemeListResponse,
    SavedSchemeModeStats,
    SavedSchemeStats,
    SyncStatus,
)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
DRAW_WEEKDAYS = {0, 2, 5}
DRAW_TIME = time(hour=21, minute=30)
TICKET_COST = 2.0
ADDITIONAL_TICKET_COST = 3.0
PRIZE_LEVEL_RULES = [
    ("\u4e00\u7b49\u5956", 5, 2),
    ("\u4e8c\u7b49\u5956", 5, 1),
    ("\u4e09\u7b49\u5956", 5, 0),
    ("\u4e09\u7b49\u5956", 4, 2),
    ("\u56db\u7b49\u5956", 4, 1),
    ("\u4e94\u7b49\u5956", 4, 0),
    ("\u4e94\u7b49\u5956", 3, 2),
    ("\u516d\u7b49\u5956", 3, 1),
    ("\u516d\u7b49\u5956", 2, 2),
    ("\u4e03\u7b49\u5956", 3, 0),
    ("\u4e03\u7b49\u5956", 2, 1),
    ("\u4e03\u7b49\u5956", 1, 2),
    ("\u4e03\u7b49\u5956", 0, 2),
]
PRIZE_LEVEL_ORDER = [
    "\u4e00\u7b49\u5956",
    "\u4e8c\u7b49\u5956",
    "\u4e09\u7b49\u5956",
    "\u56db\u7b49\u5956",
    "\u4e94\u7b49\u5956",
    "\u516d\u7b49\u5956",
    "\u4e03\u7b49\u5956",
]
FIXED_PRIZE_BY_POOL = {
    False: {
        "\u4e09\u7b49\u5956": 5000.0,
        "\u56db\u7b49\u5956": 300.0,
        "\u4e94\u7b49\u5956": 150.0,
        "\u516d\u7b49\u5956": 15.0,
        "\u4e03\u7b49\u5956": 5.0,
    },
    True: {
        "\u4e09\u7b49\u5956": 6666.0,
        "\u56db\u7b49\u5956": 380.0,
        "\u4e94\u7b49\u5956": 200.0,
        "\u516d\u7b49\u5956": 18.0,
        "\u4e03\u7b49\u5956": 7.0,
    },
}
PROMOTION_RULES = [
    {
        "start_issue": 26050,
        "end_issue": 26064,
        "min_ticket_amount": 18.0,
        "label": "2026 \u5e74 8.8 \u4ebf\u6d3e\u5956",
        "bonus_ratios": {
            "\u4e09\u7b49\u5956": 0.5,
            "\u56db\u7b49\u5956": 0.5,
            "\u4e94\u7b49\u5956": 0.5,
            "\u516d\u7b49\u5956": 0.5,
            "\u4e03\u7b49\u5956": 1.0,
        },
    },
]
DRAW_UPSERT_SELECT_BATCH_SIZE = 500
SAVED_SCHEME_SELECT_COLUMNS = ", ".join(
    [
        "id",
        "target_issue",
        "seed_mode",
        "seed_value",
        "moving_line",
        "ai_engine",
        "label",
        "confidence",
        "strategy",
        "front_numbers",
        "back_numbers",
        "rationale",
        "tuning_profile",
        "issue_confidence",
        "calibrated_confidence",
        "applied_threshold",
        "should_observe",
        "front_confidence",
        "front_gate",
        "back_confidence",
        "back_gate",
        "deep_search_triggered",
        "deep_search_reason",
        "decision_reason",
        "multiple",
        "is_additional",
        "created_at",
        "updated_at",
    ]
)
DIVINATION_RUN_SELECT_COLUMNS = ", ".join(
    [
        "id",
        "target_issue",
        "seed_mode",
        "seed_value",
        "divination_datetime",
        "target_draw_datetime",
        "requested_scheme_count",
        "visible_scheme_count",
        "requested_strategy_mode",
        "effective_strategy_mode",
        "moving_line",
        "ai_engine",
        "ai_enabled",
        "tuning_profile",
        "issue_confidence",
        "calibrated_confidence",
        "applied_threshold",
        "should_observe",
        "front_confidence",
        "front_calibrated_confidence",
        "front_gate",
        "back_confidence",
        "back_calibrated_confidence",
        "back_gate",
        "count_policy",
        "decision_tier",
        "deep_search_triggered",
        "deep_search_reason",
        "decision_reason",
        "summary_explanation",
        "created_at",
    ]
)
DIVINATION_RUN_SCHEME_SELECT_COLUMNS = ", ".join(
    [
        "id",
        "run_id",
        "scheme_index",
        "label",
        "confidence",
        "strategy",
        "front_numbers",
        "back_numbers",
        "rationale",
    ]
)
_draw_prize_amount_index_cache: dict[int, dict[tuple[str, int], float]] = {}
_draw_number_set_cache: dict[int, tuple[frozenset[int], frozenset[int]]] = {}
LIST_RESPONSE_CACHE_TTL_SECONDS = 0.75
_list_response_cache_lock = Lock()
_list_response_cache: dict[tuple[str, int], tuple[float, object]] = {}
HISTORY_QUERY_CACHE_TTL_SECONDS = 0.75
SYNC_STATUS_CACHE_TTL_SECONDS = 0.75
_history_query_cache_lock = Lock()
_history_desc_cache: dict[int, tuple[float, list[LottoDraw]]] = {}
_history_asc_cache: tuple[float, list[LottoDraw]] | None = None
_sync_status_cache: tuple[float, SyncStatus] | None = None
SAVED_SCHEME_EXISTING_SELECT_BATCH_SIZE = 500


def _ticket_cost_for_multiple(multiple: int, is_additional: bool) -> float:
    unit_cost = ADDITIONAL_TICKET_COST if is_additional else TICKET_COST
    return round(unit_cost * multiple, 2)


def _get_cached_list_response(cache_name: str, limit: int):
    cache_key = (cache_name, limit)
    now = monotonic()
    with _list_response_cache_lock:
        cached = _list_response_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= now:
            _list_response_cache.pop(cache_key, None)
            return None
        return value


def _set_cached_list_response(cache_name: str, limit: int, value) -> None:
    cache_key = (cache_name, limit)
    with _list_response_cache_lock:
        _list_response_cache[cache_key] = (monotonic() + LIST_RESPONSE_CACHE_TTL_SECONDS, value)


def _invalidate_cached_list_responses(*cache_names: str) -> None:
    with _list_response_cache_lock:
        if not cache_names:
            _list_response_cache.clear()
            return
        keys_to_remove = [cache_key for cache_key in _list_response_cache if cache_key[0] in cache_names]
        for cache_key in keys_to_remove:
            _list_response_cache.pop(cache_key, None)


def _get_cached_history(limit: int) -> list[LottoDraw] | None:
    now = monotonic()
    with _history_query_cache_lock:
        cached = _history_desc_cache.get(limit)
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= now:
            _history_desc_cache.pop(limit, None)
            return None
        return value


def _set_cached_history(limit: int, value: list[LottoDraw]) -> None:
    with _history_query_cache_lock:
        _history_desc_cache[limit] = (monotonic() + HISTORY_QUERY_CACHE_TTL_SECONDS, value)


def _get_cached_all_history_asc() -> list[LottoDraw] | None:
    now = monotonic()
    with _history_query_cache_lock:
        cached = _history_asc_cache
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= now:
            globals()["_history_asc_cache"] = None
            return None
        return value


def _set_cached_all_history_asc(value: list[LottoDraw]) -> None:
    global _history_asc_cache
    with _history_query_cache_lock:
        _history_asc_cache = (monotonic() + HISTORY_QUERY_CACHE_TTL_SECONDS, value)


def _invalidate_history_query_caches() -> None:
    global _history_asc_cache
    with _history_query_cache_lock:
        _history_desc_cache.clear()
        _history_asc_cache = None


def _get_cached_sync_status() -> SyncStatus | None:
    now = monotonic()
    with _history_query_cache_lock:
        cached = _sync_status_cache
        if cached is None:
            return None
        expires_at, value = cached
        if expires_at <= now:
            globals()["_sync_status_cache"] = None
            return None
        return value


def _set_cached_sync_status(value: SyncStatus) -> None:
    global _sync_status_cache
    with _history_query_cache_lock:
        _sync_status_cache = (monotonic() + SYNC_STATUS_CACHE_TTL_SECONDS, value)


def _invalidate_sync_status_cache() -> None:
    global _sync_status_cache
    with _history_query_cache_lock:
        _sync_status_cache = None


def _serialize_numbers(numbers: list[int]) -> str:
    return json.dumps(numbers, ensure_ascii=False)


@lru_cache(maxsize=4096)
def _deserialize_numbers_cached(raw: str) -> tuple[int, ...]:
    return tuple(int(value) for value in json.loads(raw))


def _deserialize_numbers(raw: str) -> list[int]:
    return list(_deserialize_numbers_cached(raw))


def _serialize_prize_levels(items: list[PrizeLevelItem]) -> str:
    return json.dumps([item.model_dump() for item in items], ensure_ascii=False)


@lru_cache(maxsize=4096)
def _deserialize_prize_levels_cached(raw: str) -> tuple[PrizeLevelItem, ...]:
    decoded = json.loads(raw)
    return tuple(
        PrizeLevelItem.model_construct(
            prize_level=str(item.get("prize_level", "") or ""),
            award_type=int(item.get("award_type", 0) or 0),
            stake_amount=item.get("stake_amount"),
            stake_amount_format=item.get("stake_amount_format"),
            stake_count=item.get("stake_count"),
            total_prize_amount=item.get("total_prize_amount"),
        )
        for item in decoded
    )


def _deserialize_prize_levels(raw: str | None) -> list[PrizeLevelItem]:
    if not raw:
        return []
    return list(_deserialize_prize_levels_cached(raw))


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.replace(",", "").strip()
    if not normalized:
        return None
    return float(normalized)


@lru_cache(maxsize=4096)
def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


@lru_cache(maxsize=4096)
def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _resolve_prize_level(front_match_count: int, back_match_count: int) -> str | None:
    for level, front_need, back_need in PRIZE_LEVEL_RULES:
        if front_match_count == front_need and back_match_count == back_need:
            return level
    return None


def _find_prize_amount(prize_levels: list[PrizeLevelItem], prize_level: str | None) -> float | None:
    if not prize_level:
        return None
    for item in prize_levels:
        if item.prize_level == prize_level and item.award_type == 0:
            return _parse_amount(item.stake_amount_format or item.stake_amount)
    return None


def _find_named_prize_amount(
    prize_levels: list[PrizeLevelItem],
    prize_names: list[str],
    *,
    award_type: int | None = None,
) -> float | None:
    for prize_name in prize_names:
        for item in prize_levels:
            if item.prize_level != prize_name:
                continue
            if award_type is not None and item.award_type != award_type:
                continue
            amount = _parse_amount(item.stake_amount_format or item.stake_amount)
            if amount is not None:
                return amount
    return None


def _draw_prize_amount_index(draw: LottoDraw) -> dict[tuple[str, int], float]:
    cache_key = id(draw)
    cached = _draw_prize_amount_index_cache.get(cache_key)
    if cached is not None:
        return cached
    prize_amounts: dict[tuple[str, int], float] = {}
    for item in draw.prize_level_list:
        amount = _parse_amount(item.stake_amount_format or item.stake_amount)
        if amount is None:
            continue
        prize_amounts.setdefault((item.prize_level, int(item.award_type)), amount)
    _draw_prize_amount_index_cache[cache_key] = prize_amounts
    return prize_amounts


def _find_draw_prize_amount(
    draw: LottoDraw,
    prize_names: list[str],
    *,
    award_type: int = 0,
) -> float | None:
    prize_amounts = _draw_prize_amount_index(draw)
    for prize_name in prize_names:
        amount = prize_amounts.get((prize_name, award_type))
        if amount is not None:
            return amount
    return None


def _draw_number_sets(draw: LottoDraw) -> tuple[frozenset[int], frozenset[int]]:
    cache_key = id(draw)
    cached = _draw_number_set_cache.get(cache_key)
    if cached is not None:
        return cached
    number_sets = (frozenset(draw.front_numbers), frozenset(draw.back_numbers))
    _draw_number_set_cache[cache_key] = number_sets
    return number_sets


@lru_cache(maxsize=1024)
def _promotion_rule_for_issue(issue: str | None) -> dict | None:
    if not issue:
        return None
    try:
        issue_number = int(issue)
    except ValueError:
        return None
    for rule in PROMOTION_RULES:
        if rule["start_issue"] <= issue_number <= rule["end_issue"]:
            return rule
    return None


def _manual_prize_levels(high_pool: bool) -> list[PrizeLevelItem]:
    return [
        PrizeLevelItem(
            prize_level=prize_level,
            award_type=0,
            stake_amount=str(amount),
            stake_amount_format=f"{amount:.2f}",
        )
        for prize_level, amount in FIXED_PRIZE_BY_POOL[high_pool].items()
    ]


def _row_to_manual_draw_result(row) -> ManualDrawResult:
    return ManualDrawResult.model_construct(
        issue=row["issue"],
        draw_date=_parse_iso_date(row["draw_date"]) if row["draw_date"] else None,
        front_numbers=_deserialize_numbers(row["front_numbers"]),
        back_numbers=_deserialize_numbers(row["back_numbers"]),
        high_pool=bool(row["high_pool"]),
        created_at=_parse_iso_datetime(str(row["created_at"])),
        updated_at=_parse_iso_datetime(str(row["updated_at"])),
    )


def _manual_row_to_effective_draw(row) -> LottoDraw:
    draw_date_value = row["draw_date"] if row["draw_date"] else None
    return LottoDraw.model_construct(
        issue=row["issue"],
        draw_date=_parse_iso_date(draw_date_value) if draw_date_value else date.today(),
        front_numbers=_deserialize_numbers(row["front_numbers"]),
        back_numbers=_deserialize_numbers(row["back_numbers"]),
        raw_result="manual",
        prize_level_list=_manual_prize_levels(bool(row["high_pool"])),
    )


def get_manual_draw_result(issue: str) -> ManualDrawResult | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT issue, draw_date, front_numbers, back_numbers, high_pool, created_at, updated_at
            FROM manual_draw_results
            WHERE issue = ?
            """,
            (issue,),
        ).fetchone()
    return _row_to_manual_draw_result(row) if row else None


def evaluate_scheme_against_draw(
    draw: LottoDraw | None,
    *,
    front_numbers: list[int],
    back_numbers: list[int],
    result_source: str = "official",
    multiple: int = 1,
    is_additional: bool = False,
    promotion_ticket_amount: float | None = None,
) -> PrizeEvaluation:
    ticket_amount = _ticket_cost_for_multiple(multiple, is_additional)
    if draw is None:
        return PrizeEvaluation.model_construct(
            status="pending",
            result_source="none",
            multiple=multiple,
            is_additional=is_additional,
            cost_amount=ticket_amount,
        )

    draw_front_numbers, draw_back_numbers = _draw_number_sets(draw)
    front_match_count = sum(1 for number in front_numbers if number in draw_front_numbers)
    back_match_count = sum(1 for number in back_numbers if number in draw_back_numbers)
    prize_level = _resolve_prize_level(front_match_count, back_match_count)
    base_prize_single = _find_draw_prize_amount(draw, [prize_level] if prize_level else [], award_type=0)
    if base_prize_single is None:
        base_prize_single = _find_prize_amount(draw.prize_level_list, prize_level)
    base_prize_amount = round(base_prize_single * multiple, 2) if base_prize_single is not None else None
    additional_prize_single = None
    if is_additional and prize_level in {"\u4e00\u7b49\u5956", "\u4e8c\u7b49\u5956"} and base_prize_single is not None:
        additional_prize_single = _find_draw_prize_amount(draw, [f"{prize_level}(\u8ffd\u52a0)"], award_type=0)
        if additional_prize_single is None:
            additional_prize_single = round(base_prize_single * 0.8, 2)
    additional_prize_amount = round(additional_prize_single * multiple, 2) if additional_prize_single is not None else None
    promotion_rule = _promotion_rule_for_issue(draw.issue)
    bonus_ratios = promotion_rule.get("bonus_ratios", {}) if promotion_rule else {}
    promotion_active = bool(prize_level and prize_level in bonus_ratios)
    promotion_gate_amount = promotion_ticket_amount if promotion_ticket_amount is not None else ticket_amount
    promotion_eligible = bool(
        prize_level
        and promotion_rule
        and promotion_gate_amount >= float(promotion_rule["min_ticket_amount"])
        and prize_level in bonus_ratios
        and base_prize_single is not None
    )
    bonus_prize_single = None
    if promotion_eligible and base_prize_single is not None and prize_level is not None:
        bonus_prize_single = _find_draw_prize_amount(draw, [f"{prize_level}\u6d3e\u5956"], award_type=1)
        if bonus_prize_single is None:
            bonus_ratio = float(bonus_ratios.get(prize_level, 0.0))
            bonus_prize_single = round(base_prize_single * bonus_ratio, 2) if bonus_ratio > 0 else None
    bonus_prize_amount = round(bonus_prize_single * multiple, 2) if bonus_prize_single is not None else None
    total_prize_amount = None
    if base_prize_amount is not None or additional_prize_amount is not None or bonus_prize_amount is not None:
        total_prize_amount = round((base_prize_amount or 0.0) + (additional_prize_amount or 0.0) + (bonus_prize_amount or 0.0), 2)

    if prize_level and total_prize_amount is None and result_source == "manual" and prize_level in {"\u4e00\u7b49\u5956", "\u4e8c\u7b49\u5956"}:
        prize_amount_text = "\u6d6e\u52a8\u5956\uff0c\u5f85\u5b98\u65b9\u5956\u91d1"
    elif total_prize_amount is not None:
        parts: list[str] = []
        if additional_prize_amount:
            parts.append(f"\u8ffd\u52a0 {additional_prize_amount:.2f}")
        if bonus_prize_amount:
            parts.append(f"\u6d3e\u5956 {bonus_prize_amount:.2f}")
        prize_amount_text = f"{total_prize_amount:.2f}" if not parts else f"{total_prize_amount:.2f} (\u542b{' / '.join(parts)})"
    else:
        prize_amount_text = None
    return PrizeEvaluation.model_construct(
        status="won" if prize_level else "not_won",
        result_source="manual" if result_source == "manual" else "official",
        multiple=multiple,
        is_additional=is_additional,
        cost_amount=ticket_amount,
        front_match_count=front_match_count,
        back_match_count=back_match_count,
        prize_level=prize_level,
        base_prize_amount=base_prize_amount,
        additional_prize_amount=additional_prize_amount,
        bonus_prize_amount=bonus_prize_amount,
        prize_amount=total_prize_amount,
        prize_amount_text=prize_amount_text,
        promotion_active=promotion_active,
        promotion_eligible=promotion_eligible,
        promotion_label=promotion_rule["label"] if promotion_eligible and promotion_rule is not None else None,
        promotion_min_ticket_amount=float(promotion_rule["min_ticket_amount"]) if promotion_active and promotion_rule is not None else None,
        draw_issue=draw.issue,
        draw_date=draw.draw_date,
        winning_front_numbers=draw.front_numbers,
        winning_back_numbers=draw.back_numbers,
        evaluated_at=datetime.now(SHANGHAI_TZ),
    )


def upsert_draws(draws: list[LottoDraw]) -> tuple[int, int]:
    if not draws:
        return 0, 0
    inserted = 0
    updated = 0
    with get_connection() as conn:
        existing_rows: dict[str, dict[str, str | None]] = {}
        unique_issues = list(dict.fromkeys(str(draw.issue) for draw in draws))
        for start_index in range(0, len(unique_issues), DRAW_UPSERT_SELECT_BATCH_SIZE):
            issue_batch = unique_issues[start_index : start_index + DRAW_UPSERT_SELECT_BATCH_SIZE]
            placeholders = ", ".join("?" for _ in issue_batch)
            rows = conn.execute(
                f"""
                SELECT issue, draw_date, front_numbers, back_numbers, raw_result,
                       pool_balance_afterdraw, prize_level_list
                FROM lotto_draws
                WHERE issue IN ({placeholders})
                """,
                issue_batch,
            ).fetchall()
            for row in rows:
                existing_rows[str(row["issue"])] = {
                    "draw_date": row["draw_date"],
                    "front_numbers": row["front_numbers"],
                    "back_numbers": row["back_numbers"],
                    "raw_result": row["raw_result"],
                    "pool_balance_afterdraw": row["pool_balance_afterdraw"],
                    "prize_level_list": row["prize_level_list"],
                }
        pending_inserts: dict[str, tuple[str, str, str, str, str | None, str]] = {}
        pending_updates: dict[str, tuple[str, str, str, str, str | None, str, str]] = {}
        for draw in draws:
            issue = str(draw.issue)
            row_values = {
                "draw_date": draw.draw_date.isoformat(),
                "front_numbers": _serialize_numbers(draw.front_numbers),
                "back_numbers": _serialize_numbers(draw.back_numbers),
                "raw_result": draw.raw_result,
                "pool_balance_afterdraw": draw.pool_balance_afterdraw,
                "prize_level_list": _serialize_prize_levels(draw.prize_level_list),
            }
            existing = existing_rows.get(issue)
            if existing is None:
                pending_inserts[issue] = (
                    issue,
                    row_values["draw_date"],
                    row_values["front_numbers"],
                    row_values["back_numbers"],
                    row_values["raw_result"],
                    row_values["pool_balance_afterdraw"],
                    row_values["prize_level_list"],
                )
                existing_rows[issue] = row_values.copy()
                inserted += 1
                continue
            has_changes = any(str(existing[key] or "") != str(value or "") for key, value in row_values.items())
            if not has_changes:
                continue
            existing_rows[issue] = row_values.copy()
            if issue in pending_inserts:
                pending_inserts[issue] = (
                    issue,
                    row_values["draw_date"],
                    row_values["front_numbers"],
                    row_values["back_numbers"],
                    row_values["raw_result"],
                    row_values["pool_balance_afterdraw"],
                    row_values["prize_level_list"],
                )
            else:
                pending_updates[issue] = (
                    row_values["draw_date"],
                    row_values["front_numbers"],
                    row_values["back_numbers"],
                    row_values["raw_result"],
                    row_values["pool_balance_afterdraw"],
                    row_values["prize_level_list"],
                    issue,
                )
            updated += 1
        if pending_inserts:
            conn.executemany(
                """
                INSERT INTO lotto_draws (
                    issue, draw_date, front_numbers, back_numbers, raw_result,
                    pool_balance_afterdraw, prize_level_list, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                list(pending_inserts.values()),
            )
        if pending_updates:
            conn.executemany(
                """
                UPDATE lotto_draws
                SET draw_date = ?,
                    front_numbers = ?,
                    back_numbers = ?,
                    raw_result = ?,
                    pool_balance_afterdraw = ?,
                    prize_level_list = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE issue = ?
                """,
                list(pending_updates.values()),
            )
        conn.commit()
    if inserted or updated:
        _invalidate_history_query_caches()
        _invalidate_sync_status_cache()
        _invalidate_cached_list_responses("saved_schemes", "divination_runs")
    return inserted, updated


def set_meta(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sync_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()
    if key == "last_synced_at":
        _invalidate_sync_status_cache()


def get_meta(key: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM sync_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])


def _row_to_draw(row) -> LottoDraw:
    return LottoDraw.model_construct(
        issue=row["issue"],
        draw_date=_parse_iso_date(row["draw_date"]),
        front_numbers=_deserialize_numbers(row["front_numbers"]),
        back_numbers=_deserialize_numbers(row["back_numbers"]),
        raw_result=row["raw_result"],
        pool_balance_afterdraw=row["pool_balance_afterdraw"],
        prize_level_list=_deserialize_prize_levels(row["prize_level_list"]),
    )


def get_history(limit: int = 100) -> list[LottoDraw]:
    cached = _get_cached_history(limit)
    if cached is not None:
        return cached
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT issue, draw_date, front_numbers, back_numbers, raw_result, pool_balance_afterdraw, prize_level_list
            FROM lotto_draws
            ORDER BY issue DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = [_row_to_draw(row) for row in rows]
    _set_cached_history(limit, result)
    return result


def get_all_history_asc() -> list[LottoDraw]:
    cached = _get_cached_all_history_asc()
    if cached is not None:
        return cached
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT issue, draw_date, front_numbers, back_numbers, raw_result, pool_balance_afterdraw, prize_level_list
            FROM lotto_draws
            ORDER BY issue ASC
            """
        ).fetchall()
    result = [_row_to_draw(row) for row in rows]
    _set_cached_all_history_asc(result)
    return result


def get_draw_by_issue(issue: str) -> LottoDraw | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT issue, draw_date, front_numbers, back_numbers, raw_result, pool_balance_afterdraw, prize_level_list
            FROM lotto_draws
            WHERE issue = ?
            """,
            (issue,),
        ).fetchone()
    return _row_to_draw(row) if row else None


def get_effective_draw_by_issue(issue: str) -> tuple[LottoDraw | None, str]:
    manual = get_manual_draw_result(issue)
    if manual:
        return (
            LottoDraw(
                issue=manual.issue,
                draw_date=manual.draw_date or date.today(),
                front_numbers=manual.front_numbers,
                back_numbers=manual.back_numbers,
                raw_result="manual",
                prize_level_list=_manual_prize_levels(manual.high_pool),
            ),
            "manual",
        )
    official = get_draw_by_issue(issue)
    return official, "official" if official else "none"


def get_effective_draws_by_issues(issues: list[str]) -> dict[str, tuple[LottoDraw | None, str]]:
    """Batch-fetch effective draws for a list of issues to avoid N+1 queries."""
    unique = sorted({str(issue) for issue in issues if issue})
    if not unique:
        return {}
    placeholders = ",".join("?" for _ in unique)
    manual_query = f"""
            SELECT issue, draw_date, front_numbers, back_numbers, high_pool
            FROM manual_draw_results
            WHERE issue IN ({placeholders})
            """
    official_query = f"""
            SELECT issue, draw_date, front_numbers, back_numbers, raw_result, pool_balance_afterdraw, prize_level_list
            FROM lotto_draws
            WHERE issue IN ({placeholders})
            """

    def _fetch_rows(query: str):
        with get_connection() as conn:
            return conn.execute(query, unique).fetchall()

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="effective-draws") as executor:
        manual_future = executor.submit(_fetch_rows, manual_query)
        official_future = executor.submit(_fetch_rows, official_query)
        manual_rows = manual_future.result()
        official_rows = official_future.result()
    manual_map = {str(row["issue"]): row for row in manual_rows}
    official_map = {str(row["issue"]): row for row in official_rows}
    result: dict[str, tuple[LottoDraw | None, str]] = {}
    for issue in unique:
        manual_row = manual_map.get(issue)
        if manual_row is not None:
            result[issue] = (_manual_row_to_effective_draw(manual_row), "manual")
            continue
        official_row = official_map.get(issue)
        if official_row is not None:
            result[issue] = (_row_to_draw(official_row), "official")
        else:
            result[issue] = (None, "none")
    return result


def get_total_draws() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM lotto_draws").fetchone()
    return int(row["count"])


def _is_draw_day(value: date) -> bool:
    return value.weekday() in DRAW_WEEKDAYS


def _next_draw_date_after(reference: date) -> date:
    candidate = reference + timedelta(days=1)
    while not _is_draw_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def _build_next_draw_info(latest_issue: str | None, latest_draw_date: date | None) -> tuple[str | None, datetime | None]:
    if not latest_issue or not latest_draw_date:
        return None, None
    # 下一期 = DB 中最新一期之后的第一个开奖日；期号严格连号 +1。
    # 即便墙钟时间已过当晚 20:30，只要该期开奖结果尚未同步入库，
    # 这里仍视该期为"下一期"，避免跳号。
    next_draw_date = _next_draw_date_after(latest_draw_date)
    next_draw_datetime = datetime.combine(next_draw_date, DRAW_TIME, tzinfo=SHANGHAI_TZ)
    next_issue = str(int(latest_issue) + 1)
    return next_issue, next_draw_datetime


def get_sync_status() -> SyncStatus:
    cached = _get_cached_sync_status()
    if cached is not None:
        return cached
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                issue,
                draw_date,
                (SELECT COUNT(*) FROM lotto_draws) AS total_draws
            FROM lotto_draws
            ORDER BY issue DESC
            LIMIT 1
            """
        ).fetchone()
    latest_issue = None
    latest_draw_date = None
    total_draws = 0
    if row:
        latest_issue = row["issue"]
        latest_draw_date = _parse_iso_date(row["draw_date"])
        total_draws = int(row["total_draws"] or 0)

    last_synced_at = get_meta("last_synced_at")
    next_issue, next_draw_datetime = _build_next_draw_info(latest_issue, latest_draw_date)
    status = SyncStatus(
        total_draws=total_draws,
        latest_issue=latest_issue,
        latest_draw_date=latest_draw_date,
        next_issue=next_issue,
        next_draw_datetime=next_draw_datetime,
        last_synced_at=_parse_iso_datetime(last_synced_at) if last_synced_at else None,
        source="official:webapi.sporttery.cn",
    )
    _set_cached_sync_status(status)
    return status


def save_scheme(payload: SavedSchemeCreateRequest) -> SavedScheme:
    saved_at = datetime.now(SHANGHAI_TZ)
    with get_connection() as conn:
        saved_id, created_at = _upsert_saved_scheme(conn, payload, saved_at=saved_at, return_created_at=True)
        conn.commit()
    draws_map = get_effective_draws_by_issues([payload.target_issue])
    _invalidate_cached_list_responses("saved_schemes")
    return _saved_scheme_from_payload(
        saved_id=saved_id,
        payload=payload,
        created_at=created_at,
        updated_at=saved_at,
        draws_map=draws_map,
    )


def _saved_scheme_identity(payload: SavedSchemeCreateRequest) -> tuple[str, str, str]:
    return (
        str(payload.target_issue),
        _serialize_numbers(payload.scheme.front_numbers),
        _serialize_numbers(payload.scheme.back_numbers),
    )


def _load_existing_saved_scheme_id_map(
    conn,
    identities: list[tuple[str, str, str]],
) -> dict[tuple[str, str, str], tuple[int, datetime]]:
    unique_identities = list(dict.fromkeys(identities))
    if not unique_identities:
        return {}
    identity_set = set(unique_identities)
    unique_issues = list(dict.fromkeys(issue for issue, _front_numbers, _back_numbers in unique_identities))
    existing_id_by_identity: dict[tuple[str, str, str], tuple[int, datetime]] = {}
    for start_index in range(0, len(unique_issues), SAVED_SCHEME_EXISTING_SELECT_BATCH_SIZE):
        issue_batch = unique_issues[start_index : start_index + SAVED_SCHEME_EXISTING_SELECT_BATCH_SIZE]
        placeholders = ",".join("?" for _ in issue_batch)
        rows = conn.execute(
            f"""
            SELECT id, target_issue, front_numbers, back_numbers, created_at
            FROM saved_schemes
            WHERE target_issue IN ({placeholders})
            """,
            issue_batch,
        ).fetchall()
        for row in rows:
            identity = (
                str(row["target_issue"]),
                str(row["front_numbers"]),
                str(row["back_numbers"]),
            )
            if identity in identity_set and identity not in existing_id_by_identity:
                existing_id_by_identity[identity] = (
                    int(row["id"]),
                    _parse_iso_datetime(str(row["created_at"])),
                )
    return existing_id_by_identity


def _upsert_saved_scheme(
    conn,
    payload: SavedSchemeCreateRequest,
    *,
    identity: tuple[str, str, str] | None = None,
    existing_id_by_identity: dict[tuple[str, str, str], tuple[int, datetime]] | None = None,
    saved_at: datetime | None = None,
    return_created_at: bool = False,
) -> int | tuple[int, datetime]:
    scheme = payload.scheme
    resolved_identity = identity or _saved_scheme_identity(payload)
    target_issue, front_numbers, back_numbers = resolved_identity
    existing_entry = existing_id_by_identity.get(resolved_identity) if existing_id_by_identity is not None else None
    existing_id = existing_entry[0] if existing_entry is not None else None
    existing_created_at: datetime | None = None
    if existing_entry is not None:
        existing_created_at = existing_entry[1]
    if existing_id is None:
        existing = conn.execute(
            """
            SELECT id, created_at FROM saved_schemes
            WHERE target_issue = ? AND front_numbers = ? AND back_numbers = ?
            """,
            (target_issue, front_numbers, back_numbers),
        ).fetchone()
        if existing:
            existing_id = int(existing["id"])
            existing_created_at = _parse_iso_datetime(str(existing["created_at"]))
            if existing_id_by_identity is not None:
                existing_id_by_identity[resolved_identity] = (existing_id, existing_created_at)
    if existing_id is not None:
        conn.execute(
            """
            UPDATE saved_schemes
            SET label = ?, rationale = ?, multiple = ?, is_additional = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (scheme.label, scheme.rationale, payload.multiple, 1 if payload.is_additional else 0, existing_id),
        )
        if return_created_at:
            return existing_id, (existing_created_at or saved_at or datetime.now(SHANGHAI_TZ))
        return existing_id

    cursor = conn.execute(
        """
        INSERT INTO saved_schemes (
            target_issue, seed_mode, seed_value, moving_line, ai_engine, label,
            confidence, strategy, front_numbers, back_numbers, rationale,
            tuning_profile, issue_confidence, calibrated_confidence, applied_threshold,
            should_observe, front_confidence, front_gate, back_confidence, back_gate,
            deep_search_triggered, deep_search_reason, decision_reason, multiple, is_additional, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            target_issue,
            payload.seed_mode,
            payload.seed_value,
            payload.moving_line,
            payload.ai_engine,
            scheme.label,
            scheme.confidence,
            scheme.strategy,
            front_numbers,
            back_numbers,
            scheme.rationale,
            payload.tuning_profile,
            payload.issue_confidence,
            payload.calibrated_confidence,
            payload.applied_threshold,
            1 if payload.should_observe else 0,
            payload.front_confidence,
            payload.front_gate,
            payload.back_confidence,
            payload.back_gate,
            1 if payload.deep_search_triggered else 0,
            payload.deep_search_reason,
            payload.decision_reason,
            payload.multiple,
            1 if payload.is_additional else 0,
        ),
    )
    saved_id = int(cursor.lastrowid)
    if existing_id_by_identity is not None:
        existing_id_by_identity[resolved_identity] = (saved_id, saved_at or datetime.now(SHANGHAI_TZ))
    if return_created_at:
        return saved_id, (saved_at or datetime.now(SHANGHAI_TZ))
    return saved_id


def _saved_scheme_row_from_payload(
    *,
    saved_id: int,
    payload: SavedSchemeCreateRequest,
    created_at: datetime,
    updated_at: datetime,
    identity: tuple[str, str, str] | None = None,
) -> dict[str, object]:
    scheme = payload.scheme
    target_issue, front_numbers, back_numbers = identity or _saved_scheme_identity(payload)
    return {
        "id": saved_id,
        "target_issue": target_issue,
        "seed_mode": payload.seed_mode,
        "seed_value": payload.seed_value,
        "moving_line": payload.moving_line,
        "ai_engine": payload.ai_engine,
        "label": scheme.label,
        "confidence": scheme.confidence,
        "strategy": scheme.strategy,
        "front_numbers": front_numbers,
        "back_numbers": back_numbers,
        "rationale": scheme.rationale,
        "tuning_profile": payload.tuning_profile,
        "issue_confidence": payload.issue_confidence,
        "calibrated_confidence": payload.calibrated_confidence,
        "applied_threshold": payload.applied_threshold,
        "should_observe": 1 if payload.should_observe else 0,
        "front_confidence": payload.front_confidence,
        "front_gate": payload.front_gate,
        "back_confidence": payload.back_confidence,
        "back_gate": payload.back_gate,
        "deep_search_triggered": 1 if payload.deep_search_triggered else 0,
        "deep_search_reason": payload.deep_search_reason,
        "decision_reason": payload.decision_reason,
        "multiple": payload.multiple,
        "is_additional": 1 if payload.is_additional else 0,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
    }


def _saved_scheme_from_payload(
    *,
    saved_id: int,
    payload: SavedSchemeCreateRequest,
    created_at: datetime,
    updated_at: datetime,
    draws_map: dict[str, tuple[LottoDraw | None, str]] | None = None,
) -> SavedScheme:
    issue_key = str(payload.target_issue)
    if draws_map is not None and issue_key in draws_map:
        draw, result_source = draws_map[issue_key]
    else:
        draw, result_source = get_effective_draw_by_issue(payload.target_issue)
    scheme = payload.scheme
    front_numbers = list(scheme.front_numbers)
    back_numbers = list(scheme.back_numbers)
    promotion_ticket_amount = _get_manual_issue_ticket_amount(issue_key) if payload.ai_engine == "manual" else None
    evaluation = evaluate_scheme_against_draw(
        draw,
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        result_source=result_source,
        multiple=payload.multiple,
        is_additional=payload.is_additional,
        promotion_ticket_amount=promotion_ticket_amount,
    )
    return SavedScheme.model_construct(
        id=saved_id,
        target_issue=payload.target_issue,
        seed_mode=payload.seed_mode,
        seed_value=payload.seed_value,
        moving_line=payload.moving_line,
        ai_engine=payload.ai_engine,
        label=scheme.label,
        confidence=scheme.confidence,
        strategy=scheme.strategy,
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        rationale=scheme.rationale,
        tuning_profile=payload.tuning_profile,
        issue_confidence=payload.issue_confidence,
        calibrated_confidence=payload.calibrated_confidence,
        applied_threshold=payload.applied_threshold,
        should_observe=payload.should_observe,
        front_confidence=payload.front_confidence,
        front_gate=payload.front_gate,
        back_confidence=payload.back_confidence,
        back_gate=payload.back_gate,
        deep_search_triggered=payload.deep_search_triggered,
        deep_search_reason=payload.deep_search_reason,
        decision_reason=payload.decision_reason,
        multiple=payload.multiple,
        is_additional=payload.is_additional,
        created_at=created_at,
        updated_at=updated_at,
        evaluation=evaluation,
    )


def save_schemes(payloads: list[SavedSchemeCreateRequest]) -> list[SavedScheme]:
    if not payloads:
        return []
    prepared_payloads = [(payload, _saved_scheme_identity(payload)) for payload in payloads]
    final_row_by_id: dict[int, dict[str, object]] = {}
    with get_connection() as conn:
        existing_id_by_identity = _load_existing_saved_scheme_id_map(
            conn,
            [identity for _payload, identity in prepared_payloads],
        )
        saved_ids: list[int] = []
        for payload, identity in prepared_payloads:
            saved_at = datetime.now(SHANGHAI_TZ)
            saved_id, created_at = _upsert_saved_scheme(
                conn,
                payload,
                identity=identity,
                existing_id_by_identity=existing_id_by_identity,
                saved_at=saved_at,
                return_created_at=True,
            )
            saved_ids.append(saved_id)
            final_row_by_id[saved_id] = _saved_scheme_row_from_payload(
                saved_id=saved_id,
                payload=payload,
                created_at=created_at,
                updated_at=saved_at,
                identity=identity,
            )
        conn.commit()
    ordered_rows = [final_row_by_id[saved_id] for saved_id in saved_ids if saved_id in final_row_by_id]
    manual_issue_ticket_amounts = _build_manual_issue_ticket_amounts(ordered_rows)
    draws_map = get_effective_draws_by_issues([str(row["target_issue"]) for row in ordered_rows])
    items = [
        _row_to_saved_scheme(row, manual_issue_ticket_amounts=manual_issue_ticket_amounts, draws_map=draws_map)
        for row in ordered_rows
    ]
    _invalidate_cached_list_responses("saved_schemes")
    return items


def save_manual_scheme(payload: "SavedSchemeManualCreateRequest") -> SavedScheme:
    from app.models import FinalScheme, SavedSchemeCreateRequest

    label = (payload.label or "").strip() or f"\u624b\u52a8\u8d2d\u4e70 {payload.target_issue}"
    note = (payload.note or "").strip() or "\u7528\u6237\u81ea\u884c\u8d2d\u4e70\uff0c\u624b\u52a8\u5f55\u5165"
    scheme = FinalScheme(
        label=label,
        confidence=0.0,
        strategy="\u624b\u52a8\u8d2d\u4e70",
        front_numbers=sorted(payload.front_numbers),
        back_numbers=sorted(payload.back_numbers),
        rationale=note,
    )
    wrapped = SavedSchemeCreateRequest(
        target_issue=payload.target_issue,
        seed_mode="system_time",
        seed_value=datetime.now().isoformat(timespec="seconds"),
        moving_line=0,
        ai_engine="manual",
        scheme=scheme,
        multiple=payload.multiple,
        is_additional=payload.is_additional,
    )
    return save_scheme(wrapped)


def _build_manual_issue_ticket_amounts(rows) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        if row["ai_engine"] != "manual":
            continue
        issue = str(row["target_issue"])
        amount = _ticket_cost_for_multiple(
            int(row["multiple"]) if row["multiple"] is not None else 1,
            bool(row["is_additional"]) if row["is_additional"] is not None else False,
        )
        totals[issue] = round(totals.get(issue, 0.0) + amount, 2)
    return totals


def _get_manual_issue_ticket_amount(issue: str) -> float:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT target_issue, ai_engine, multiple, is_additional
            FROM saved_schemes
            WHERE target_issue = ? AND ai_engine = 'manual'
            """,
            (issue,),
        ).fetchall()
    return _build_manual_issue_ticket_amounts(rows).get(issue, 0.0)


def upsert_manual_draw_result(issue: str, payload: ManualDrawResultUpsertRequest) -> ManualDrawResult:
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO manual_draw_results (
                issue, draw_date, front_numbers, back_numbers, high_pool, updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(issue) DO UPDATE SET
                draw_date = excluded.draw_date,
                front_numbers = excluded.front_numbers,
                back_numbers = excluded.back_numbers,
                high_pool = excluded.high_pool,
                updated_at = CURRENT_TIMESTAMP
            RETURNING issue, draw_date, front_numbers, back_numbers, high_pool, created_at, updated_at
            """,
            (
                issue,
                payload.draw_date.isoformat() if payload.draw_date else None,
                _serialize_numbers(payload.front_numbers),
                _serialize_numbers(payload.back_numbers),
                1 if payload.high_pool else 0,
            ),
        ).fetchone()
        conn.commit()
    _invalidate_cached_list_responses("saved_schemes", "divination_runs")
    return _row_to_manual_draw_result(row)


def delete_manual_draw_result(issue: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("DELETE FROM manual_draw_results WHERE issue = ?", (issue,))
        conn.commit()
    deleted = row.rowcount > 0
    if deleted:
        _invalidate_cached_list_responses("saved_schemes", "divination_runs")
    return deleted


def delete_saved_scheme(saved_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute("DELETE FROM saved_schemes WHERE id = ?", (saved_id,))
        conn.commit()
    deleted = row.rowcount > 0
    if deleted:
        _invalidate_cached_list_responses("saved_schemes")
    return deleted


def delete_saved_schemes_by_issue(issue: str) -> int:
    with get_connection() as conn:
        row = conn.execute("DELETE FROM saved_schemes WHERE target_issue = ?", (issue,))
        conn.commit()
    deleted = int(row.rowcount)
    if deleted:
        _invalidate_cached_list_responses("saved_schemes")
    return deleted


def _row_to_saved_scheme(
    row,
    manual_issue_ticket_amounts: dict[str, float] | None = None,
    draws_map: dict[str, tuple[LottoDraw | None, str]] | None = None,
) -> SavedScheme:
    issue_key = str(row["target_issue"])
    if draws_map is not None and issue_key in draws_map:
        draw, result_source = draws_map[issue_key]
    else:
        draw, result_source = get_effective_draw_by_issue(row["target_issue"])
    front_numbers = _deserialize_numbers(row["front_numbers"])
    back_numbers = _deserialize_numbers(row["back_numbers"])
    multiple = int(row["multiple"]) if row["multiple"] is not None else 1
    is_additional = bool(row["is_additional"]) if row["is_additional"] is not None else False
    promotion_ticket_amount = None
    if row["ai_engine"] == "manual":
        if manual_issue_ticket_amounts is not None:
            promotion_ticket_amount = manual_issue_ticket_amounts.get(str(row["target_issue"]))
        else:
            promotion_ticket_amount = _get_manual_issue_ticket_amount(str(row["target_issue"]))
    evaluation = evaluate_scheme_against_draw(
        draw,
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        result_source=result_source,
        multiple=multiple,
        is_additional=is_additional,
        promotion_ticket_amount=promotion_ticket_amount,
    )
    return SavedScheme.model_construct(
        id=int(row["id"]),
        target_issue=row["target_issue"],
        seed_mode=row["seed_mode"],
        seed_value=row["seed_value"],
        moving_line=int(row["moving_line"]),
        ai_engine=row["ai_engine"],
        label=row["label"],
        confidence=float(row["confidence"]),
        strategy=row["strategy"],
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        rationale=row["rationale"],
        tuning_profile=row["tuning_profile"],
        issue_confidence=float(row["issue_confidence"]) if row["issue_confidence"] is not None else None,
        calibrated_confidence=float(row["calibrated_confidence"]) if row["calibrated_confidence"] is not None else None,
        applied_threshold=float(row["applied_threshold"]) if row["applied_threshold"] is not None else None,
        should_observe=bool(row["should_observe"]) if row["should_observe"] is not None else False,
        front_confidence=float(row["front_confidence"]) if row["front_confidence"] is not None else None,
        front_gate=float(row["front_gate"]) if row["front_gate"] is not None else None,
        back_confidence=float(row["back_confidence"]) if row["back_confidence"] is not None else None,
        back_gate=float(row["back_gate"]) if row["back_gate"] is not None else None,
        deep_search_triggered=bool(row["deep_search_triggered"]) if row["deep_search_triggered"] is not None else False,
        deep_search_reason=row["deep_search_reason"],
        decision_reason=row["decision_reason"],
        multiple=multiple,
        is_additional=is_additional,
        created_at=_parse_iso_datetime(str(row["created_at"])),
        updated_at=_parse_iso_datetime(str(row["updated_at"])),
        evaluation=evaluation,
    )


def _new_saved_scheme_stats_state() -> dict[str, object]:
    return {
        "total_saved": 0,
        "total_cost": 0.0,
        "total_prize_amount": 0.0,
        "evaluated_count": 0,
        "won_count": 0,
        "prize_level_wins": {level: 0 for level in PRIZE_LEVEL_ORDER},
        "mode_summaries": {
            False: {"total_saved": 0, "evaluated_count": 0, "won_count": 0, "total_cost": 0.0, "total_prize_amount": 0.0},
            True: {"total_saved": 0, "evaluated_count": 0, "won_count": 0, "total_cost": 0.0, "total_prize_amount": 0.0},
        },
    }


def _accumulate_saved_scheme_stats(state: dict[str, object], item: SavedScheme) -> None:
    evaluation = item.evaluation
    state["total_saved"] = int(state["total_saved"]) + 1
    state["total_cost"] = float(state["total_cost"]) + evaluation.cost_amount
    mode_summaries = state["mode_summaries"]
    assert isinstance(mode_summaries, dict)
    mode_summary = mode_summaries[item.is_additional]
    assert isinstance(mode_summary, dict)
    mode_summary["total_saved"] = int(mode_summary["total_saved"]) + 1
    mode_summary["total_cost"] = float(mode_summary["total_cost"]) + evaluation.cost_amount
    if evaluation.status == "pending":
        return
    state["evaluated_count"] = int(state["evaluated_count"]) + 1
    mode_summary["evaluated_count"] = int(mode_summary["evaluated_count"]) + 1
    if evaluation.status != "won":
        return
    prize_amount = float(evaluation.prize_amount or 0.0)
    state["won_count"] = int(state["won_count"]) + 1
    state["total_prize_amount"] = float(state["total_prize_amount"]) + prize_amount
    mode_summary["won_count"] = int(mode_summary["won_count"]) + 1
    mode_summary["total_prize_amount"] = float(mode_summary["total_prize_amount"]) + prize_amount
    prize_level_wins = state["prize_level_wins"]
    assert isinstance(prize_level_wins, dict)
    if evaluation.prize_level in prize_level_wins:
        prize_level_wins[evaluation.prize_level] = int(prize_level_wins[evaluation.prize_level]) + 1


def _finalize_saved_scheme_stats(state: dict[str, object]) -> SavedSchemeStats:
    def _mode_stats(summary: dict[str, float | int]) -> SavedSchemeModeStats:
        total_cost = round(float(summary["total_cost"]), 2)
        total_prize_amount = round(float(summary["total_prize_amount"]), 2)
        evaluated_count = int(summary["evaluated_count"])
        won_count = int(summary["won_count"])
        return SavedSchemeModeStats(
            total_saved=int(summary["total_saved"]),
            evaluated_count=evaluated_count,
            won_count=won_count,
            total_cost=total_cost,
            total_prize_amount=total_prize_amount,
            overall_win_rate=round((won_count / evaluated_count) if evaluated_count else 0.0, 4),
            roi=round(((total_prize_amount - total_cost) / total_cost) if total_cost else 0.0, 4),
        )

    total_saved = int(state["total_saved"])
    total_cost = round(float(state["total_cost"]), 2)
    total_prize_amount = round(float(state["total_prize_amount"]), 2)
    evaluated_count = int(state["evaluated_count"])
    won_count = int(state["won_count"])
    prize_level_wins = state["prize_level_wins"]
    assert isinstance(prize_level_wins, dict)
    mode_summaries = state["mode_summaries"]
    assert isinstance(mode_summaries, dict)
    prize_rates = [
        PrizeRateItem(
            level=level,
            wins=int(prize_level_wins[level]),
            rate=round((int(prize_level_wins[level]) / evaluated_count) if evaluated_count else 0.0, 4),
        )
        for level in PRIZE_LEVEL_ORDER
    ]
    return SavedSchemeStats(
        total_saved=total_saved,
        evaluated_count=evaluated_count,
        pending_count=total_saved - evaluated_count,
        won_count=won_count,
        total_cost=total_cost,
        total_prize_amount=total_prize_amount,
        overall_win_rate=round((won_count / evaluated_count) if evaluated_count else 0.0, 4),
        roi=round(((total_prize_amount - total_cost) / total_cost) if total_cost else 0.0, 4),
        basic=_mode_stats(mode_summaries[False]),
        additional=_mode_stats(mode_summaries[True]),
        prize_rates=prize_rates,
    )


def build_saved_scheme_stats(items: list[SavedScheme]) -> SavedSchemeStats:
    state = _new_saved_scheme_stats_state()
    for item in items:
        _accumulate_saved_scheme_stats(state, item)
    return _finalize_saved_scheme_stats(state)


def list_saved_schemes(limit: int = 100) -> SavedSchemeListResponse:
    cached = _get_cached_list_response("saved_schemes", limit)
    if cached is not None:
        return cached
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                """
            + SAVED_SCHEME_SELECT_COLUMNS
            + """
            FROM saved_schemes
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    manual_issue_ticket_amounts = _build_manual_issue_ticket_amounts(rows)
    draws_map = get_effective_draws_by_issues([str(row["target_issue"]) for row in rows])
    items: list[SavedScheme] = []
    stats_state = _new_saved_scheme_stats_state()
    for row in rows:
        item = _row_to_saved_scheme(row, manual_issue_ticket_amounts, draws_map)
        items.append(item)
        _accumulate_saved_scheme_stats(stats_state, item)
    response = SavedSchemeListResponse(items=items, stats=_finalize_saved_scheme_stats(stats_state))
    _set_cached_list_response("saved_schemes", limit, response)
    return response


def save_divination_run(
    response: DivinationResponse,
    *,
    target_issue: str | None = None,
    requested_scheme_count: int | None = None,
    requested_strategy_mode: str | None = None,
    ai_enabled: bool = False,
) -> DivinationRun:
    resolved_target_issue = target_issue or (response.seed_value if response.seed_mode == "issue" else None)
    created_at_dt = datetime.now(SHANGHAI_TZ)
    created_at = created_at_dt.isoformat()
    resolved_requested_scheme_count = requested_scheme_count if requested_scheme_count is not None else len(response.final_schemes)
    resolved_requested_strategy_mode = requested_strategy_mode or response.strategy_mode
    with get_connection() as conn:
        run_cursor = conn.execute(
            """
            INSERT INTO divination_runs (
                target_issue, seed_mode, seed_value, divination_datetime, target_draw_datetime,
                requested_scheme_count, visible_scheme_count, requested_strategy_mode,
                effective_strategy_mode, moving_line, ai_engine, ai_enabled, tuning_profile,
                issue_confidence, calibrated_confidence, applied_threshold, should_observe,
                front_confidence, front_calibrated_confidence, front_gate,
                back_confidence, back_calibrated_confidence, back_gate,
                count_policy, decision_tier, deep_search_triggered, deep_search_reason,
                decision_reason, summary_explanation, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_target_issue,
                response.seed_mode,
                response.seed_value,
                response.divination_datetime,
                response.target_draw_datetime,
                resolved_requested_scheme_count,
                len(response.final_schemes),
                resolved_requested_strategy_mode,
                response.strategy_mode,
                response.moving_line,
                response.ai_analysis.engine,
                1 if ai_enabled else 0,
                response.tuning_profile,
                response.issue_confidence,
                response.calibrated_confidence,
                response.applied_threshold,
                1 if response.should_observe else 0,
                response.front_confidence,
                response.front_calibrated_confidence,
                response.front_gate,
                response.back_confidence,
                response.back_calibrated_confidence,
                response.back_gate,
                response.count_policy,
                response.decision_tier,
                1 if response.deep_search_triggered else 0,
                response.deep_search_reason,
                response.decision_reason,
                response.summary.explanation,
                created_at,
            ),
        )
        run_id = int(run_cursor.lastrowid)
        scheme_rows = [
            (
                run_id,
                scheme_index,
                scheme.label,
                scheme.confidence,
                scheme.strategy,
                _serialize_numbers(scheme.front_numbers),
                _serialize_numbers(scheme.back_numbers),
                scheme.rationale,
            )
            for scheme_index, scheme in enumerate(response.final_schemes, start=1)
        ]
        if scheme_rows:
            conn.executemany(
                """
                INSERT INTO divination_run_schemes (
                    run_id, scheme_index, label, confidence, strategy, front_numbers, back_numbers, rationale
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                scheme_rows,
            )
        conn.commit()
        scheme_id_rows = conn.execute(
            """
            SELECT id, scheme_index
            FROM divination_run_schemes
            WHERE run_id = ?
            ORDER BY scheme_index ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
    draws_map = get_effective_draws_by_issues([resolved_target_issue] if resolved_target_issue else [])
    _invalidate_cached_list_responses("divination_runs")
    return _divination_run_from_response(
        run_id=run_id,
        response=response,
        target_issue=resolved_target_issue,
        requested_scheme_count=resolved_requested_scheme_count,
        requested_strategy_mode=resolved_requested_strategy_mode,
        ai_enabled=ai_enabled,
        created_at=created_at_dt,
        scheme_id_rows=scheme_id_rows,
        draws_map=draws_map,
    )


def _row_to_divination_run_scheme(
    row,
    draw: LottoDraw | None,
    result_source: str,
) -> DivinationRunScheme:
    front_numbers = _deserialize_numbers(row["front_numbers"])
    back_numbers = _deserialize_numbers(row["back_numbers"])
    evaluation = evaluate_scheme_against_draw(
        draw,
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        result_source=result_source,
    )
    return DivinationRunScheme.model_construct(
        id=int(row["id"]),
        run_id=int(row["run_id"]),
        scheme_index=int(row["scheme_index"]),
        label=row["label"],
        confidence=float(row["confidence"]),
        strategy=row["strategy"],
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        rationale=row["rationale"],
        evaluation=evaluation,
    )


def _divination_run_scheme_from_response_scheme(
    *,
    scheme_id: int,
    run_id: int,
    scheme_index: int,
    scheme,
    draw: LottoDraw | None,
    result_source: str,
) -> DivinationRunScheme:
    front_numbers = list(scheme.front_numbers)
    back_numbers = list(scheme.back_numbers)
    evaluation = evaluate_scheme_against_draw(
        draw,
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        result_source=result_source,
    )
    return DivinationRunScheme.model_construct(
        id=scheme_id,
        run_id=run_id,
        scheme_index=scheme_index,
        label=scheme.label,
        confidence=scheme.confidence,
        strategy=scheme.strategy,
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        rationale=scheme.rationale,
        evaluation=evaluation,
    )


def _row_to_divination_run(
    row,
    scheme_rows,
    draws_map: dict[str, tuple[LottoDraw | None, str]] | None = None,
    stats_state: dict[str, int] | None = None,
) -> DivinationRun:
    target_issue = str(row["target_issue"]) if row["target_issue"] is not None else None
    draw = None
    result_source = "none"
    if target_issue:
        if draws_map is not None and target_issue in draws_map:
            draw, result_source = draws_map[target_issue]
        else:
            draw, result_source = get_effective_draw_by_issue(target_issue)
    schemes: list[DivinationRunScheme] = []
    run_has_evaluated = False
    run_has_win = False
    if stats_state is not None:
        stats_state["total_runs"] += 1
    for scheme_row in scheme_rows:
        scheme = _row_to_divination_run_scheme(scheme_row, draw, result_source)
        schemes.append(scheme)
        if stats_state is None:
            continue
        stats_state["total_scheme_count"] += 1
        if scheme.evaluation.status == "pending":
            continue
        run_has_evaluated = True
        stats_state["evaluated_scheme_count"] += 1
        if scheme.evaluation.status == "won":
            run_has_win = True
            stats_state["won_scheme_count"] += 1
    if stats_state is not None:
        if run_has_evaluated:
            stats_state["evaluated_runs"] += 1
        if run_has_win:
            stats_state["hit_issue_count"] += 1
    return DivinationRun.model_construct(
        id=int(row["id"]),
        target_issue=target_issue,
        seed_mode=row["seed_mode"],
        seed_value=row["seed_value"],
        divination_datetime=row["divination_datetime"],
        target_draw_datetime=row["target_draw_datetime"],
        requested_scheme_count=int(row["requested_scheme_count"]) if row["requested_scheme_count"] is not None else len(schemes),
        visible_scheme_count=int(row["visible_scheme_count"]) if row["visible_scheme_count"] is not None else len(schemes),
        requested_strategy_mode=row["requested_strategy_mode"],
        effective_strategy_mode=row["effective_strategy_mode"],
        moving_line=int(row["moving_line"]),
        ai_engine=row["ai_engine"],
        ai_enabled=bool(row["ai_enabled"]) if row["ai_enabled"] is not None else False,
        tuning_profile=row["tuning_profile"],
        issue_confidence=float(row["issue_confidence"]) if row["issue_confidence"] is not None else None,
        calibrated_confidence=float(row["calibrated_confidence"]) if row["calibrated_confidence"] is not None else None,
        applied_threshold=float(row["applied_threshold"]) if row["applied_threshold"] is not None else None,
        should_observe=bool(row["should_observe"]) if row["should_observe"] is not None else False,
        front_confidence=float(row["front_confidence"]) if row["front_confidence"] is not None else None,
        front_calibrated_confidence=float(row["front_calibrated_confidence"]) if row["front_calibrated_confidence"] is not None else None,
        front_gate=float(row["front_gate"]) if row["front_gate"] is not None else None,
        back_confidence=float(row["back_confidence"]) if row["back_confidence"] is not None else None,
        back_calibrated_confidence=float(row["back_calibrated_confidence"]) if row["back_calibrated_confidence"] is not None else None,
        back_gate=float(row["back_gate"]) if row["back_gate"] is not None else None,
        count_policy=row["count_policy"],
        decision_tier=row["decision_tier"],
        deep_search_triggered=bool(row["deep_search_triggered"]) if row["deep_search_triggered"] is not None else False,
        deep_search_reason=row["deep_search_reason"],
        decision_reason=row["decision_reason"],
        summary_explanation=row["summary_explanation"],
        created_at=_parse_iso_datetime(str(row["created_at"])),
        schemes=schemes,
    )


def _divination_run_from_response(
    *,
    run_id: int,
    response: DivinationResponse,
    target_issue: str | None,
    requested_scheme_count: int,
    requested_strategy_mode: str,
    ai_enabled: bool,
    created_at: datetime,
    scheme_id_rows,
    draws_map: dict[str, tuple[LottoDraw | None, str]] | None = None,
) -> DivinationRun:
    draw = None
    result_source = "none"
    if target_issue:
        if draws_map is not None and target_issue in draws_map:
            draw, result_source = draws_map[target_issue]
        else:
            draw, result_source = get_effective_draw_by_issue(target_issue)
    scheme_id_by_index = {int(row["scheme_index"]): int(row["id"]) for row in scheme_id_rows}
    schemes = [
        _divination_run_scheme_from_response_scheme(
            scheme_id=scheme_id_by_index.get(scheme_index, 0),
            run_id=run_id,
            scheme_index=scheme_index,
            scheme=scheme,
            draw=draw,
            result_source=result_source,
        )
        for scheme_index, scheme in enumerate(response.final_schemes, start=1)
    ]
    return DivinationRun.model_construct(
        id=run_id,
        target_issue=target_issue,
        seed_mode=response.seed_mode,
        seed_value=response.seed_value,
        divination_datetime=response.divination_datetime,
        target_draw_datetime=response.target_draw_datetime,
        requested_scheme_count=requested_scheme_count,
        visible_scheme_count=len(response.final_schemes),
        requested_strategy_mode=requested_strategy_mode,
        effective_strategy_mode=response.strategy_mode,
        moving_line=response.moving_line,
        ai_engine=response.ai_analysis.engine,
        ai_enabled=ai_enabled,
        tuning_profile=response.tuning_profile,
        issue_confidence=response.issue_confidence,
        calibrated_confidence=response.calibrated_confidence,
        applied_threshold=response.applied_threshold,
        should_observe=response.should_observe,
        front_confidence=response.front_confidence,
        front_calibrated_confidence=response.front_calibrated_confidence,
        front_gate=response.front_gate,
        back_confidence=response.back_confidence,
        back_calibrated_confidence=response.back_calibrated_confidence,
        back_gate=response.back_gate,
        count_policy=response.count_policy,
        decision_tier=response.decision_tier,
        deep_search_triggered=response.deep_search_triggered,
        deep_search_reason=response.deep_search_reason,
        decision_reason=response.decision_reason,
        summary_explanation=response.summary.explanation,
        created_at=created_at,
        schemes=schemes,
    )


def _new_divination_run_stats_state() -> dict[str, int]:
    return {
        "total_runs": 0,
        "evaluated_runs": 0,
        "total_scheme_count": 0,
        "evaluated_scheme_count": 0,
        "won_scheme_count": 0,
        "hit_issue_count": 0,
    }


def _accumulate_divination_run_stats(state: dict[str, int], item: DivinationRun) -> None:
    state["total_runs"] += 1
    run_has_evaluated = False
    run_has_win = False
    for scheme in item.schemes:
        state["total_scheme_count"] += 1
        if scheme.evaluation.status == "pending":
            continue
        run_has_evaluated = True
        state["evaluated_scheme_count"] += 1
        if scheme.evaluation.status == "won":
            state["won_scheme_count"] += 1
            run_has_win = True
    if run_has_evaluated:
        state["evaluated_runs"] += 1
    if run_has_win:
        state["hit_issue_count"] += 1


def _finalize_divination_run_stats(state: dict[str, int]) -> DivinationRunStats:
    total_runs = state["total_runs"]
    evaluated_runs = state["evaluated_runs"]
    total_scheme_count = state["total_scheme_count"]
    evaluated_scheme_count = state["evaluated_scheme_count"]
    won_scheme_count = state["won_scheme_count"]
    hit_issue_count = state["hit_issue_count"]
    return DivinationRunStats(
        total_runs=total_runs,
        evaluated_runs=evaluated_runs,
        pending_runs=total_runs - evaluated_runs,
        hit_issue_count=hit_issue_count,
        total_scheme_count=total_scheme_count,
        evaluated_scheme_count=evaluated_scheme_count,
        won_scheme_count=won_scheme_count,
        scheme_win_rate=round((won_scheme_count / evaluated_scheme_count) if evaluated_scheme_count else 0.0, 4),
        issue_hit_rate=round((hit_issue_count / evaluated_runs) if evaluated_runs else 0.0, 4),
    )


def build_divination_run_stats(items: list[DivinationRun]) -> DivinationRunStats:
    state = _new_divination_run_stats_state()
    for item in items:
        _accumulate_divination_run_stats(state, item)
    return _finalize_divination_run_stats(state)


def list_divination_runs(limit: int = 100) -> DivinationRunListResponse:
    cached = _get_cached_list_response("divination_runs", limit)
    if cached is not None:
        return cached
    with get_connection() as conn:
        run_rows = conn.execute(
            """
            SELECT
                """
            + DIVINATION_RUN_SELECT_COLUMNS
            + """
            FROM divination_runs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        if not run_rows:
            empty = []
            response = DivinationRunListResponse(items=empty, stats=build_divination_run_stats(empty))
            _set_cached_list_response("divination_runs", limit, response)
            return response
        run_ids = [int(row["id"]) for row in run_rows]
        placeholders = ",".join("?" for _ in run_ids)
        scheme_rows = conn.execute(
            f"""
            SELECT {DIVINATION_RUN_SCHEME_SELECT_COLUMNS}
            FROM divination_run_schemes
            WHERE run_id IN ({placeholders})
            ORDER BY run_id DESC, scheme_index ASC, id ASC
            """,
            run_ids,
        ).fetchall()
    scheme_rows_by_run: dict[int, list] = {}
    for scheme_row in scheme_rows:
        scheme_rows_by_run.setdefault(int(scheme_row["run_id"]), []).append(scheme_row)
    target_issues = [
        str(row["target_issue"])
        for row in run_rows
        if row["target_issue"] is not None and str(row["target_issue"]).strip()
    ]
    draws_map = get_effective_draws_by_issues(target_issues)
    items: list[DivinationRun] = []
    stats_state = _new_divination_run_stats_state()
    for row in run_rows:
        item = _row_to_divination_run(
            row,
            scheme_rows_by_run.get(int(row["id"]), []),
            draws_map,
            stats_state=stats_state,
        )
        items.append(item)
    response = DivinationRunListResponse(items=items, stats=_finalize_divination_run_stats(stats_state))
    _set_cached_list_response("divination_runs", limit, response)
    return response


def build_backtest_stats(issue_results: list[BacktestIssueResult | dict]) -> BacktestResponse:
    normalized = [
        item if isinstance(item, BacktestIssueResult) else BacktestIssueResult.model_validate(item)
        for item in issue_results
    ]
    issue_count = len(normalized)
    total_generated_schemes = 0
    won_schemes = 0
    total_prize_amount_raw = 0.0
    total_cost_raw = 0.0
    issue_hit_count = 0
    front_pairwise_overlap_total = 0.0
    back_pairwise_overlap_total = 0.0
    back_pair_reuse_total = 0.0
    fresh_back_number_total = 0.0
    prize_level_wins = {level: 0 for level in PRIZE_LEVEL_ORDER}
    prize_level_issue_hits = {level: 0 for level in PRIZE_LEVEL_ORDER}
    prize_level_amounts = {level: 0.0 for level in PRIZE_LEVEL_ORDER}
    for item in normalized:
        total_generated_schemes += item.scheme_count
        won_schemes += item.won_count
        total_prize_amount_raw += item.total_prize_amount or item.best_prize_amount or 0.0
        total_cost_raw += item.cost or 0.0
        if item.won_count > 0:
            issue_hit_count += 1
        front_pairwise_overlap_total += item.front_pairwise_overlap_avg
        back_pairwise_overlap_total += item.back_pairwise_overlap_avg
        back_pair_reuse_total += item.back_pair_reuse_rate
        fresh_back_number_total += item.fresh_back_number_rate
        for level in PRIZE_LEVEL_ORDER:
            wins = item.prize_level_hits.get(level, 0) if item.prize_level_hits else (1 if item.best_prize_level == level else 0)
            if wins > 0:
                prize_level_wins[level] += wins
                prize_level_issue_hits[level] += 1
            prize_level_amounts[level] += (
                item.prize_level_amounts.get(level, 0.0)
                if item.prize_level_amounts
                else ((item.total_prize_amount or item.best_prize_amount or 0.0) if item.best_prize_level == level else 0.0)
            )
    total_prize_amount = round(total_prize_amount_raw, 2)
    total_cost = round(total_cost_raw, 2)
    net_profit = round(total_prize_amount - total_cost, 2)
    prize_rates: list[PrizeRateItem] = []
    prize_level_breakdown: list[BacktestPrizeLevelSummary] = []
    for level in PRIZE_LEVEL_ORDER:
        wins = prize_level_wins[level]
        issue_hits = prize_level_issue_hits[level]
        total_level_amount = round(prize_level_amounts[level], 2)
        rate = round((wins / total_generated_schemes) if total_generated_schemes else 0.0, 4)
        prize_rates.append(PrizeRateItem(level=level, wins=wins, rate=rate))
        prize_level_breakdown.append(
            BacktestPrizeLevelSummary(
                level=level,
                wins=wins,
                scheme_rate=rate,
                issue_hits=issue_hits,
                issue_rate=round((issue_hits / issue_count) if issue_count else 0.0, 4),
                total_prize_amount=total_level_amount,
                average_prize_amount=round((total_level_amount / wins) if wins else 0.0, 2),
            )
        )
    coverage_metrics = BacktestCoverageMetrics(
        front_pairwise_overlap_avg=round(
            front_pairwise_overlap_total / issue_count,
            4,
        ) if issue_count else 0.0,
        back_pairwise_overlap_avg=round(
            back_pairwise_overlap_total / issue_count,
            4,
        ) if issue_count else 0.0,
        back_pair_reuse_rate=round(
            back_pair_reuse_total / issue_count,
            4,
        ) if issue_count else 0.0,
        fresh_back_number_rate=round(
            fresh_back_number_total / issue_count,
            4,
        ) if issue_count else 0.0,
    )
    return BacktestResponse(
        recent_issues=issue_count,
        scheme_count=normalized[0].scheme_count if normalized else 0,
        ticket_mode=normalized[0].ticket_mode if normalized else "basic",
        total_issues=issue_count,
        total_generated_schemes=total_generated_schemes,
        won_schemes=won_schemes,
        total_prize_amount=total_prize_amount,
        total_cost=total_cost,
        net_profit=net_profit,
        overall_win_rate=round((won_schemes / total_generated_schemes) if total_generated_schemes else 0.0, 4),
        issue_hit_rate=round((issue_hit_count / issue_count) if issue_count else 0.0, 4),
        prize_rates=prize_rates,
        prize_level_breakdown=prize_level_breakdown,
        issues=normalized,
        coverage_metrics=coverage_metrics,
    )
