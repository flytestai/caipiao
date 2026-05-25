from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
from zoneinfo import ZoneInfo

from app.db import get_connection
from app.models import (
    BacktestCoverageMetrics,
    BacktestIssueResult,
    BacktestPrizeLevelSummary,
    BacktestResponse,
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


def _ticket_cost_for_multiple(multiple: int, is_additional: bool) -> float:
    unit_cost = ADDITIONAL_TICKET_COST if is_additional else TICKET_COST
    return round(unit_cost * multiple, 2)


def _serialize_numbers(numbers: list[int]) -> str:
    return json.dumps(numbers, ensure_ascii=False)


def _deserialize_numbers(raw: str) -> list[int]:
    return [int(value) for value in json.loads(raw)]


def _serialize_prize_levels(items: list[PrizeLevelItem]) -> str:
    return json.dumps([item.model_dump() for item in items], ensure_ascii=False)


def _deserialize_prize_levels(raw: str | None) -> list[PrizeLevelItem]:
    if not raw:
        return []
    return [PrizeLevelItem.model_validate(item) for item in json.loads(raw)]


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.replace(",", "").strip()
    if not normalized:
        return None
    return float(normalized)


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
    return ManualDrawResult(
        issue=row["issue"],
        draw_date=date.fromisoformat(row["draw_date"]) if row["draw_date"] else None,
        front_numbers=_deserialize_numbers(row["front_numbers"]),
        back_numbers=_deserialize_numbers(row["back_numbers"]),
        high_pool=bool(row["high_pool"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
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
        return PrizeEvaluation(
            status="pending",
            result_source="none",
            multiple=multiple,
            is_additional=is_additional,
            cost_amount=ticket_amount,
        )

    front_match_count = len(set(front_numbers) & set(draw.front_numbers))
    back_match_count = len(set(back_numbers) & set(draw.back_numbers))
    prize_level = _resolve_prize_level(front_match_count, back_match_count)
    base_prize_single = _find_named_prize_amount(draw.prize_level_list, [prize_level] if prize_level else [], award_type=0)
    if base_prize_single is None:
        base_prize_single = _find_prize_amount(draw.prize_level_list, prize_level)
    base_prize_amount = round(base_prize_single * multiple, 2) if base_prize_single is not None else None
    additional_prize_single = None
    if is_additional and prize_level in {"\u4e00\u7b49\u5956", "\u4e8c\u7b49\u5956"} and base_prize_single is not None:
        additional_prize_single = _find_named_prize_amount(draw.prize_level_list, [f"{prize_level}(\u8ffd\u52a0)"], award_type=0)
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
        bonus_prize_single = _find_named_prize_amount(draw.prize_level_list, [f"{prize_level}\u6d3e\u5956"], award_type=1)
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
    return PrizeEvaluation(
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
    inserted = 0
    updated = 0
    with get_connection() as conn:
        for draw in draws:
            existing = conn.execute("SELECT issue FROM lotto_draws WHERE issue = ?", (draw.issue,)).fetchone()
            conn.execute(
                """
                INSERT INTO lotto_draws (
                    issue, draw_date, front_numbers, back_numbers, raw_result,
                    pool_balance_afterdraw, prize_level_list, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(issue) DO UPDATE SET
                    draw_date = excluded.draw_date,
                    front_numbers = excluded.front_numbers,
                    back_numbers = excluded.back_numbers,
                    raw_result = excluded.raw_result,
                    pool_balance_afterdraw = excluded.pool_balance_afterdraw,
                    prize_level_list = excluded.prize_level_list,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    draw.issue,
                    draw.draw_date.isoformat(),
                    _serialize_numbers(draw.front_numbers),
                    _serialize_numbers(draw.back_numbers),
                    draw.raw_result,
                    draw.pool_balance_afterdraw,
                    _serialize_prize_levels(draw.prize_level_list),
                ),
            )
            if existing:
                updated += 1
            else:
                inserted += 1
        conn.commit()
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


def get_meta(key: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM sync_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])


def _row_to_draw(row) -> LottoDraw:
    return LottoDraw(
        issue=row["issue"],
        draw_date=date.fromisoformat(row["draw_date"]),
        front_numbers=_deserialize_numbers(row["front_numbers"]),
        back_numbers=_deserialize_numbers(row["back_numbers"]),
        raw_result=row["raw_result"],
        pool_balance_afterdraw=row["pool_balance_afterdraw"],
        prize_level_list=_deserialize_prize_levels(row["prize_level_list"]),
    )


def get_history(limit: int = 100) -> list[LottoDraw]:
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
    return [_row_to_draw(row) for row in rows]


def get_all_history_asc() -> list[LottoDraw]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT issue, draw_date, front_numbers, back_numbers, raw_result, pool_balance_afterdraw, prize_level_list
            FROM lotto_draws
            ORDER BY issue ASC
            """
        ).fetchall()
    return [_row_to_draw(row) for row in rows]


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
    with get_connection() as conn:
        manual_rows = conn.execute(
            f"""
            SELECT issue, draw_date, front_numbers, back_numbers, high_pool, created_at, updated_at
            FROM manual_draw_results
            WHERE issue IN ({placeholders})
            """,
            unique,
        ).fetchall()
        official_rows = conn.execute(
            f"""
            SELECT issue, draw_date, front_numbers, back_numbers, raw_result, pool_balance_afterdraw, prize_level_list
            FROM lotto_draws
            WHERE issue IN ({placeholders})
            """,
            unique,
        ).fetchall()
    manual_map = {str(row["issue"]): row for row in manual_rows}
    official_map = {str(row["issue"]): row for row in official_rows}
    result: dict[str, tuple[LottoDraw | None, str]] = {}
    for issue in unique:
        manual_row = manual_map.get(issue)
        if manual_row is not None:
            manual = _row_to_manual_draw_result(manual_row)
            result[issue] = (
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
    latest_issue = None
    latest_draw_date = None
    with get_connection() as conn:
        row = conn.execute("SELECT issue, draw_date FROM lotto_draws ORDER BY issue DESC LIMIT 1").fetchone()
        if row:
            latest_issue = row["issue"]
            latest_draw_date = date.fromisoformat(row["draw_date"])

    last_synced_at = get_meta("last_synced_at")
    next_issue, next_draw_datetime = _build_next_draw_info(latest_issue, latest_draw_date)
    return SyncStatus(
        total_draws=get_total_draws(),
        latest_issue=latest_issue,
        latest_draw_date=latest_draw_date,
        next_issue=next_issue,
        next_draw_datetime=next_draw_datetime,
        last_synced_at=datetime.fromisoformat(last_synced_at) if last_synced_at else None,
        source="official:webapi.sporttery.cn",
    )


def save_scheme(payload: SavedSchemeCreateRequest) -> SavedScheme:
    scheme = payload.scheme
    with get_connection() as conn:
        saved_id = _upsert_saved_scheme(conn, payload)
        conn.commit()
        row = conn.execute("SELECT * FROM saved_schemes WHERE id = ?", (saved_id,)).fetchone()
    return _row_to_saved_scheme(row)


def _upsert_saved_scheme(conn, payload: SavedSchemeCreateRequest) -> int:
    scheme = payload.scheme
    front_numbers = _serialize_numbers(scheme.front_numbers)
    back_numbers = _serialize_numbers(scheme.back_numbers)
    existing = conn.execute(
        """
        SELECT id FROM saved_schemes
        WHERE target_issue = ? AND front_numbers = ? AND back_numbers = ?
        """,
        (payload.target_issue, front_numbers, back_numbers),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE saved_schemes
            SET label = ?, rationale = ?, multiple = ?, is_additional = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (scheme.label, scheme.rationale, payload.multiple, 1 if payload.is_additional else 0, existing["id"]),
        )
        return int(existing["id"])

    conn.execute(
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
            payload.target_issue,
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
    return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])


def save_schemes(payloads: list[SavedSchemeCreateRequest]) -> list[SavedScheme]:
    if not payloads:
        return []
    with get_connection() as conn:
        saved_ids = [_upsert_saved_scheme(conn, payload) for payload in payloads]
        conn.commit()
        placeholders = ",".join("?" for _ in saved_ids)
        rows = conn.execute(f"SELECT * FROM saved_schemes WHERE id IN ({placeholders})", saved_ids).fetchall()
    row_by_id = {int(row["id"]): row for row in rows}
    ordered_rows = [row_by_id[saved_id] for saved_id in saved_ids if saved_id in row_by_id]
    draws_map = get_effective_draws_by_issues([str(row["target_issue"]) for row in ordered_rows])
    return [_row_to_saved_scheme(row, draws_map=draws_map) for row in ordered_rows]


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
        conn.execute(
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
            """,
            (
                issue,
                payload.draw_date.isoformat() if payload.draw_date else None,
                _serialize_numbers(payload.front_numbers),
                _serialize_numbers(payload.back_numbers),
                1 if payload.high_pool else 0,
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT issue, draw_date, front_numbers, back_numbers, high_pool, created_at, updated_at
            FROM manual_draw_results
            WHERE issue = ?
            """,
            (issue,),
        ).fetchone()
    return _row_to_manual_draw_result(row)


def delete_manual_draw_result(issue: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("DELETE FROM manual_draw_results WHERE issue = ?", (issue,))
        conn.commit()
    return row.rowcount > 0


def delete_saved_scheme(saved_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute("DELETE FROM saved_schemes WHERE id = ?", (saved_id,))
        conn.commit()
    return row.rowcount > 0


def delete_saved_schemes_by_issue(issue: str) -> int:
    with get_connection() as conn:
        row = conn.execute("DELETE FROM saved_schemes WHERE target_issue = ?", (issue,))
        conn.commit()
    return int(row.rowcount)


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
    return SavedScheme(
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
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        evaluation=evaluation,
    )


def build_saved_scheme_stats(items: list[SavedScheme]) -> SavedSchemeStats:
    def _mode_stats(mode_items: list[SavedScheme]) -> SavedSchemeModeStats:
        evaluated_mode_items = [item for item in mode_items if item.evaluation.status != "pending"]
        won_mode_items = [item for item in evaluated_mode_items if item.evaluation.status == "won"]
        total_mode_cost = round(sum(item.evaluation.cost_amount for item in mode_items), 2)
        total_mode_prize = round(sum(item.evaluation.prize_amount or 0 for item in won_mode_items), 2)
        evaluated_mode_count = len(evaluated_mode_items)
        won_mode_count = len(won_mode_items)
        return SavedSchemeModeStats(
            total_saved=len(mode_items),
            evaluated_count=evaluated_mode_count,
            won_count=won_mode_count,
            total_cost=total_mode_cost,
            total_prize_amount=total_mode_prize,
            overall_win_rate=round((won_mode_count / evaluated_mode_count) if evaluated_mode_count else 0.0, 4),
            roi=round(((total_mode_prize - total_mode_cost) / total_mode_cost) if total_mode_cost else 0.0, 4),
        )

    total_saved = len(items)
    evaluated_items = [item for item in items if item.evaluation.status != "pending"]
    won_items = [item for item in evaluated_items if item.evaluation.status == "won"]
    total_prize_amount = round(sum(item.evaluation.prize_amount or 0 for item in won_items), 2)
    evaluated_count = len(evaluated_items)
    total_cost = round(sum(item.evaluation.cost_amount for item in items), 2)
    basic_items = [item for item in items if not item.is_additional]
    additional_items = [item for item in items if item.is_additional]
    prize_rates: list[PrizeRateItem] = []
    for level in PRIZE_LEVEL_ORDER:
        wins = sum(1 for item in won_items if item.evaluation.prize_level == level)
        rate = round((wins / evaluated_count) if evaluated_count else 0.0, 4)
        prize_rates.append(PrizeRateItem(level=level, wins=wins, rate=rate))
    return SavedSchemeStats(
        total_saved=total_saved,
        evaluated_count=evaluated_count,
        pending_count=total_saved - evaluated_count,
        won_count=len(won_items),
        total_cost=total_cost,
        total_prize_amount=total_prize_amount,
        overall_win_rate=round((len(won_items) / evaluated_count) if evaluated_count else 0.0, 4),
        roi=round(((total_prize_amount - total_cost) / total_cost) if total_cost else 0.0, 4),
        basic=_mode_stats(basic_items),
        additional=_mode_stats(additional_items),
        prize_rates=prize_rates,
    )


def list_saved_schemes(limit: int = 100) -> SavedSchemeListResponse:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM saved_schemes
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    manual_issue_ticket_amounts = _build_manual_issue_ticket_amounts(rows)
    draws_map = get_effective_draws_by_issues([str(row["target_issue"]) for row in rows])
    items = [
        _row_to_saved_scheme(row, manual_issue_ticket_amounts, draws_map)
        for row in rows
    ]
    return SavedSchemeListResponse(items=items, stats=build_saved_scheme_stats(items))


def build_backtest_stats(issue_results: list[BacktestIssueResult | dict]) -> BacktestResponse:
    normalized = [
        item if isinstance(item, BacktestIssueResult) else BacktestIssueResult.model_validate(item)
        for item in issue_results
    ]
    total_generated_schemes = sum(item.scheme_count for item in normalized)
    won_schemes = sum(item.won_count for item in normalized)
    total_prize_amount = round(sum(item.total_prize_amount or item.best_prize_amount or 0 for item in normalized), 2)
    total_cost = round(sum(item.cost or 0.0 for item in normalized), 2)
    net_profit = round(total_prize_amount - total_cost, 2)
    issue_hit_count = sum(1 for item in normalized if item.won_count > 0)
    prize_rates: list[PrizeRateItem] = []
    prize_level_breakdown: list[BacktestPrizeLevelSummary] = []
    for level in PRIZE_LEVEL_ORDER:
        wins = sum(
            (item.prize_level_hits.get(level, 0) if item.prize_level_hits else (1 if item.best_prize_level == level else 0))
            for item in normalized
        )
        issue_hits = sum(
            1
            for item in normalized
            if (item.prize_level_hits.get(level, 0) if item.prize_level_hits else (1 if item.best_prize_level == level else 0)) > 0
        )
        total_level_amount = round(
            sum(
                item.prize_level_amounts.get(level, 0.0)
                if item.prize_level_amounts
                else ((item.total_prize_amount or item.best_prize_amount or 0.0) if item.best_prize_level == level else 0.0)
                for item in normalized
            ),
            2,
        )
        rate = round((wins / total_generated_schemes) if total_generated_schemes else 0.0, 4)
        prize_rates.append(PrizeRateItem(level=level, wins=wins, rate=rate))
        prize_level_breakdown.append(
            BacktestPrizeLevelSummary(
                level=level,
                wins=wins,
                scheme_rate=rate,
                issue_hits=issue_hits,
                issue_rate=round((issue_hits / len(normalized)) if normalized else 0.0, 4),
                total_prize_amount=total_level_amount,
                average_prize_amount=round((total_level_amount / wins) if wins else 0.0, 2),
            )
        )
    coverage_metrics = BacktestCoverageMetrics(
        front_pairwise_overlap_avg=round(
            sum(item.front_pairwise_overlap_avg for item in normalized) / len(normalized),
            4,
        ) if normalized else 0.0,
        back_pairwise_overlap_avg=round(
            sum(item.back_pairwise_overlap_avg for item in normalized) / len(normalized),
            4,
        ) if normalized else 0.0,
        back_pair_reuse_rate=round(
            sum(item.back_pair_reuse_rate for item in normalized) / len(normalized),
            4,
        ) if normalized else 0.0,
        fresh_back_number_rate=round(
            sum(item.fresh_back_number_rate for item in normalized) / len(normalized),
            4,
        ) if normalized else 0.0,
    )
    return BacktestResponse(
        recent_issues=len(normalized),
        scheme_count=normalized[0].scheme_count if normalized else 0,
        ticket_mode=normalized[0].ticket_mode if normalized else "basic",
        total_issues=len(normalized),
        total_generated_schemes=total_generated_schemes,
        won_schemes=won_schemes,
        total_prize_amount=total_prize_amount,
        total_cost=total_cost,
        net_profit=net_profit,
        overall_win_rate=round((won_schemes / total_generated_schemes) if total_generated_schemes else 0.0, 4),
        issue_hit_rate=round((issue_hit_count / len(normalized)) if normalized else 0.0, 4),
        prize_rates=prize_rates,
        prize_level_breakdown=prize_level_breakdown,
        issues=normalized,
        coverage_metrics=coverage_metrics,
    )
