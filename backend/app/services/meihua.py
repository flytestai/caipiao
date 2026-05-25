from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from itertools import combinations

from app.models import (
    AIAnalysis,
    AIConfigRequest,
    CandidateBreakdown,
    DivinationResponse,
    FinalScheme,
    HexagramInfo,
    RecommendationNumber,
    RecommendationSummary,
    TailWeightItem,
    ZoneSignal,
)
from app.services.ai_gateway import chat_completion
from app.services.analytics import build_analytics
from app.services.repository import get_history

logger = logging.getLogger(__name__)


class AIConfigurationError(RuntimeError):
    pass


class AIGenerationError(RuntimeError):
    pass

# 梅花起卦与下一期开奖时点统一按 21:30 取值，避免展示时间和实际推演输入分叉。
DIVINATION_DRAW_TIME = time(hour=21, minute=30)
DRAW_WEEKDAYS = {0, 2, 5}
DEFAULT_SCORE_WEIGHTS = {
    "tail": 0.15,
    "omission": 0.35,
    "frequency": 0.30,
    "recent_hits": 0.20,
}
DEFAULT_COMBO_WEIGHTS = {
    "candidate": 0.64,
    "structure": 0.36,
    "pair_front": 0.74,
    "pair_back": 0.26,
    "multi_cover_pair": 0.74,
    "multi_cover_novelty": 0.26,
    "single_hit_pair": 0.92,
    "single_hit_novelty": 0.08,
    "overlap_front": 0.12,
    "overlap_back": 0.45,
    "same_back_pair_penalty": 1.25,
    "back_usage_penalty": 0.25,
    "fresh_back_bonus": 0.30,
    "crowd_penalty": 0.20,
    "jackpot_front_core": 0.0,
    "front_wheel_mode": 0.0,
    "front_anchor_repeat_mode": 0.0,
    "back_wheel_mode": 0.0,
    "front_pool_boost": 0.0,
    "back_pool_boost": 0.0,
    "front_combo_limit_boost": 0.0,
    "back_combo_limit_boost": 0.0,
    "ticket_candidate_budget_boost": 0.0,
    "floor_harvest_slots": 0.0,
    "front_jackpot_pattern": 0.0,
    "front_probe_slots": 0.0,
    "front_probe_anchor_bonus": 0.0,
    "front_probe_support_bonus": 0.0,
    "back_independent_coverage": 0.0,
    "back_jackpot_slots": 0.0,
    "back_pair_floor_bonus": 0.0,
    "back_pair_coverage_bonus": 0.0,
}
MULTI_COVER_SUPERVISED_WINDOWS = ((12, 0.42), (36, 0.33), (108, 0.25))

DEFAULT_AI_SYSTEM_PROMPT = (
    "\u4f60\u662f\u4e00\u4f4d\u7406\u6027\u3001\u4e25\u8c28\u7684\u5f69\u7968\u6570\u636e\u5206\u6790\u52a9\u624b\uff0c"
    "\u4f1a\u7ed3\u5408\u5386\u53f2\u9891\u7387\u3001\u9057\u6f0f\u3001\u51b7\u70ed\u3001\u5947\u5076\u8df3\u5ea6\u4e0e\u6885\u82b1\u5366\u8c61\u4fe1\u53f7\u5bf9\u5927\u4e50\u900f\u8fdb\u884c\u70b9\u8bc4\uff0c"
    "\u4e0d\u4f1a\u627f\u8bfa\u4efb\u4f55\u4e2d\u5956\u7ed3\u679c\uff0c\u8a00\u8f9e\u51c6\u786e\u3001\u4e0d\u91cd\u590d\u3002"
)

TRIGRAMS = {
    1: {"name": "Qian", "element": "metal", "lines": [1, 1, 1]},
    2: {"name": "Dui", "element": "metal", "lines": [1, 1, 0]},
    3: {"name": "Li", "element": "fire", "lines": [1, 0, 1]},
    4: {"name": "Zhen", "element": "wood", "lines": [1, 0, 0]},
    5: {"name": "Xun", "element": "wood", "lines": [0, 1, 1]},
    6: {"name": "Kan", "element": "water", "lines": [0, 1, 0]},
    7: {"name": "Gen", "element": "earth", "lines": [0, 0, 1]},
    8: {"name": "Kun", "element": "earth", "lines": [0, 0, 0]},
}

HEXAGRAM_NAMES = {
    "111111": "Qian over Qian",
    "111110": "Heaven over Lake",
    "111101": "Heaven over Fire",
    "111100": "Heaven over Thunder",
    "111011": "Heaven over Wind",
    "111010": "Heaven over Water",
    "111001": "Heaven over Mountain",
    "111000": "Heaven over Earth",
    "110111": "Lake over Heaven",
    "110110": "Dui over Dui",
    "110101": "Lake over Fire",
    "110100": "Lake over Thunder",
    "110011": "Lake over Wind",
    "110010": "Lake over Water",
    "110001": "Lake over Mountain",
    "110000": "Lake over Earth",
    "101111": "Fire over Heaven",
    "101110": "Fire over Lake",
    "101101": "Li over Li",
    "101100": "Fire over Thunder",
    "101011": "Fire over Wind",
    "101010": "Fire over Water",
    "101001": "Fire over Mountain",
    "101000": "Fire over Earth",
    "100111": "Thunder over Heaven",
    "100110": "Thunder over Lake",
    "100101": "Thunder over Fire",
    "100100": "Zhen over Zhen",
    "100011": "Thunder over Wind",
    "100010": "Thunder over Water",
    "100001": "Thunder over Mountain",
    "100000": "Thunder over Earth",
    "011111": "Wind over Heaven",
    "011110": "Wind over Lake",
    "011101": "Wind over Fire",
    "011100": "Wind over Thunder",
    "011011": "Xun over Xun",
    "011010": "Wind over Water",
    "011001": "Wind over Mountain",
    "011000": "Wind over Earth",
    "010111": "Water over Heaven",
    "010110": "Water over Lake",
    "010101": "Water over Fire",
    "010100": "Water over Thunder",
    "010011": "Water over Wind",
    "010010": "Kan over Kan",
    "010001": "Water over Mountain",
    "010000": "Water over Earth",
    "001111": "Mountain over Heaven",
    "001110": "Mountain over Lake",
    "001101": "Mountain over Fire",
    "001100": "Mountain over Thunder",
    "001011": "Mountain over Wind",
    "001010": "Mountain over Water",
    "001001": "Gen over Gen",
    "001000": "Mountain over Earth",
    "000111": "Earth over Heaven",
    "000110": "Earth over Lake",
    "000101": "Earth over Fire",
    "000100": "Earth over Thunder",
    "000011": "Earth over Wind",
    "000010": "Earth over Water",
    "000001": "Earth over Mountain",
    "000000": "Kun over Kun",
}

ELEMENT_DIGITS = {
    "water": {1, 6},
    "fire": {2, 7},
    "wood": {3, 8},
    "metal": {4, 9},
    "earth": {5, 0},
}

ELEMENT_GENERATES = {"wood": "fire", "fire": "earth", "earth": "metal", "metal": "water", "water": "wood"}
ELEMENT_LABELS = {
    "metal": "\u91d1",
    "wood": "\u6728",
    "water": "\u6c34",
    "fire": "\u706b",
    "earth": "\u571f",
}
SCHEME_STYLES = [
    "\u7a33\u5065\u4e3b\u9009",
    "\u5e73\u8861\u6269\u6563",
    "\u8d8b\u52bf\u5f3a\u5316",
    "\u51b7\u53f7\u56de\u8865",
    "\u70ed\u53f7\u8ddf\u8fdb",
    "\u5c3e\u6570\u805a\u7126",
    "\u8de8\u5ea6\u4f18\u5148",
    "\u5947\u6570\u504f\u5f3a",
    "\u5076\u6570\u504f\u5f3a",
    "\u9ad8\u533a\u538b\u7f29",
    "\u4f4e\u533a\u94fa\u5f00",
    "\u5747\u8861\u5907\u9009",
]


@dataclass
class SeedContext:
    mode: str
    seed_value: str
    numbers: list[int]
    divination_datetime: datetime
    target_draw_datetime: datetime


@dataclass
class DerivedHexagrams:
    main: HexagramInfo
    mutual: HexagramInfo
    changed: HexagramInfo
    moving_line: int
    upper_num: int
    lower_num: int


@dataclass
class PrecomputedHistoryFeatures:
    history_size: int
    front_frequency: dict[int, int]
    back_frequency: dict[int, int]
    front_omission: dict[int, int]
    back_omission: dict[int, int]
    front_recent_hits: dict[int, int]
    back_recent_hits: dict[int, int]
    front_window_hits: dict[int, dict[int, int]]
    back_window_hits: dict[int, dict[int, int]]


@dataclass(frozen=True)
class TicketCandidate:
    front_numbers: tuple[int, ...]
    back_numbers: tuple[int, ...]
    front_set: frozenset[int]
    back_set: frozenset[int]
    front_score: float
    back_score: float
    base_score: float
    crowd_penalty: float


@dataclass(frozen=True)
class TicketSelectionContext:
    front_covered: frozenset[int]
    back_covered: frozenset[int]
    back_usage: tuple[tuple[int, int], ...]
    used_back_pairs: frozenset[tuple[int, ...]]
    anchor_front: frozenset[int]
    selected_front_sets: tuple[frozenset[int], ...]
    selected_back_sets: tuple[frozenset[int], ...]
    used_rotations: frozenset[int]


def _zone_seed(seed: SeedContext, zone: str) -> SeedContext:
    base_numbers = list(seed.numbers or [8])
    if zone == "front":
        numbers = base_numbers + [35, 5, (sum(base_numbers) % 10)]
    else:
        numbers = list(reversed(base_numbers)) + [12, 2, ((sum(base_numbers) * 3) % 10)]
    return SeedContext(
        mode=seed.mode,
        seed_value=seed.seed_value,
        numbers=numbers,
        divination_datetime=seed.divination_datetime,
        target_draw_datetime=seed.target_draw_datetime,
    )


def _line_to_trigram(lines: list[int]) -> tuple[int, dict]:
    for idx, trigram in TRIGRAMS.items():
        if trigram["lines"] == lines:
            return idx, trigram
    raise ValueError(f"Unknown trigram lines: {lines}")


def _build_hexagram(lines: list[int]) -> HexagramInfo:
    lower_lines = lines[:3]
    upper_lines = lines[3:]
    _, lower = _line_to_trigram(lower_lines)
    _, upper = _line_to_trigram(upper_lines)
    code = "".join(str(value) for value in lines)
    element = Counter([upper["element"], lower["element"]]).most_common(1)[0][0]
    return HexagramInfo(
        code=code,
        name=HEXAGRAM_NAMES.get(code, "Unknown Hexagram"),
        upper_trigram=upper["name"],
        lower_trigram=lower["name"],
        element=element,
        lines=lines,
    )


def _parse_seed_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _normalize_seed_datetime(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0, tzinfo=None)


def _format_seed_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def _next_draw_date_after(reference: date) -> date:
    candidate = reference + timedelta(days=1)
    while candidate.weekday() not in DRAW_WEEKDAYS:
        candidate += timedelta(days=1)
    return candidate


def _resolve_target_draw_datetime(history: list, target_draw_date: date | None) -> datetime:
    if target_draw_date is not None:
        resolved_date = target_draw_date
    else:
        draw_dates = [item.draw_date for item in history if getattr(item, "draw_date", None)]
        if draw_dates:
            resolved_date = _next_draw_date_after(max(draw_dates))
        else:
            resolved_date = date.today()
            if resolved_date.weekday() not in DRAW_WEEKDAYS:
                resolved_date = _next_draw_date_after(resolved_date - timedelta(days=1))
    return datetime.combine(resolved_date, DIVINATION_DRAW_TIME)


def _seed_from_request(
    issue: str | None,
    timestamp: str | None,
    target_draw_datetime: datetime | None = None,
) -> SeedContext:
    divination_dt = _normalize_seed_datetime(_parse_seed_timestamp(timestamp) if timestamp else datetime.now())
    draw_dt = _normalize_seed_datetime(target_draw_datetime or datetime.combine(divination_dt.date(), DIVINATION_DRAW_TIME))
    issue_numbers = [int(ch) for ch in issue if ch.isdigit()] if issue else []
    numbers = issue_numbers + [
        divination_dt.year,
        divination_dt.month,
        divination_dt.day,
        divination_dt.hour,
        divination_dt.minute,
        draw_dt.year,
        draw_dt.month,
        draw_dt.day,
        draw_dt.hour,
        draw_dt.minute,
    ]
    if issue:
        return SeedContext(
            mode="issue",
            seed_value=issue,
            numbers=numbers,
            divination_datetime=divination_dt,
            target_draw_datetime=draw_dt,
        )
    if timestamp:
        return SeedContext(
            mode="timestamp",
            seed_value=divination_dt.isoformat(timespec="minutes"),
            numbers=numbers,
            divination_datetime=divination_dt,
            target_draw_datetime=draw_dt,
        )
    return SeedContext(
        mode="system_time",
        seed_value=divination_dt.isoformat(timespec="minutes"),
        numbers=numbers,
        divination_datetime=divination_dt,
        target_draw_datetime=draw_dt,
    )


def _derive_hexagrams(seed: SeedContext) -> DerivedHexagrams:
    nums = seed.numbers or [8]
    upper_num = (sum(nums[::2]) % 8) or 8
    lower_num = (sum(nums[1::2]) % 8) or 8
    moving_line = (sum(nums) % 6) or 6
    main_lines = TRIGRAMS[lower_num]["lines"] + TRIGRAMS[upper_num]["lines"]
    mutual_lines = main_lines[1:4] + main_lines[2:5]
    changed_lines = main_lines.copy()
    changed_lines[moving_line - 1] = 0 if changed_lines[moving_line - 1] else 1
    return DerivedHexagrams(
        main=_build_hexagram(main_lines),
        mutual=_build_hexagram(mutual_lines),
        changed=_build_hexagram(changed_lines),
        moving_line=moving_line,
        upper_num=upper_num,
        lower_num=lower_num,
    )


def _build_tail_weights(active_elements: list[str], derived: DerivedHexagrams) -> dict[int, float]:
    weights = {tail: 0.0 for tail in range(10)}
    for digit in ELEMENT_DIGITS[active_elements[0]]:
        weights[digit] += 1.0
    for digit in ELEMENT_DIGITS[active_elements[1]]:
        weights[digit] += 0.7
    for digit in ELEMENT_DIGITS[active_elements[2]]:
        weights[digit] += 0.55
    for digit in ELEMENT_DIGITS[ELEMENT_GENERATES[active_elements[0]]]:
        weights[digit] += 0.35
    for digit in {derived.upper_num % 10, derived.lower_num % 10, derived.moving_line % 10}:
        weights[digit] += 0.2
    return weights


def _merge_tail_weights(front_weights: dict[int, float], back_weights: dict[int, float]) -> dict[int, float]:
    merged: dict[int, float] = {}
    for tail in range(10):
        merged[tail] = round(front_weights.get(tail, 0.0) * 0.7 + back_weights.get(tail, 0.0) * 0.3, 4)
    return merged


def _tail_weight_items(weights: dict[int, float]) -> list[TailWeightItem]:
    return [
        TailWeightItem(tail=tail, weight=round(weight, 2))
        for tail, weight in sorted(weights.items(), key=lambda item: (-item[1], item[0]))
    ]


def _recent_hits(draws: list, *, zone: str, lookback: int = 30) -> dict[int, int]:
    pool = range(1, 36) if zone == "front" else range(1, 13)
    hits = {number: 0 for number in pool}
    for draw in draws[:lookback]:
        values = draw.front_numbers if zone == "front" else draw.back_numbers
        for number in values:
            hits[number] += 1
    return hits


def _window_hits(draws: list, *, zone: str) -> dict[int, dict[int, int]]:
    pool = range(1, 36) if zone == "front" else range(1, 13)
    hits_by_window: dict[int, dict[int, int]] = {}
    for window_size, _weight in MULTI_COVER_SUPERVISED_WINDOWS:
        hits = {number: 0 for number in pool}
        for draw in draws[:window_size]:
            values = draw.front_numbers if zone == "front" else draw.back_numbers
            for number in values:
                hits[number] += 1
        hits_by_window[window_size] = hits
    return hits_by_window


def _zone_pick_count(pool: range) -> int:
    return 5 if len(pool) == 35 else 2


def _normalize_ratio_band(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    if low <= value <= high:
        mid = (low + high) / 2
        half = (high - low) / 2
        return 1.0 if half <= 0 else max(0.0, 1 - abs(value - mid) / half)
    if value < low:
        return max(0.0, 1 - (low - value) / max(high - low, 1e-9))
    return max(0.0, 1 - (value - high) / max(high - low, 1e-9))


def _relative_feature_signal(value: float, expected: float, *, low_ratio: float, high_ratio: float) -> float:
    if expected <= 0:
        return 0.0
    return _normalize_ratio_band(value / expected, low_ratio, high_ratio)


def build_history_feature_context(history: list) -> PrecomputedHistoryFeatures:
    analytics = build_analytics(history)
    return PrecomputedHistoryFeatures(
        history_size=len(history),
        front_frequency={item.number: item.count for item in analytics.front_frequency},
        back_frequency={item.number: item.count for item in analytics.back_frequency},
        front_omission={item.number: item.omission for item in analytics.front_omission},
        back_omission={item.number: item.omission for item in analytics.back_omission},
        front_recent_hits=_recent_hits(history, zone="front", lookback=30),
        back_recent_hits=_recent_hits(history, zone="back", lookback=30),
        front_window_hits=_window_hits(history, zone="front"),
        back_window_hits=_window_hits(history, zone="back"),
    )


def _multi_window_candidate_signals(
    *,
    number: int,
    pool: range,
    pick_count: int,
    history_size: int,
    window_hits: dict[int, dict[int, int]] | None,
) -> tuple[float, float, float]:
    if not window_hits or history_size <= 0 or not pool:
        return 0.0, 0.0, 0.0

    blended_signal = 0.0
    underhit_signal = 0.0
    weight_total = 0.0
    ratios: list[float] = []
    pool_size = len(pool)

    for window_size, weight in MULTI_COVER_SUPERVISED_WINDOWS:
        observed_map = window_hits.get(window_size)
        if not observed_map:
            continue
        effective_window = min(window_size, history_size)
        expected_hits = effective_window * pick_count / pool_size
        if expected_hits <= 0:
            continue
        observed_hits = observed_map.get(number, 0)
        ratio = observed_hits / expected_hits
        ratios.append(ratio)
        if window_size <= 12:
            low_ratio, high_ratio = 0.70, 1.12
        elif window_size <= 36:
            low_ratio, high_ratio = 0.76, 1.10
        else:
            low_ratio, high_ratio = 0.82, 1.08
        blended_signal += _normalize_ratio_band(ratio, low_ratio, high_ratio) * weight
        underhit_signal += _normalize_ratio_band(ratio, 0.72, 0.98) * weight
        weight_total += weight

    if weight_total <= 0:
        return 0.0, 0.0, 0.0

    blended_signal /= weight_total
    underhit_signal /= weight_total
    ratio_avg = sum(ratios) / len(ratios) if ratios else 1.0
    ratio_range = (max(ratios) - min(ratios)) if len(ratios) > 1 else 0.0
    consistency_signal = max(0.0, 1 - ratio_range / 1.05)
    moderate_ratio_signal = _normalize_ratio_band(ratio_avg, 0.78, 1.04)
    stability_signal = round(consistency_signal * 0.55 + moderate_ratio_signal * 0.45, 4)
    return round(blended_signal, 4), stability_signal, round(underhit_signal, 4)


def _score_candidates(
    pool: range,
    tail_weights: dict[int, float],
    omission_map: dict[int, int],
    frequency_map: dict[int, int],
    recent_hits: dict[int, int],
    score_weights: dict[str, float] | None = None,
    *,
    history_size: int | None = None,
    window_hits: dict[int, dict[int, int]] | None = None,
) -> list[CandidateBreakdown]:
    weights = score_weights or DEFAULT_SCORE_WEIGHTS
    expected_frequency = (sum(frequency_map.values()) / len(pool)) if pool else 1.0
    expected_recent_hits = (sum(recent_hits.values()) / len(pool)) if pool else 1.0
    pick_count = _zone_pick_count(pool)
    expected_omission = (len(pool) - pick_count) / pick_count
    max_tail_weight = max(tail_weights.values()) or 1
    scored: list[CandidateBreakdown] = []
    for number in pool:
        tail = number % 10
        tail_weight = round(tail_weights.get(tail, 0.0), 2)
        omission_signal = _relative_feature_signal(
            omission_map[number],
            expected_omission,
            low_ratio=0.7,
            high_ratio=1.7,
        )
        frequency_signal = _relative_feature_signal(
            frequency_map[number],
            expected_frequency,
            low_ratio=0.85,
            high_ratio=1.15,
        )
        recent_signal = _relative_feature_signal(
            recent_hits[number],
            expected_recent_hits,
            low_ratio=0.55,
            high_ratio=1.15,
        )
        if history_size and window_hits:
            window_signal, stability_signal, underhit_signal = _multi_window_candidate_signals(
                number=number,
                pool=pool,
                pick_count=pick_count,
                history_size=history_size,
                window_hits=window_hits,
            )
            omission_signal = round(omission_signal * 0.84 + underhit_signal * 0.16, 4)
            frequency_signal = round(
                frequency_signal * 0.58 + window_signal * 0.27 + stability_signal * 0.15,
                4,
            )
            recent_signal = round(
                recent_signal * 0.50 + window_signal * 0.32 + underhit_signal * 0.18,
                4,
            )
        # Candidate scoring now prefers numbers near the zone-level expectation
        # with a slight under-hit allowance, instead of blindly chasing the coldest tail.
        score = round(
            weights["tail"] * (tail_weight / max_tail_weight)
            + weights["omission"] * omission_signal
            + weights["frequency"] * frequency_signal
            + weights["recent_hits"] * recent_signal,
            4,
        )
        scored.append(
            CandidateBreakdown(
                number=number,
                score=score,
                tail=tail,
                tail_weight=tail_weight,
                omission=omission_map[number],
                frequency=frequency_map[number],
                recent_hits=recent_hits[number],
                selected=False,
            )
        )
    scored.sort(key=lambda item: (-item.score, item.number))
    return scored


def _pick_recommendations(
    candidates: list[CandidateBreakdown], count: int
) -> tuple[list[RecommendationNumber], list[CandidateBreakdown]]:
    selected_numbers = {item.number for item in candidates[:count]}
    recommendations: list[RecommendationNumber] = []
    details: list[CandidateBreakdown] = []
    for item in candidates:
        selected = item.number in selected_numbers
        details.append(item.model_copy(update={"selected": selected}))
        if selected:
            recommendations.append(
                RecommendationNumber(
                    number=item.number,
                    score=item.score,
                    reason=(
                        f"\u6309\u4e00\u7b49\u5956\u76ee\u6807\u7ed3\u6784\u63a8\u6f14\uff1a"
                        f"\u5c3e\u6570 {item.tail} \u6743\u91cd {item.tail_weight:.2f}\uff0c"
                        f"\u9057\u6f0f {item.omission}\uff0c\u5386\u53f2\u9891\u6b21 {item.frequency}\uff0c"
                        f"\u8fd130\u671f\u547d\u4e2d {item.recent_hits}"
                    ),
                )
            )
    return recommendations, details


def _odd_even_ratio(numbers: list[int]) -> str:
    odd = sum(1 for number in numbers if number % 2 == 1)
    return f"{odd}:{len(numbers) - odd}"


def _display_elements(active_elements: list[str]) -> list[str]:
    return [ELEMENT_LABELS.get(element, element) for element in active_elements]


def _build_summary(
    front_numbers: list[int], back_numbers: list[int], favored_tails: list[int], active_elements: list[str]
) -> RecommendationSummary:
    display_elements = _display_elements(active_elements)
    return RecommendationSummary(
        front_sum=sum(front_numbers),
        back_sum=sum(back_numbers),
        front_span=max(front_numbers) - min(front_numbers),
        back_span=max(back_numbers) - min(back_numbers),
        front_odd_even=_odd_even_ratio(front_numbers),
        back_odd_even=_odd_even_ratio(back_numbers),
        favored_tails=favored_tails,
        explanation=(
            f"\u672c\u6b21\u4ecd\u4ee5\u4e00\u7b49\u5956\u76ee\u6807\u4e3a\u63a8\u6f14\u53e3\u5f84\uff0c"
            "\u4f46\u524d\u533a 35 \u9009 5 \u4e0e\u540e\u533a 12 \u9009 2 \u5df2\u6309\u4e24\u4e2a\u6295\u653e\u7bb1\u5206\u5f00\u5efa\u6a21\u3002"
            f"\u524d\u540e\u533a\u5366\u8c61\u4fe1\u53f7\u7efc\u5408\u540e\u6fc0\u6d3b\u4e86 {', '.join(display_elements)} \u8fd9\u7ec4\u4e94\u884c\u503e\u5411\uff0c"
            f"\u5f53\u671f\u7efc\u5408\u4f18\u5148\u5c3e\u6570\u4e3a {', '.join(str(value) for value in favored_tails)}\uff0c"
            "\u518d\u53e0\u52a0\u9057\u6f0f\u3001\u5386\u53f2\u9891\u7387\u548c\u8fd1\u671f\u51b7\u70ed\u7279\u5f81\u8fdb\u884c\u6392\u5e8f\u3002"
        ),
    )


def _scheme_numbers(source: list[CandidateBreakdown], count: int, *, variant: int) -> list[int]:
    """Pick `count` numbers from a pre-sorted candidate list with tail diversification.

    Used for the first scheme (variant=0) — pure top-score core combo.
    For variant>0, applies a re-sort heuristic to provide a baseline alternative.
    """
    pool = list(source[: max(15, count * 5)])
    if variant % 4 == 1:
        pool.sort(key=lambda item: (-item.omission, -item.score, item.number))
    elif variant % 4 == 2:
        pool.sort(key=lambda item: (item.recent_hits, -item.score, item.number))
    elif variant % 4 == 3:
        pool.sort(key=lambda item: (-item.tail_weight, item.recent_hits, item.number))
    else:
        pool.sort(key=lambda item: (-item.score, item.number))

    picked: list[int] = []
    used_tails: set[int] = set()
    for candidate in pool:
        if len(picked) == count:
            break
        if candidate.tail in used_tails and len(used_tails) < count:
            continue
        picked.append(candidate.number)
        used_tails.add(candidate.tail)

    for candidate in pool:
        if len(picked) == count:
            break
        if candidate.number not in picked:
            picked.append(candidate.number)

    return sorted(picked[:count])


def _coverage_pick(
    pool: list[CandidateBreakdown],
    covered: set[int],
    count: int,
) -> list[int]:
    """Greedy diversification: pick `count` numbers preferring ones not yet covered.

    Tie-break by descending score so picked numbers still carry the most information.
    Tails are also diversified to avoid clustering on the same digit family.
    """
    # First, partition: uncovered with high score wins; covered numbers are fallback.
    ranked = sorted(
        pool,
        key=lambda item: (item.number in covered, -item.score, item.number),
    )
    picked: list[int] = []
    used_tails: set[int] = set()
    for candidate in ranked:
        if len(picked) == count:
            break
        if candidate.tail in used_tails and len(used_tails) < count:
            continue
        picked.append(candidate.number)
        used_tails.add(candidate.tail)

    # Fallback if tail-diversification left us short
    for candidate in ranked:
        if len(picked) == count:
            break
        if candidate.number not in picked:
            picked.append(candidate.number)

    return sorted(picked[:count])


def _confidence_from_scores(
    selected_numbers: list[int],
    pool: list[CandidateBreakdown],
) -> float:
    """Confidence = mean score of the selected candidates, mapped into [0.45, 0.92]."""
    score_map = {item.number: item.score for item in pool}
    selected_scores = [score_map[n] for n in selected_numbers if n in score_map]
    if not selected_scores:
        return 0.45
    avg = sum(selected_scores) / len(selected_scores)
    # Candidate scores are in [0,1] by construction; re-map to a calibrated band.
    return round(0.45 + max(0.0, min(1.0, avg)) * (0.92 - 0.45), 2)


def _normalize_band(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    if low <= value <= high:
        mid = (low + high) / 2
        half = (high - low) / 2
        return 1.0 if half <= 0 else max(0.0, 1 - abs(value - mid) / half)
    if value < low:
        return max(0.0, 1 - (low - value) / max(high - low, 1))
    return max(0.0, 1 - (value - high) / max(high - low, 1))


def _combination_structure_score(numbers: list[int], *, zone: str) -> float:
    return _combination_structure_score_cached(tuple(sorted(numbers)), zone)


@lru_cache(maxsize=8192)
def _combination_structure_score_cached(numbers_key: tuple[int, ...], zone: str) -> float:
    values = list(numbers_key)
    total = sum(values)
    span = values[-1] - values[0]
    odd = sum(1 for number in values if number % 2 == 1)
    unique_tails = len({number % 10 for number in values})
    consecutive_pairs = sum(1 for index in range(1, len(values)) if values[index] - values[index - 1] == 1)

    if zone == "front":
        zone_split = [0, 0, 0]
        for value in values:
            if value <= 12:
                zone_split[0] += 1
            elif value <= 24:
                zone_split[1] += 1
            else:
                zone_split[2] += 1
        zone_balance = 1 - (max(zone_split) - min(zone_split)) / 5
        odd_even_balance = 1 - abs(odd - 2.5) / 2.5
        sum_score = _normalize_band(total, 75, 125)
        span_score = _normalize_band(span, 16, 30)
        tail_score = unique_tails / 5
        consecutive_score = 1 - min(consecutive_pairs, 3) / 3
        return max(
            0.0,
            min(
                1.0,
                0.28 * sum_score
                + 0.22 * span_score
                + 0.20 * odd_even_balance
                + 0.18 * zone_balance
                + 0.08 * tail_score
                + 0.04 * consecutive_score,
            ),
        )

    odd_even_balance = 1 - abs(odd - 1) / 1
    sum_score = _normalize_band(total, 7, 17)
    span_score = _normalize_band(span, 2, 8)
    tail_score = unique_tails / 2
    consecutive_score = 1 - min(consecutive_pairs, 1)
    return max(
        0.0,
        min(1.0, 0.38 * sum_score + 0.26 * span_score + 0.20 * odd_even_balance + 0.10 * tail_score + 0.06 * consecutive_score),
    )


def _front_jackpot_pattern_bonus(numbers: list[int]) -> float:
    return _front_jackpot_pattern_bonus_cached(tuple(sorted(numbers)))


@lru_cache(maxsize=8192)
def _front_jackpot_pattern_bonus_cached(numbers_key: tuple[int, ...]) -> float:
    values = list(numbers_key)
    total = sum(values)
    span = values[-1] - values[0]
    odd = sum(1 for number in values if number % 2 == 1)
    consecutive_pairs = sum(1 for index in range(1, len(values)) if values[index] - values[index - 1] == 1)
    tail_counts = Counter(number % 10 for number in values)
    repeated_tails = sum(max(0, count - 1) for count in tail_counts.values())
    zone_low = sum(1 for number in values if number <= 12)
    zone_mid = sum(1 for number in values if 13 <= number <= 24)
    zone_high = len(values) - zone_low - zone_mid

    sum_score = max(0.0, 1 - abs(total - 86) / 24)
    span_score = max(0.0, 1 - abs(span - 25) / 12)
    odd_score = max(0.0, 1 - abs(odd - 3) / 2)
    zone_low_score = max(0.0, 1 - abs(zone_low - 2) / 2)
    zone_mid_score = max(0.0, 1 - abs(zone_mid - 1.5) / 2.5)
    zone_high_score = max(0.0, 1 - abs(zone_high - 1.5) / 2.5)
    imbalance_score = max(0.0, 1 - (max(zone_low, zone_mid, zone_high) - min(zone_low, zone_mid, zone_high)) / 4)
    repeat_score = 1.0 if repeated_tails == 1 else (0.7 if repeated_tails == 0 else 0.4)
    no_consecutive_score = 1 - min(consecutive_pairs, 3) / 3
    return round(
        0.22 * sum_score
        + 0.22 * span_score
        + 0.12 * odd_score
        + 0.18 * zone_low_score
        + 0.12 * zone_mid_score
        + 0.06 * zone_high_score
        + 0.04 * imbalance_score
        + 0.04 * repeat_score
        + 0.04 * no_consecutive_score,
        4,
    )


def _combo_score(
    numbers: list[int],
    *,
    zone: str,
    score_map: dict[int, float],
    combo_weights: dict[str, float] | None = None,
) -> float:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    numbers_key = tuple(sorted(numbers))
    combo_score = _combo_score_from_key(
        numbers_key,
        zone=zone,
        score_map=score_map,
        candidate_weight=weights["candidate"],
        structure_weight=weights["structure"],
        front_jackpot_pattern_weight=weights.get("front_jackpot_pattern", 0.0),
    )
    return round(combo_score, 4)


def _combo_score_from_key(
    numbers_key: tuple[int, ...],
    *,
    zone: str,
    score_map: dict[int, float],
    candidate_weight: float,
    structure_weight: float,
    front_jackpot_pattern_weight: float = 0.0,
) -> float:
    candidate_score = sum(score_map[number] for number in numbers_key) / len(numbers_key)
    structure_score = _combination_structure_score_cached(numbers_key, zone)
    combo_score = candidate_weight * candidate_score + structure_weight * structure_score
    if zone == "front" and front_jackpot_pattern_weight > 0:
        combo_score += front_jackpot_pattern_weight * _front_jackpot_pattern_bonus_cached(numbers_key)
    return round(combo_score, 4)


def _top_number_pool(
    source: list[CandidateBreakdown],
    *,
    pick_count: int,
    strategy_mode: str,
    zone: str,
    combo_weights: dict[str, float] | None = None,
    search_profile: str = "full",
) -> list[int]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    if zone == "front":
        if search_profile == "coarse":
            limit = 9 if strategy_mode == "single_hit" else 10
        elif search_profile == "deep_single_hit":
            limit = 17 if strategy_mode == "single_hit" else 16
        elif search_profile == "tuning":
            limit = 11 if strategy_mode == "single_hit" else 12
        else:
            limit = 14 if strategy_mode == "single_hit" else 16
    else:
        if search_profile == "coarse":
            limit = 5
        elif search_profile == "deep_single_hit":
            limit = 9 if strategy_mode == "single_hit" else 9
        elif search_profile == "tuning":
            limit = 7
        else:
            limit = 8 if strategy_mode == "single_hit" else 9
    boost_key = "front_pool_boost" if zone == "front" else "back_pool_boost"
    boost = int(max(0, round(weights.get(boost_key, 0.0))))
    if boost > 0:
        if search_profile == "coarse":
            boost = min(boost, 1)
        elif search_profile == "tuning":
            boost = min(boost, 2 if zone == "front" else 1)
        elif search_profile == "deep_single_hit":
            boost = min(boost, 3 if zone == "front" else 2)
        limit += boost
    limit = max(pick_count + 3, min(limit, len(source)))
    return [item.number for item in source[:limit]]


def _enumerate_scored_combinations(
    source: list[CandidateBreakdown],
    *,
    pick_count: int,
    strategy_mode: str,
    zone: str,
    combo_weights: dict[str, float] | None = None,
    search_profile: str = "full",
) -> list[tuple[list[int], float]]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    score_map = {item.number: item.score for item in source}
    top_numbers = sorted(
        _top_number_pool(
        source,
        pick_count=pick_count,
        strategy_mode=strategy_mode,
        zone=zone,
        combo_weights=weights,
        search_profile=search_profile,
        )
    )
    candidate_weight = weights["candidate"]
    structure_weight = weights["structure"]
    front_jackpot_pattern_weight = weights.get("front_jackpot_pattern", 0.0)
    combos: list[tuple[list[int], float]] = []
    for combo in combinations(top_numbers, pick_count):
        combos.append(
            (
                list(combo),
                _combo_score_from_key(
                    combo,
                    zone=zone,
                    score_map=score_map,
                    candidate_weight=candidate_weight,
                    structure_weight=structure_weight,
                    front_jackpot_pattern_weight=front_jackpot_pattern_weight,
                ),
            )
        )
    combos.sort(key=lambda item: (-item[1], item[0]))
    return combos


def _cross_scheme_novelty(
    front_numbers: list[int],
    back_numbers: list[int],
    front_covered: set[int],
    back_covered: set[int],
) -> float:
    front_new = len([number for number in front_numbers if number not in front_covered]) / len(front_numbers)
    back_new = len([number for number in back_numbers if number not in back_covered]) / len(back_numbers)
    return front_new * 0.7 + back_new * 0.3


def _ticket_crowd_penalty(front_numbers: list[int], back_numbers: list[int]) -> float:
    return _ticket_crowd_penalty_cached(tuple(sorted(front_numbers)), tuple(sorted(back_numbers)))


@lru_cache(maxsize=32768)
def _ticket_crowd_penalty_cached(front_key: tuple[int, ...], back_key: tuple[int, ...]) -> float:
    front_sorted = list(front_key)
    back_numbers = list(back_key)
    low_bias = max(0.0, (sum(1 for number in front_sorted if number <= 31) - 3) / 2)
    consecutive_pairs = sum(1 for index in range(1, len(front_sorted)) if front_sorted[index] - front_sorted[index - 1] == 1)
    tail_counts = Counter(number % 10 for number in front_sorted)
    repeated_tails = sum(max(0, count - 1) for count in tail_counts.values())
    arithmetic_steps = Counter(
        front_sorted[index] - front_sorted[index - 1]
        for index in range(1, len(front_sorted))
    )
    progression_penalty = 1.0 if arithmetic_steps and arithmetic_steps.most_common(1)[0][1] >= 3 else 0.0
    symmetry_penalty = 1.0 if front_sorted[0] + front_sorted[-1] == front_sorted[1] + front_sorted[-2] else 0.0
    back_low_bias = sum(1 for number in back_numbers if number <= 6) / len(back_numbers)
    penalty = (
        0.20 * low_bias
        + 0.18 * min(consecutive_pairs / 2, 1.0)
        + 0.15 * progression_penalty
        + 0.12 * min(repeated_tails / 3, 1.0)
        + 0.10 * symmetry_penalty
        + 0.08 * back_low_bias
    )
    return round(min(1.0, penalty), 4)


def _build_ticket_selection_context(selected: list[FinalScheme]) -> TicketSelectionContext | None:
    if not selected:
        return None
    selected_front_sets = tuple(frozenset(scheme.front_numbers) for scheme in selected)
    selected_back_sets = tuple(frozenset(scheme.back_numbers) for scheme in selected)
    anchor_front = selected_front_sets[0]
    back_usage_counter = Counter(number for scheme in selected for number in scheme.back_numbers)
    used_rotations = frozenset(
        next(iter(rotation))
        for front_set in selected_front_sets[1:]
        for rotation in [front_set - anchor_front]
        if len(front_set.intersection(anchor_front)) == 4 and len(rotation) == 1
    )
    return TicketSelectionContext(
        front_covered=frozenset(number for scheme in selected for number in scheme.front_numbers),
        back_covered=frozenset(number for scheme in selected for number in scheme.back_numbers),
        back_usage=tuple(sorted(back_usage_counter.items())),
        used_back_pairs=frozenset(tuple(scheme.back_numbers) for scheme in selected),
        anchor_front=anchor_front,
        selected_front_sets=selected_front_sets,
        selected_back_sets=selected_back_sets,
        used_rotations=used_rotations,
    )


def _scheme_search_limits(
    strategy_mode: str,
    search_profile: str,
    combo_weights: dict[str, float] | None = None,
) -> tuple[int, int]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    if search_profile == "coarse":
        front_limit, back_limit = (22, 6) if strategy_mode == "single_hit" else (28, 8)
    elif search_profile == "deep_single_hit":
        front_limit, back_limit = (72, 18) if strategy_mode == "single_hit" else (72, 16)
    elif search_profile == "tuning":
        front_limit, back_limit = (34, 8) if strategy_mode == "single_hit" else (44, 10)
    else:
        front_limit, back_limit = (56, 12) if strategy_mode == "single_hit" else (72, 16)

    front_boost = int(max(0, round(weights.get("front_combo_limit_boost", 0.0))))
    back_boost = int(max(0, round(weights.get("back_combo_limit_boost", 0.0))))
    if search_profile == "coarse":
        front_boost = min(front_boost, 8)
        back_boost = min(back_boost, 2)
    elif search_profile == "tuning":
        front_boost = min(front_boost, 20)
        back_boost = min(back_boost, 4)
    elif search_profile == "deep_single_hit":
        front_boost = min(front_boost, 36)
        back_boost = min(back_boost, 6)

    return front_limit + front_boost, back_limit + back_boost


def _ticket_candidate_budget(
    strategy_mode: str,
    search_profile: str,
    combo_weights: dict[str, float] | None = None,
) -> int:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    if strategy_mode == "single_hit":
        if search_profile == "deep_single_hit":
            budget = 320
        elif search_profile == "tuning":
            budget = 180
        elif search_profile == "coarse":
            budget = 120
        else:
            budget = 220
    elif search_profile == "tuning":
        budget = 280
    else:
        budget = 420

    boost = int(max(0, round(weights.get("ticket_candidate_budget_boost", 0.0))))
    if boost > 0:
        if search_profile == "coarse":
            boost = min(boost, 40)
        elif search_profile == "tuning":
            boost = min(boost, 120)
        elif search_profile == "deep_single_hit":
            boost = min(boost, 180)
        budget += boost
    return budget


def _build_ticket_candidates(
    front_candidates: list[CandidateBreakdown],
    back_candidates: list[CandidateBreakdown],
    *,
    strategy_mode: str,
    combo_weights: dict[str, float] | None = None,
    search_profile: str = "full",
) -> list[TicketCandidate]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    front_combos = _enumerate_scored_combinations(
        front_candidates,
        pick_count=5,
        strategy_mode=strategy_mode,
        zone="front",
        combo_weights=weights,
        search_profile=search_profile,
    )
    back_combos = _enumerate_scored_combinations(
        back_candidates,
        pick_count=2,
        strategy_mode=strategy_mode,
        zone="back",
        combo_weights=weights,
        search_profile=search_profile,
    )
    front_limit, back_limit = _scheme_search_limits(strategy_mode, search_profile, combo_weights=weights)
    ticket_candidates: list[TicketCandidate] = []
    for front_numbers, front_score in front_combos[:front_limit]:
        for back_numbers, back_score in back_combos[:back_limit]:
            ticket_candidates.append(
                TicketCandidate(
                    front_numbers=tuple(front_numbers),
                    back_numbers=tuple(back_numbers),
                    front_set=frozenset(front_numbers),
                    back_set=frozenset(back_numbers),
                    front_score=front_score,
                    back_score=back_score,
                    base_score=round(front_score * weights["pair_front"] + back_score * weights["pair_back"], 4),
                    crowd_penalty=_ticket_crowd_penalty(front_numbers, back_numbers),
                )
            )
    ticket_candidates.sort(
        key=lambda item: (
            -item.base_score,
            item.crowd_penalty,
            item.front_numbers,
            item.back_numbers,
        )
    )
    return ticket_candidates[: _ticket_candidate_budget(strategy_mode, search_profile, combo_weights=weights)]


def _ticket_selection_score(
    candidate: TicketCandidate,
    selected: list[FinalScheme],
    *,
    strategy_mode: str,
    combo_weights: dict[str, float] | None = None,
    selection_context: TicketSelectionContext | None = None,
) -> float:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    if not selected:
        return round(candidate.base_score - candidate.crowd_penalty * weights["crowd_penalty"], 4)

    context = selection_context or _build_ticket_selection_context(selected)
    if context is None:
        return round(candidate.base_score - candidate.crowd_penalty * weights["crowd_penalty"], 4)

    back_usage = dict(context.back_usage)
    novelty = _cross_scheme_novelty(
        list(candidate.front_numbers),
        list(candidate.back_numbers),
        set(context.front_covered),
        set(context.back_covered),
    )
    front_overlap_penalty = sum(
        len(candidate.front_set.intersection(front_set)) ** 2
        for front_set in context.selected_front_sets
    )
    back_overlap_penalty = sum(
        len(candidate.back_set.intersection(back_set)) ** 2
        for back_set in context.selected_back_sets
    )
    back_pair_penalty = 1.0 if candidate.back_numbers in context.used_back_pairs else 0.0
    back_usage_penalty = sum(back_usage.get(number, 0) for number in candidate.back_numbers)
    fresh_back_bonus = sum(1 for number in candidate.back_numbers if number not in context.back_covered) / len(candidate.back_numbers)
    anchor_overlap = len(candidate.front_set.intersection(context.anchor_front))
    anchor_rotation_bonus = 0.0
    anchor_rotation_penalty = 0.0
    anchor_deviation_penalty = 0.0
    high_tier_anchor_enabled = (
        weights.get("jackpot_front_core", 0.0) >= 0.5
        or weights.get("front_wheel_mode", 0.0) >= 0.5
        or weights.get("front_anchor_repeat_mode", 0.0) >= 0.5
    )
    if strategy_mode == "multi_cover" and high_tier_anchor_enabled:
        rotated_numbers = candidate.front_set - context.anchor_front
        if anchor_overlap == 4 and len(rotated_numbers) == 1:
            anchor_rotation_bonus = 0.38 + fresh_back_bonus * 0.08
            front_overlap_penalty *= 0.2
            rotation_number = next(iter(rotated_numbers))
            if rotation_number in context.used_rotations:
                anchor_rotation_penalty = 0.08
        elif anchor_overlap == 3:
            anchor_rotation_bonus = 0.05
        elif anchor_overlap <= 2:
            anchor_deviation_penalty = 0.12
        elif anchor_overlap == 5:
            anchor_rotation_bonus = 0.02
            anchor_rotation_penalty = 0.14

    if strategy_mode == "single_hit":
        score = (
            candidate.base_score * weights["single_hit_pair"]
            + novelty * weights["single_hit_novelty"]
            + fresh_back_bonus * (weights["fresh_back_bonus"] * 0.45)
            - front_overlap_penalty * (weights["overlap_front"] * 0.22)
            - back_overlap_penalty * (weights["overlap_back"] * 0.30)
            - back_pair_penalty * (weights["same_back_pair_penalty"] * 0.25)
            - back_usage_penalty * (weights["back_usage_penalty"] * 0.12)
            - candidate.crowd_penalty * (weights["crowd_penalty"] * 0.35)
        )
    else:
        score = (
            candidate.base_score * weights["multi_cover_pair"]
            + novelty * weights["multi_cover_novelty"]
            + fresh_back_bonus * weights["fresh_back_bonus"]
            + anchor_rotation_bonus
            - front_overlap_penalty * weights["overlap_front"]
            - back_overlap_penalty * weights["overlap_back"]
            - back_pair_penalty * weights["same_back_pair_penalty"]
            - back_usage_penalty * weights["back_usage_penalty"]
            - anchor_rotation_penalty
            - anchor_deviation_penalty
            - candidate.crowd_penalty * weights["crowd_penalty"]
        )
    return round(score, 4)


def _number_window_rate(draws: list, *, zone: str) -> dict[int, float]:
    if not draws:
        return {}
    pool = range(1, 36) if zone == "front" else range(1, 13)
    counts = {number: 0 for number in pool}
    for draw in draws:
        values = draw.front_numbers if zone == "front" else draw.back_numbers
        for number in values:
            counts[number] += 1
    total = len(draws)
    return {number: counts[number] / total for number in pool}


def _back_pair_window_rate(draws: list) -> dict[tuple[int, int], float]:
    if not draws:
        return {}
    counts: dict[tuple[int, int], int] = {}
    for draw in draws:
        pair = tuple(sorted(draw.back_numbers))
        counts[pair] = counts.get(pair, 0) + 1
    total = len(draws)
    return {pair: count / total for pair, count in counts.items()}


def _build_multi_cover_supervised_windows(
    history_desc: list,
) -> list[tuple[float, dict[int, float], dict[int, float], dict[tuple[int, int], float]]]:
    windows: list[tuple[float, dict[int, float], dict[int, float], dict[tuple[int, int], float]]] = []
    for window_size, weight in MULTI_COVER_SUPERVISED_WINDOWS:
        window_draws = history_desc[:window_size]
        if not window_draws:
            continue
        windows.append(
            (
                weight,
                _number_window_rate(window_draws, zone="front"),
                _number_window_rate(window_draws, zone="back"),
                _back_pair_window_rate(window_draws),
            )
        )
    return windows


def _ticket_supervised_signals(
    candidate: TicketCandidate,
    supervised_windows: list[tuple[float, dict[int, float], dict[int, float], dict[tuple[int, int], float]]],
) -> tuple[float, float, float]:
    front_signal = 0.0
    back_signal = 0.0
    back_pair_signal = 0.0
    for weight, front_rates, back_rates, back_pair_rates in supervised_windows:
        front_signal += sum(front_rates.get(number, 0.0) for number in candidate.front_numbers) / len(candidate.front_numbers) * weight
        back_signal += sum(back_rates.get(number, 0.0) for number in candidate.back_numbers) / len(candidate.back_numbers) * weight
        back_pair_signal += back_pair_rates.get(tuple(sorted(candidate.back_numbers)), 0.0) * weight
    return round(front_signal, 4), round(back_signal, 4), round(back_pair_signal, 4)


def _floor_harvest_bonus(
    candidate: TicketCandidate,
    supervised_windows: list[tuple[float, dict[int, float], dict[int, float], dict[tuple[int, int], float]]],
) -> float:
    front_signal, back_signal, back_pair_signal = _ticket_supervised_signals(candidate, supervised_windows)
    back_low_bias = sum(1 for number in candidate.back_numbers if number <= 6) / len(candidate.back_numbers)
    back_sum_penalty = sum(candidate.back_numbers) / 24.0
    front_floor_signal = min(front_signal, 0.22) / 0.22
    back_floor_signal = min(back_signal, 0.18) / 0.18
    bonus = (
        back_signal * 1.70
        + back_pair_signal * 0.65
        + back_low_bias * 0.24
        + front_signal * 0.14
        + min(front_floor_signal, back_floor_signal) * 0.08
        - back_sum_penalty * 0.04
    )
    return round(bonus, 4)


def _scheme_from_ticket_candidate(
    candidate: TicketCandidate,
    *,
    index: int,
    front_candidates: list[CandidateBreakdown],
    back_candidates: list[CandidateBreakdown],
    strategy: str,
    rationale: str,
) -> FinalScheme:
    front_numbers = list(candidate.front_numbers)
    back_numbers = list(candidate.back_numbers)
    label = SCHEME_STYLES[index] if index < len(SCHEME_STYLES) else f"Scheme {index + 1}"
    confidence_front = _confidence_from_scores(front_numbers, front_candidates)
    confidence_back = _confidence_from_scores(back_numbers, back_candidates)
    confidence = round(min(0.98, max(candidate.base_score, confidence_front * 0.7 + confidence_back * 0.3)), 2)
    return FinalScheme(
        label=label,
        confidence=confidence,
        strategy=strategy,
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        rationale=rationale,
    )


def _apply_floor_harvest_schemes(
    base_schemes: list[FinalScheme],
    *,
    history_desc: list,
    front_candidates: list[CandidateBreakdown],
    back_candidates: list[CandidateBreakdown],
    combo_weights: dict[str, float] | None = None,
    search_profile: str = "full",
) -> list[FinalScheme]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    harvest_slots = int(max(0, round(weights.get("floor_harvest_slots", 0.0))))
    if harvest_slots <= 0 or len(base_schemes) < 4 or not history_desc:
        return base_schemes

    supervised_windows = _build_multi_cover_supervised_windows(history_desc)
    if not supervised_windows:
        return base_schemes

    ticket_candidates = _build_ticket_candidates(
        front_candidates,
        back_candidates,
        strategy_mode="multi_cover",
        combo_weights=weights,
        search_profile=search_profile,
    )
    if not ticket_candidates:
        return base_schemes

    harvest_slots = min(harvest_slots, max(1, len(base_schemes) - 1))
    keep_count = max(1, len(base_schemes) - harvest_slots)
    protected = list(base_schemes[:keep_count])
    used_keys = {(tuple(item.front_numbers), tuple(item.back_numbers)) for item in protected}
    rebuilt: list[FinalScheme] = list(protected)

    for _ in range(harvest_slots):
        selection_context = _build_ticket_selection_context(rebuilt)
        chosen: TicketCandidate | None = None
        chosen_score = float("-inf")
        for candidate in ticket_candidates:
            key = (candidate.front_numbers, candidate.back_numbers)
            if key in used_keys:
                continue
            if _violates_multi_cover_overlap_guard(candidate, rebuilt):
                continue
            selection_score = _ticket_selection_score(
                candidate,
                rebuilt,
                strategy_mode="multi_cover",
                combo_weights=weights,
                selection_context=selection_context,
            )
            selection_score += _floor_harvest_bonus(candidate, supervised_windows)
            if selection_score > chosen_score:
                chosen = candidate
                chosen_score = selection_score
        if chosen is None:
            break
        rebuilt.append(
            _scheme_from_ticket_candidate(
                chosen,
                index=len(rebuilt),
                front_candidates=front_candidates,
                back_candidates=back_candidates,
                strategy=(
                    f"第 {len(rebuilt) + 1} 组偏向低奖兜底："
                    "保留前三组强前区主核，末位票改为后区命中率优先，"
                    "尽量补齐七等奖到五等奖的稳定落点。"
                ),
                rationale=(
                    "以近窗后区出现率、后区对子频率与低位后区覆盖为主做二次筛票，"
                    "只在不破坏前面核心票的前提下替换末位方案，"
                    "把宽搜索候选池里更容易兑现的小奖票拉进最终 5 张。"
                ),
            )
        )
        used_keys.add((chosen.front_numbers, chosen.back_numbers))

    if len(rebuilt) < len(base_schemes):
        for scheme in base_schemes[keep_count:]:
            key = (tuple(scheme.front_numbers), tuple(scheme.back_numbers))
            if key in used_keys:
                continue
            rebuilt.append(scheme)
            used_keys.add(key)
            if len(rebuilt) >= len(base_schemes):
                break

    relabeled: list[FinalScheme] = []
    for index, scheme in enumerate(rebuilt[: len(base_schemes)]):
        label = SCHEME_STYLES[index] if index < len(SCHEME_STYLES) else f"Scheme {index + 1}"
        relabeled.append(scheme.model_copy(update={"label": label}))
    return relabeled


def _apply_mid_front_probe_schemes(
    base_schemes: list[FinalScheme],
    ticket_candidates: list[TicketCandidate],
    *,
    front_candidates: list[CandidateBreakdown],
    back_candidates: list[CandidateBreakdown],
    combo_weights: dict[str, float] | None = None,
) -> list[FinalScheme]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    probe_slots = int(max(0, round(weights.get("jackpot_probe_slots", 0.0))))
    if probe_slots <= 0 or len(base_schemes) < 4 or not ticket_candidates:
        return base_schemes

    probe_slots = min(probe_slots, max(0, len(base_schemes) - 3))
    if probe_slots <= 0:
        return base_schemes

    rank_pool = ticket_candidates[: min(120, len(ticket_candidates))]
    if not rank_pool:
        return base_schemes

    ranked_front = sorted(
        rank_pool,
        key=lambda item: (
            -item.front_score,
            -item.base_score,
            item.crowd_penalty,
            item.front_numbers,
            item.back_numbers,
        ),
    )
    rank_low = int(max(1, round(weights.get("jackpot_probe_front_rank_low", 20.0))))
    rank_high = int(max(rank_low, round(weights.get("jackpot_probe_front_rank_high", 80.0))))
    rank_low = min(rank_low, len(ranked_front))
    rank_high = min(rank_high, len(ranked_front))

    keep_count = len(base_schemes) - probe_slots
    protected = list(base_schemes[:keep_count])
    used_keys = {(tuple(item.front_numbers), tuple(item.back_numbers)) for item in protected}

    probe_schemes: list[FinalScheme] = []
    for rank_index, candidate in enumerate(ranked_front, start=1):
        if rank_index < rank_low or rank_index > rank_high:
            continue
        key = (candidate.front_numbers, candidate.back_numbers)
        if key in used_keys:
            continue
        probe_schemes.append(
            _scheme_from_ticket_candidate(
                candidate,
                index=keep_count + len(probe_schemes),
                front_candidates=front_candidates,
                back_candidates=back_candidates,
                strategy=(
                    f"第 {keep_count + len(probe_schemes) + 1} 组作为头奖冲刺探索票："
                    "保留前几组覆盖骨架，额外从前区中段高分组合中补一张更激进的完整票。"
                ),
                rationale=(
                    "这张票不继续追随当前贪心覆盖顺序，而是从前区高分排序的中段截取尚未入选的完整组合，"
                    "用较小的票数代价补强 4+ / 5+ 前区命中的跃迁空间。"
                ),
            )
        )
        used_keys.add(key)
        if len(probe_schemes) >= probe_slots:
            break

    if len(probe_schemes) < probe_slots:
        for candidate in ranked_front:
            key = (candidate.front_numbers, candidate.back_numbers)
            if key in used_keys:
                continue
            probe_schemes.append(
                _scheme_from_ticket_candidate(
                    candidate,
                    index=keep_count + len(probe_schemes),
                    front_candidates=front_candidates,
                    back_candidates=back_candidates,
                    strategy=(
                        f"第 {keep_count + len(probe_schemes) + 1} 组作为头奖冲刺探索票："
                        "在中段候选不足时，回退补入前区更强的完整组合。"
                    ),
                    rationale=(
                        "优先尝试前区中段高分组合；若可用样本不足，再回退到更强的前区完整票，"
                        "保持冲刺位始终存在。"
                    ),
                )
            )
            used_keys.add(key)
            if len(probe_schemes) >= probe_slots:
                break

    if len(probe_schemes) < probe_slots:
        return base_schemes

    combined = protected + probe_schemes
    relabeled: list[FinalScheme] = []
    for index, scheme in enumerate(combined):
        label = SCHEME_STYLES[index] if index < len(SCHEME_STYLES) else f"Scheme {index + 1}"
        relabeled.append(scheme.model_copy(update={"label": label}))
    return relabeled


def _front_pair_consensus_score(
    numbers_key: tuple[int, ...],
    pair_consensus: dict[tuple[int, int], float],
) -> float:
    return sum(pair_consensus.get(tuple(sorted(pair)), 0.0) for pair in combinations(numbers_key, 2))


def _front_expanded_variant_score(
    numbers_key: tuple[int, ...],
    *,
    zone: str,
    score_map: dict[int, float],
    combo_weights: dict[str, float],
    number_consensus: dict[int, float],
    pair_consensus: dict[tuple[int, int], float],
    anchor_front: frozenset[int],
    core_front: frozenset[int],
    probe_mode: bool,
) -> float:
    base_score = _combo_score_from_key(
        numbers_key,
        zone=zone,
        score_map=score_map,
        candidate_weight=combo_weights["candidate"],
        structure_weight=combo_weights["structure"],
        front_jackpot_pattern_weight=combo_weights.get("front_jackpot_pattern", 0.0),
    )
    number_bonus = (
        sum(number_consensus.get(number, 0.0) for number in numbers_key) / max(1, len(numbers_key))
    ) * 0.035
    pair_bonus = _front_pair_consensus_score(numbers_key, pair_consensus) * 0.008
    anchor_overlap = len(anchor_front.intersection(numbers_key))
    core_overlap = len(core_front.intersection(numbers_key))
    score = base_score + number_bonus + pair_bonus + core_overlap * 0.006
    if probe_mode:
        probe_numbers = set(numbers_key) - core_front
        score += len(probe_numbers) * combo_weights.get("front_probe_support_bonus", 0.0)
        if anchor_overlap == 3:
            score += combo_weights.get("front_probe_anchor_bonus", 0.0)
        elif anchor_overlap >= 4:
            score -= combo_weights.get("front_probe_anchor_bonus", 0.0) * 0.4
    else:
        if anchor_overlap >= 4:
            score += 0.02
    return round(score, 4)


def _build_expanded_front_variants(
    front_combos: list[tuple[list[int], float]],
    *,
    scheme_count: int,
    combo_weights: dict[str, float],
    front_score_map: dict[int, float],
) -> tuple[list[tuple[list[int], float]], list[tuple[list[int], float]]]:
    anchor_front_numbers, anchor_front_score = front_combos[0]
    consensus_rank_pool = front_combos[: max(14, scheme_count * 5)]
    number_consensus: dict[int, float] = {}
    pair_consensus: dict[tuple[int, int], float] = {}
    for rank, (front_numbers, front_score) in enumerate(consensus_rank_pool):
        rank_weight = max(0.42, 1.0 - rank * 0.06)
        weighted_score = front_score * rank_weight
        for number in front_numbers:
            number_consensus[number] = number_consensus.get(number, 0.0) + weighted_score
        for left, right in combinations(front_numbers, 2):
            pair_key = tuple(sorted((left, right)))
            pair_consensus[pair_key] = pair_consensus.get(pair_key, 0.0) + weighted_score

    core_candidate_numbers = [
        number
        for number, _ in sorted(
            number_consensus.items(),
            key=lambda item: (-item[1], -front_score_map.get(item[0], 0.0), item[0]),
        )[: min(10, max(7, scheme_count + 5))]
    ]
    if len(core_candidate_numbers) < 4:
        core_candidate_numbers = sorted(anchor_front_numbers, key=lambda number: (-front_score_map.get(number, 0.0), number))

    best_core_score = float("-inf")
    anchor_front_ranked = sorted(anchor_front_numbers, key=lambda number: (-front_score_map.get(number, 0.0), number))
    core_front_numbers = tuple(sorted(anchor_front_ranked[:4]))
    for subset in combinations(core_candidate_numbers, 4):
        subset_numbers = tuple(sorted(subset))
        number_score = sum(number_consensus.get(number, 0.0) for number in subset_numbers)
        pair_score = _front_pair_consensus_score(subset_numbers, pair_consensus)
        anchor_overlap = len(set(subset_numbers).intersection(anchor_front_numbers))
        subset_score = number_score + pair_score * 0.22 + anchor_overlap * 0.08
        if subset_score > best_core_score:
            best_core_score = subset_score
            core_front_numbers = subset_numbers

    anchor_front_set = frozenset(anchor_front_numbers)
    core_front_set = frozenset(core_front_numbers)
    anchor_tail_numbers = [number for number in anchor_front_numbers if number not in core_front_set]
    variant_weights: dict[int, float] = {}
    for rank, (front_numbers, front_score) in enumerate(front_combos[: max(16, scheme_count * 6)]):
        rank_weight = max(0.4, 1.0 - rank * 0.08)
        for number in front_numbers:
            if number in core_front_set:
                continue
            consensus_bonus = number_consensus.get(number, 0.0) * 0.28
            pair_bonus = sum(
                pair_consensus.get(tuple(sorted((number, core_number))), 0.0) for core_number in core_front_numbers
            ) * 0.08
            variant_weights[number] = variant_weights.get(number, 0.0) + front_score * rank_weight + consensus_bonus + pair_bonus

    variant_numbers = [
        number
        for number, _ in sorted(
            variant_weights.items(),
            key=lambda item: (-item[1], -front_score_map.get(item[0], 0.0), item[0]),
        )
    ]
    for number in anchor_tail_numbers:
        if number in variant_numbers:
            variant_numbers.remove(number)
        variant_numbers.insert(0, number)

    anchor_variants: list[tuple[list[int], float]] = []
    seen_anchor_variants: set[tuple[int, ...]] = set()
    anchor_combo = tuple(sorted(anchor_front_numbers))
    anchor_variants.append((list(anchor_combo), anchor_front_score))
    seen_anchor_variants.add(anchor_combo)

    for number in variant_numbers[: max(4, scheme_count + 1)]:
        variant_combo = tuple(sorted((*core_front_numbers, number)))
        if variant_combo in seen_anchor_variants:
            continue
        anchor_variants.append(
            (
                list(variant_combo),
                _front_expanded_variant_score(
                    variant_combo,
                    zone="front",
                    score_map=front_score_map,
                    combo_weights=combo_weights,
                    number_consensus=number_consensus,
                    pair_consensus=pair_consensus,
                    anchor_front=anchor_front_set,
                    core_front=core_front_set,
                    probe_mode=False,
                ),
            )
        )
        seen_anchor_variants.add(variant_combo)

    probe_variants: list[tuple[list[int], float]] = []
    seen_probe_variants: set[tuple[int, ...]] = set()
    probe_support_numbers = variant_numbers[: max(5, min(len(variant_numbers), scheme_count + 2))]
    probe_core_numbers = tuple(sorted(core_front_numbers[:3]))
    for support_numbers in combinations(probe_support_numbers, 2):
        probe_combo = tuple(sorted((*probe_core_numbers, *support_numbers)))
        if probe_combo in seen_anchor_variants or probe_combo in seen_probe_variants:
            continue
        probe_variants.append(
            (
                list(probe_combo),
                _front_expanded_variant_score(
                    probe_combo,
                    zone="front",
                    score_map=front_score_map,
                    combo_weights=combo_weights,
                    number_consensus=number_consensus,
                    pair_consensus=pair_consensus,
                    anchor_front=anchor_front_set,
                    core_front=core_front_set,
                    probe_mode=True,
                ),
            )
        )
        seen_probe_variants.add(probe_combo)

    for front_numbers, front_score in front_combos[: max(18, scheme_count * 6)]:
        combo_key = tuple(front_numbers)
        if combo_key in seen_anchor_variants or combo_key in seen_probe_variants:
            continue
        overlap = len(set(front_numbers).intersection(core_front_set))
        if overlap < 3:
            continue
        probe_mode = overlap == 3
        target_list = probe_variants if probe_mode else anchor_variants
        target_list.append(
            (
                front_numbers,
                _front_expanded_variant_score(
                    combo_key,
                    zone="front",
                    score_map=front_score_map,
                    combo_weights=combo_weights,
                    number_consensus=number_consensus,
                    pair_consensus=pair_consensus,
                    anchor_front=anchor_front_set,
                    core_front=core_front_set,
                    probe_mode=probe_mode,
                ) + (0.006 * overlap),
            )
        )
        if len(anchor_variants) >= max(scheme_count + 3, 8) and len(probe_variants) >= max(2, scheme_count):
            break

    anchor_variants.sort(key=lambda item: (-item[1], item[0]))
    probe_variants.sort(key=lambda item: (-item[1], item[0]))
    return anchor_variants, probe_variants


def _build_front_wheel_plan(
    front_combos: list[tuple[list[int], float]],
    *,
    scheme_count: int,
    combo_weights: dict[str, float],
    front_score_map: dict[int, float],
) -> list[tuple[list[int], float]]:
    if scheme_count < 5 or not front_combos:
        return []
    consensus_rank_pool = front_combos[: max(18, scheme_count * 6)]
    number_consensus: dict[int, float] = {}
    pair_consensus: dict[tuple[int, int], float] = {}
    for rank, (front_numbers, front_score) in enumerate(consensus_rank_pool):
        rank_weight = max(0.4, 1.0 - rank * 0.06)
        weighted_score = front_score * rank_weight
        for number in front_numbers:
            number_consensus[number] = number_consensus.get(number, 0.0) + weighted_score
        for left, right in combinations(front_numbers, 2):
            pair_key = tuple(sorted((left, right)))
            pair_consensus[pair_key] = pair_consensus.get(pair_key, 0.0) + weighted_score

    wheel_candidate_numbers = [
        number
        for number, _ in sorted(
            number_consensus.items(),
            key=lambda item: (-item[1], -front_score_map.get(item[0], 0.0), item[0]),
        )[:6]
    ]
    if len(wheel_candidate_numbers) < 6:
        return []

    anchor_front_numbers = tuple(sorted(front_combos[0][0]))
    anchor_front_set = frozenset(anchor_front_numbers)
    anchor_front_ranked = sorted(anchor_front_numbers, key=lambda number: (-front_score_map.get(number, 0.0), number))
    lock_number = anchor_front_ranked[0] if anchor_front_ranked and anchor_front_ranked[0] in wheel_candidate_numbers else wheel_candidate_numbers[0]
    rotating_numbers = [number for number in wheel_candidate_numbers if number != lock_number][:5]
    if len(rotating_numbers) < 5:
        return []

    wheel_core_numbers = tuple(sorted((lock_number, *rotating_numbers)))
    core_front_numbers = tuple(sorted([lock_number, *rotating_numbers[:3]]))
    core_front_set = frozenset(core_front_numbers)
    wheel_plan: list[tuple[list[int], float]] = []
    for omitted_number in rotating_numbers:
        wheel_combo = tuple(sorted(number for number in wheel_core_numbers if number != omitted_number))
        score = _front_expanded_variant_score(
            wheel_combo,
            zone="front",
            score_map=front_score_map,
            combo_weights=combo_weights,
            number_consensus=number_consensus,
            pair_consensus=pair_consensus,
            anchor_front=anchor_front_set,
            core_front=core_front_set,
            probe_mode=False,
        )
        score += 0.018
        score -= number_consensus.get(omitted_number, 0.0) * 0.0008
        if omitted_number not in anchor_front_set:
            score += 0.006
        wheel_plan.append((list(wheel_combo), round(score, 4)))
    wheel_plan.sort(key=lambda item: (-item[1], item[0]))
    return wheel_plan[:scheme_count]


def _compose_front_plan(
    anchor_variants: list[tuple[list[int], float]],
    probe_variants: list[tuple[list[int], float]],
    *,
    scheme_count: int,
    combo_weights: dict[str, float],
) -> list[tuple[list[int], float]]:
    probe_slots = int(max(0, round(combo_weights.get("front_probe_slots", 0.0))))
    probe_slots = min(probe_slots, max(0, scheme_count - 2), len(probe_variants))
    anchor_slots = max(1, min(scheme_count - probe_slots, len(anchor_variants)))

    anchor_selected = anchor_variants[:anchor_slots]
    probe_selected = probe_variants[:probe_slots]
    plan: list[tuple[list[int], float]] = []
    seen_keys: set[tuple[int, ...]] = set()
    for index in range(max(len(anchor_selected), len(probe_selected))):
        if index < len(anchor_selected):
            candidate = anchor_selected[index]
            key = tuple(candidate[0])
            if key not in seen_keys:
                plan.append(candidate)
                seen_keys.add(key)
        if index < len(probe_selected):
            candidate = probe_selected[index]
            key = tuple(candidate[0])
            if key not in seen_keys:
                plan.append(candidate)
                seen_keys.add(key)

    for candidate in anchor_variants[anchor_slots:] + probe_variants[probe_slots:]:
        key = tuple(candidate[0])
        if key in seen_keys:
            continue
        plan.append(candidate)
        seen_keys.add(key)
        if len(plan) >= scheme_count:
            break
    return plan[:scheme_count]


def _compose_anchor_repeat_front_plan(
    anchor_variants: list[tuple[list[int], float]],
    probe_variants: list[tuple[list[int], float]],
    *,
    scheme_count: int,
    combo_weights: dict[str, float],
) -> list[tuple[list[int], float]]:
    if not anchor_variants:
        return []
    repeat_slots = int(max(2, round(combo_weights.get("front_anchor_repeat_mode", 0.0))))
    repeat_slots = min(repeat_slots, max(1, scheme_count - 1))
    anchor_ticket = anchor_variants[0]
    plan: list[tuple[list[int], float]] = [anchor_ticket for _ in range(repeat_slots)]
    for candidate in anchor_variants[1:] + probe_variants:
        plan.append(candidate)
        if len(plan) >= scheme_count:
            break
    while len(plan) < scheme_count:
        plan.append(anchor_ticket)
    return plan[:scheme_count]


def _select_back_variants_for_front_core(
    back_combos: list[tuple[list[int], float]],
    *,
    scheme_count: int,
    combo_weights: dict[str, float] | None = None,
) -> list[tuple[list[int], float]]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    selected: list[tuple[list[int], float]] = []
    used_pairs: set[tuple[int, ...]] = set()
    back_usage: Counter[int] = Counter()

    while len(selected) < scheme_count:
        chosen: tuple[list[int], float] | None = None
        chosen_score = float("-inf")
        for back_numbers, back_score in back_combos:
            pair_key = tuple(back_numbers)
            if pair_key in used_pairs:
                continue
            fresh_ratio = sum(1 for number in back_numbers if back_usage[number] == 0) / len(back_numbers)
            usage_penalty = sum(back_usage[number] for number in back_numbers)
            overlap_penalty = sum(
                len(set(back_numbers).intersection(existing_back_numbers)) ** 2
                for existing_back_numbers, _ in selected
            )
            selection_score = (
                back_score
                + fresh_ratio * (weights["fresh_back_bonus"] * 0.9)
                - usage_penalty * (weights["back_usage_penalty"] * 0.35)
                - overlap_penalty * (weights["overlap_back"] * 0.12)
            )
            if selection_score > chosen_score:
                chosen = (back_numbers, back_score)
                chosen_score = selection_score
        if chosen is None:
            break
        selected.append(chosen)
        used_pairs.add(tuple(chosen[0]))
        back_usage.update(chosen[0])
    return selected


def _select_clustered_back_variants(
    back_combos: list[tuple[list[int], float]],
    *,
    scheme_count: int,
    combo_weights: dict[str, float] | None = None,
    back_candidates: list[CandidateBreakdown] | None = None,
) -> list[tuple[list[int], float]]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    if not back_combos or scheme_count <= 0:
        return []

    back_score_map = {item.number: item.score for item in (back_candidates or [])}
    pair_score_map = {tuple(pair): score for pair, score in back_combos}
    pool_size = 5 if weights.get("back_wheel_mode", 0.0) >= 1.5 else 4
    ranked_back_numbers = [item.number for item in (back_candidates or [])[: max(pool_size, scheme_count)]]

    if len(ranked_back_numbers) < pool_size:
        consensus_numbers: list[int] = []
        seen_numbers: set[int] = set()
        for back_numbers, _back_score in back_combos[: max(8, scheme_count * 2)]:
            for number in back_numbers:
                if number in seen_numbers:
                    continue
                seen_numbers.add(number)
                consensus_numbers.append(number)
                if len(consensus_numbers) >= pool_size:
                    break
            if len(consensus_numbers) >= pool_size:
                break
        ranked_back_numbers = consensus_numbers
    if len(ranked_back_numbers) < pool_size:
        return _select_back_variants_for_front_core(
            back_combos,
            scheme_count=scheme_count,
            combo_weights=combo_weights,
        )

    back_pool = tuple(sorted(ranked_back_numbers[:pool_size]))
    scored_pairs: list[tuple[tuple[int, int], float]] = []
    for pair in combinations(back_pool, 2):
        combo_score = pair_score_map.get(pair)
        if combo_score is None:
            avg_score = sum(back_score_map.get(number, 0.0) for number in pair) / len(pair)
            combo_score = round(avg_score, 4)
        floor_score = min(back_score_map.get(number, combo_score) for number in pair)
        avg_score = sum(back_score_map.get(number, combo_score) for number in pair) / len(pair)
        pair_score = round(
            combo_score
            + floor_score * weights.get("back_pair_floor_bonus", 0.0)
            + avg_score * 0.05,
            4,
        )
        scored_pairs.append((pair, pair_score))
    if len(scored_pairs) <= scheme_count:
        return [(list(pair), score) for pair, score in sorted(scored_pairs, key=lambda item: (-item[1], item[0]))]

    best_subset: list[tuple[tuple[int, int], float]] | None = None
    best_score = float("-inf")
    for subset in combinations(scored_pairs, scheme_count):
        usage = Counter(number for pair, _score in subset for number in pair)
        total_pair_score = sum(score for _pair, score in subset)
        top_number_bonus = sum(min(3, usage.get(number, 0)) for number in back_pool[:2]) * 0.035
        support_bonus = sum(min(2, usage.get(number, 0)) for number in back_pool[2:]) * 0.018
        missing_penalty = sum(0.022 for number in back_pool if usage.get(number, 0) == 0)
        thin_penalty = sum(0.012 for number in back_pool if usage.get(number, 0) == 1)
        balance_penalty = max(0, max(usage.values()) - min(usage.values())) * 0.01 if usage else 0.0
        selection_score = total_pair_score + top_number_bonus + support_bonus - missing_penalty - thin_penalty - balance_penalty
        if selection_score > best_score:
            best_score = selection_score
            best_subset = list(subset)

    if not best_subset:
        return _select_back_variants_for_front_core(
            back_combos,
            scheme_count=scheme_count,
            combo_weights=combo_weights,
        )
    best_subset.sort(key=lambda item: (-item[1], item[0]))
    return [(list(pair), score) for pair, score in best_subset]


def _select_independent_back_variants(
    back_combos: list[tuple[list[int], float]],
    *,
    scheme_count: int,
    combo_weights: dict[str, float] | None = None,
    back_candidates: list[CandidateBreakdown] | None = None,
) -> list[tuple[list[int], float]]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    if not back_combos:
        return []
    back_score_map = {item.number: item.score for item in (back_candidates or [])}
    ranked_pairs: list[tuple[list[int], float, float]] = []
    for back_numbers, back_score in back_combos:
        floor_score = min(back_score_map.get(number, back_score) for number in back_numbers)
        pair_score = round(
            back_score
            + floor_score * weights.get("back_pair_floor_bonus", 0.0)
            + (sum(back_score_map.get(number, back_score) for number in back_numbers) / len(back_numbers)) * 0.04,
            4,
        )
        ranked_pairs.append((back_numbers, back_score, pair_score))
    ranked_pairs.sort(key=lambda item: (-item[2], -item[1], item[0]))

    strong_slots = int(max(2, round(weights.get("back_jackpot_slots", max(2.0, scheme_count - 2.0)))))
    strong_slots = min(strong_slots, scheme_count)
    selected: list[tuple[list[int], float]] = []
    used_pairs: set[tuple[int, ...]] = set()
    covered_numbers: set[int] = set()
    back_usage: Counter[int] = Counter()

    while len(selected) < scheme_count:
        chosen: tuple[list[int], float] | None = None
        chosen_score = float("-inf")
        coverage_phase = len(selected) >= strong_slots
        for back_numbers, back_score, independent_score in ranked_pairs:
            pair_key = tuple(back_numbers)
            if pair_key in used_pairs:
                continue
            new_numbers = sum(1 for number in back_numbers if number not in covered_numbers)
            fresh_ratio = new_numbers / len(back_numbers)
            usage_penalty = sum(back_usage[number] for number in back_numbers)
            overlap_penalty = sum(
                len(set(back_numbers).intersection(existing_back_numbers)) ** 2
                for existing_back_numbers, _ in selected
            )
            selection_score = independent_score
            if coverage_phase:
                selection_score += fresh_ratio * max(
                    weights["fresh_back_bonus"],
                    weights.get("back_pair_coverage_bonus", weights["fresh_back_bonus"]),
                )
                selection_score -= usage_penalty * max(0.04, weights["back_usage_penalty"] * 0.30)
            else:
                selection_score += fresh_ratio * (weights["fresh_back_bonus"] * 0.35)
                selection_score -= usage_penalty * max(0.02, weights["back_usage_penalty"] * 0.12)
            selection_score -= overlap_penalty * (weights["overlap_back"] * 0.10)
            if selection_score > chosen_score:
                chosen = (back_numbers, back_score)
                chosen_score = selection_score
        if chosen is None:
            break
        selected.append(chosen)
        used_pairs.add(tuple(chosen[0]))
        covered_numbers.update(chosen[0])
        back_usage.update(chosen[0])
    return selected


def _build_multi_cover_front_core_schemes(
    front_candidates: list[CandidateBreakdown],
    back_candidates: list[CandidateBreakdown],
    scheme_count: int,
    *,
    combo_weights: dict[str, float] | None = None,
    search_profile: str = "full",
) -> list[FinalScheme]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    front_combos = _enumerate_scored_combinations(
        front_candidates,
        pick_count=5,
        strategy_mode="multi_cover",
        zone="front",
        combo_weights=weights,
        search_profile=search_profile,
    )
    back_combos = _enumerate_scored_combinations(
        back_candidates,
        pick_count=2,
        strategy_mode="multi_cover",
        zone="back",
        combo_weights=weights,
        search_profile=search_profile,
    )
    if not front_combos or not back_combos:
        return []

    _, back_limit = _scheme_search_limits("multi_cover", search_profile, combo_weights=weights)
    front_score_map = {item.number: item.score for item in front_candidates}
    anchor_variants: list[tuple[list[int], float]] = []
    probe_variants: list[tuple[list[int], float]] = []
    if weights.get("front_wheel_mode", 0.0) >= 0.5:
        front_plan = _build_front_wheel_plan(
            front_combos,
            scheme_count=scheme_count,
            combo_weights=weights,
            front_score_map=front_score_map,
        )
    else:
        front_plan = []
    if not front_plan:
        anchor_variants, probe_variants = _build_expanded_front_variants(
            front_combos,
            scheme_count=scheme_count,
            combo_weights=weights,
            front_score_map=front_score_map,
        )
        if weights.get("front_anchor_repeat_mode", 0.0) >= 0.5:
            front_plan = _compose_anchor_repeat_front_plan(
                anchor_variants,
                probe_variants,
                scheme_count=scheme_count,
                combo_weights=weights,
            )
        else:
            front_plan = _compose_front_plan(
                anchor_variants,
                probe_variants,
                scheme_count=scheme_count,
                combo_weights=weights,
            )
    if not front_plan:
        return []

    back_variant_candidates = back_combos[: max(back_limit * 2, scheme_count * 4)]
    if weights.get("back_wheel_mode", 0.0) >= 0.5:
        selected_back_variants = _select_clustered_back_variants(
            back_variant_candidates,
            scheme_count=scheme_count,
            combo_weights=weights,
            back_candidates=back_candidates,
        )
    elif weights.get("back_independent_coverage", 0.0) >= 0.5:
        selected_back_variants = _select_independent_back_variants(
            back_variant_candidates,
            scheme_count=scheme_count,
            combo_weights=weights,
            back_candidates=back_candidates,
        )
    else:
        selected_back_variants = _select_back_variants_for_front_core(
            back_variant_candidates,
            scheme_count=scheme_count,
            combo_weights=weights,
        )
    if not selected_back_variants:
        return []

    front_plan = sorted(front_plan[:scheme_count], key=lambda item: (-item[1], item[0]))
    selected_back_variants = sorted(selected_back_variants[:scheme_count], key=lambda item: (-item[1], item[0]))

    schemes: list[FinalScheme] = []
    for index, ((front_numbers, front_score), (back_numbers, back_score)) in enumerate(
        zip(front_plan[:scheme_count], selected_back_variants[:scheme_count]),
        start=1,
    ):
        label = SCHEME_STYLES[index - 1] if index - 1 < len(SCHEME_STYLES) else f"Scheme {index}"
        front_confidence = _confidence_from_scores(front_numbers, front_candidates)
        confidence_back = _confidence_from_scores(back_numbers, back_candidates)
        base_score = round(front_score * weights["pair_front"] + back_score * weights["pair_back"], 4)
        confidence = round(min(0.98, max(base_score, front_confidence * 0.82 + confidence_back * 0.18)), 2)
        schemes.append(
            FinalScheme(
                label=label,
                confidence=confidence,
                strategy=(
                    f"\u7b2c {index} \u7ec4\u5171\u4eab 4 \u7801\u524d\u533a\u5f3a\u6838\uff1a"
                    "\u7b2c 5 \u7801\u53ea\u5728\u5c11\u91cf\u9ad8\u5206\u5019\u9009\u4e2d\u8f6e\u6362\uff0c\u540e\u533a\u518d\u505a\u53d8\u4f53\u6269\u5c55\u4e00\u81f3\u4e09\u7b49\u5956\u843d\u70b9\u3002"
                ),
                front_numbers=list(front_numbers),
                back_numbers=list(back_numbers),
                rationale=(
                    "\u5148\u9501\u5b9a\u524d\u533a 4 \u7801\u4e3b\u6838\uff0c\u53ea\u5bf9\u7b2c 5 \u7801\u4fdd\u7559 2-3 \u4e2a\u9ad8\u6743\u91cd\u5907\u9009\uff0c"
                    "\u518d\u4ece\u9ad8\u5206\u540e\u533a\u5b50\u5bf9\u4e2d\u505a\u53bb\u91cd\u4e0e\u5206\u6563\uff0c"
                    "\u5728\u4e0d\u8fc7\u5ea6\u6253\u6563\u524d\u533a\u7684\u524d\u63d0\u4e0b\u628a\u5934\u5956\u5230\u4e09\u7b49\u5956\u7684\u8def\u5f84\u7559\u5728\u540e\u533a\u53d8\u4f53\u4e0a\u3002"
                ),
            )
        )
    return schemes


def _build_combo_based_schemes(
    front_candidates: list[CandidateBreakdown],
    back_candidates: list[CandidateBreakdown],
    scheme_count: int,
    *,
    strategy_mode: str,
    combo_weights: dict[str, float] | None = None,
    search_profile: str = "full",
) -> list[FinalScheme]:
    weights = {**DEFAULT_COMBO_WEIGHTS, **(combo_weights or {})}
    if strategy_mode == "multi_cover" and scheme_count >= 3 and weights.get("jackpot_front_core", 0.0) >= 0.5:
        core_schemes = _build_multi_cover_front_core_schemes(
            front_candidates,
            back_candidates,
            scheme_count,
            combo_weights=weights,
            search_profile=search_profile,
        )
        if len(core_schemes) >= scheme_count:
            return core_schemes[:scheme_count]

    ticket_candidates = _build_ticket_candidates(
        front_candidates,
        back_candidates,
        strategy_mode=strategy_mode,
        combo_weights=weights,
        search_profile=search_profile,
    )
    schemes: list[FinalScheme] = []
    used_keys: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()

    while len(schemes) < scheme_count and ticket_candidates:
        selection_context = _build_ticket_selection_context(schemes)
        chosen: TicketCandidate | None = None
        chosen_score = float("-inf")
        for candidate in ticket_candidates:
            key = (candidate.front_numbers, candidate.back_numbers)
            if key in used_keys:
                continue
            if strategy_mode == "multi_cover" and _violates_multi_cover_overlap_guard(candidate, schemes):
                continue
            selection_score = _ticket_selection_score(
                candidate,
                schemes,
                strategy_mode=strategy_mode,
                combo_weights=combo_weights,
                selection_context=selection_context,
            )
            if selection_score > chosen_score:
                chosen = candidate
                chosen_score = selection_score
        if chosen is None:
            break

        front_numbers = list(chosen.front_numbers)
        back_numbers = list(chosen.back_numbers)
        used_keys.add((chosen.front_numbers, chosen.back_numbers))
        label = SCHEME_STYLES[len(schemes)] if len(schemes) < len(SCHEME_STYLES) else f"Scheme {len(schemes) + 1}"
        confidence_front = _confidence_from_scores(front_numbers, front_candidates)
        confidence_back = _confidence_from_scores(back_numbers, back_candidates)
        confidence = round(min(0.98, max(chosen.base_score, confidence_front * 0.7 + confidence_back * 0.3)), 2)

        if strategy_mode == "single_hit":
            strategy_text = (
                f"\u7b2c {len(schemes) + 1} \u7ec4\u4ee5\u5355\u6ce8\u5f3a\u5ea6\u4f18\u5148\uff1a"
                "\u4fdd\u7559\u9ad8\u5206\u6838\u5fc3\u53f7\uff0c\u53ea\u5bf9\u8fc7\u5ea6\u91cd\u53e0\u548c\u62e5\u6324\u540e\u533a\u505a\u8f7b\u5ea6\u60e9\u7f5a\u3002"
            )
            rationale = (
                "\u5148\u5bf9\u524d\u540e\u533a\u7ec4\u5408\u5206\u522b\u6253\u5206\uff0c\u518d\u6309\u6574\u6ce8\u5f62\u6001\u3001"
                "\u540e\u533a\u4f7f\u7528\u9891\u6b21\u4e0e\u5927\u4f17\u5316\u6a21\u5f0f\u8fdb\u884c\u4e8c\u6b21\u7b5b\u9009\u3002"
            )
        else:
            strategy_text = (
                f"\u7b2c {len(schemes) + 1} \u7ec4\u6309\u8986\u76d6\u589e\u76ca\u9009\u53d6\uff1a"
                "\u56f4\u7ed5\u9ad8\u5206\u524d\u533a\u6838\u5fc3\u505a 4+1 \u8f6e\u6362\uff0c\u540e\u533a\u7ee7\u7eed\u5206\u6563\uff0c"
                "\u4f18\u5148\u517c\u987e\u56db\u7b49\u5956\u8986\u76d6\u5f62\u6001\u3002"
            )
            rationale = (
                "\u5019\u9009\u6c60\u5148\u6839\u636e\u5355\u53f7\u5f97\u5206\u548c\u7ec4\u5408\u7ed3\u6784\u751f\u6210\uff0c"
                "\u518d\u7528\u8d2a\u5fc3\u4f18\u5316\u4fdd\u7559\u5f3a\u524d\u533a\u6838\u5fc3\u3001\u5206\u6563\u540e\u533a\u4f7f\u7528\u6b21\u6570\uff0c"
                "\u5e76\u63a7\u5236\u5927\u4f17\u5316\u6a21\u5f0f\u3002"
            )

        schemes.append(
            FinalScheme(
                label=label,
                confidence=confidence,
                strategy=strategy_text,
                front_numbers=front_numbers,
                back_numbers=back_numbers,
                rationale=rationale,
            )
        )
    if (
        strategy_mode == "multi_cover"
        and scheme_count >= 5
        and weights.get("jackpot_mid_probe", 0.0) >= 0.5
        and len(schemes) >= scheme_count
    ):
        schemes = _apply_mid_front_probe_schemes(
            schemes[:scheme_count],
            ticket_candidates,
            front_candidates=front_candidates,
            back_candidates=back_candidates,
            combo_weights=weights,
        )
    return schemes


def _violates_multi_cover_overlap_guard(candidate: TicketCandidate, selected: list[FinalScheme]) -> bool:
    if not selected:
        return False
    selected_back_pairs = {tuple(scheme.back_numbers) for scheme in selected}
    if tuple(candidate.back_numbers) in selected_back_pairs:
        return True
    return False


def _build_final_schemes(
    front_candidates: list[CandidateBreakdown],
    back_candidates: list[CandidateBreakdown],
    scheme_count: int,
    *,
    strategy_mode: str = "multi_cover",
    combo_weights: dict[str, float] | None = None,
    search_profile: str = "full",
) -> list[FinalScheme]:
    """Build N schemes either for single-ticket strength or multi-ticket coverage."""
    combo_schemes = _build_combo_based_schemes(
        front_candidates,
        back_candidates,
        scheme_count,
        strategy_mode=strategy_mode,
        combo_weights=combo_weights,
        search_profile=search_profile,
    )
    if len(combo_schemes) >= scheme_count:
        return combo_schemes[:scheme_count]

    schemes: list[FinalScheme] = list(combo_schemes)
    front_pool = front_candidates[: max(25, scheme_count * 5 + 5)]
    back_pool = back_candidates[: max(8, scheme_count * 2 + 2)]
    front_covered: set[int] = {number for scheme in schemes for number in scheme.front_numbers}
    back_covered: set[int] = {number for scheme in schemes for number in scheme.back_numbers}

    for index in range(len(schemes), scheme_count):
        label = SCHEME_STYLES[index] if index < len(SCHEME_STYLES) else f"Scheme {index + 1}"
        if strategy_mode == "single_hit":
            front_nums = _scheme_numbers(front_candidates, 5, variant=index)
            back_nums = _scheme_numbers(back_candidates, 2, variant=index)
            strategy_text = (
                f"\u7b2c {index + 1} \u7ec4\u91c7\u7528\u5355\u6ce8\u4f18\u5148\u6392\u5e8f\uff1a"
                "\u56f4\u7ed5\u9ad8\u5206\u6838\u5fc3\u53f7\u505a\u4e0d\u540c\u53d8\u4f53\uff0c"
                "\u76ee\u6807\u662f\u628a\u5355\u6ce8\u547d\u4e2d\u80fd\u529b\u5c3d\u91cf\u96c6\u4e2d\u5728\u524d\u51e0\u7ec4\u3002"
            )
            rationale = (
                "\u4ee5\u9057\u6f0f / \u9891\u7387 / \u8fd1\u671f\u51b7\u70ed\u8bc4\u5206\u4e3a\u4e3b\uff0c"
                "\u4e0d\u523b\u610f\u8ffd\u6c42\u7ec4\u4e0e\u7ec4\u4e4b\u95f4\u7684\u5927\u8986\u76d6\uff0c"
                "\u66f4\u504f\u5411\u628a\u80fd\u91cf\u96c6\u4e2d\u5728\u9ad8\u5206\u53f7\u7801\u4e0a\u3002"
            )
        else:
            if index == 0:
                front_nums = _scheme_numbers(front_candidates, 5, variant=0)
                back_nums = _scheme_numbers(back_candidates, 2, variant=0)
                strategy_text = (
                    "\u9996\u9009\u4ee5\u603b\u5408\u5f97\u5206\u6700\u9ad8\u7684\u6838\u5fc3\u53f7\u7801\u4e3a\u4e3b\uff0c"
                    "\u4ee5\u5c3e\u6570\u591a\u6837\u5316\u5151\u73b0\u4e3b\u9009\u5207\u7247\u3002"
                )
            else:
                front_nums = _coverage_pick(front_pool, front_covered, count=5)
                back_nums = _coverage_pick(back_pool, back_covered, count=2)
                strategy_text = (
                    f"\u7b2c {index + 1} \u7ec4\u91c7\u7528\u8d2a\u5fc3\u8986\u76d6\u7b56\u7565\uff1a"
                    "\u4f18\u5148\u9009\u672a\u88ab\u5176\u4ed6\u65b9\u6848\u8986\u76d6\u7684\u9ad8\u5206\u53f7\u7801\uff0c"
                    "\u4ee5\u6269\u5927\u591a\u6ce8\u7684\u8054\u5408\u8986\u76d6\u9762\uff0c\u964d\u4f4e\u5168\u5957\u843d\u7a7a\u6982\u7387\u3002"
                )
            rationale = (
                "\u6309\u9057\u6f0f / \u9891\u7387 / \u8fd1\u671f\u51b7\u70ed \u4e3a\u4e3b\u52a0\u6743\uff0c"
                "\u5366\u8c61\u5c3e\u6570\u6743\u91cd\u4f5c\u4e3a\u8f85\u52a9\u4fe1\u53f7\uff1b"
                "\u591a\u6ce8\u4e4b\u95f4\u91c7\u7528\u8986\u76d6\u4f18\u5316\u4ee5\u63d0\u9ad8\u81f3\u5c11\u547d\u4e2d 1 \u7801\u7684\u6982\u7387\u3002"
            )

        front_covered.update(front_nums)
        back_covered.update(back_nums)
        confidence_front = _confidence_from_scores(front_nums, front_pool)
        confidence_back = _confidence_from_scores(back_nums, back_pool)
        confidence = round(confidence_front * 0.7 + confidence_back * 0.3, 2)

        schemes.append(
            FinalScheme(
                label=label,
                confidence=confidence,
                strategy=strategy_text,
                front_numbers=front_nums,
                back_numbers=back_nums,
                rationale=rationale,
            )
        )
    return schemes


def _local_ai_analysis(
    all_draws_count: int,
    active_elements: list[str],
    favored_tails: list[int],
    front_candidates: list[CandidateBreakdown],
    final_schemes: list[FinalScheme],
    *,
    engine_label: str,
    extra_overview: str = "",
) -> AIAnalysis:
    hot_front = [item.number for item in sorted(front_candidates, key=lambda item: (-item.recent_hits, -item.score))[:3]]
    cold_front = [item.number for item in sorted(front_candidates, key=lambda item: (-item.omission, -item.score))[:3]]
    display_elements = _display_elements(active_elements)
    return AIAnalysis(
        engine=engine_label,
        overview=(
            f"{extra_overview}"
            f"\u672c\u6b21\u672c\u5730\u6a21\u578b\u7eb3\u5165 {all_draws_count} \u671f\u5168\u5386\u53f2\u3001\u6885\u82b1\u6613\u6570\u5366\u8c61\u4e0e\u51b7\u70ed\u9057\u6f0f\u8bc4\u5206\uff0c"
            f"\u4e94\u884c\u503e\u5411\u4e3a {', '.join(display_elements)}\uff0c"
            f"\u5c3e\u6570\u91cd\u5fc3\u96c6\u4e2d\u5728 {', '.join(str(item) for item in favored_tails[:4])}\u3002"
        ),
        key_factors=[
            f"\u5168\u5386\u53f2\u6837\u672c\u91cf\u4e3a {all_draws_count} \u671f\u3002",
            f"\u524d\u533a\u8fd1\u671f\u70ed\u53f7\u53c2\u8003\uff1a{', '.join(str(number) for number in hot_front)}\u3002",
            f"\u524d\u533a\u51b7\u53f7\u56de\u8865\u53c2\u8003\uff1a{', '.join(str(number) for number in cold_front)}\u3002",
        ],
        final_advice=(
            f"\u672c\u6b21\u6309\u591a\u6ce8\u8986\u76d6\u4f18\u5316\u8fd4\u56de {len(final_schemes)} \u7ec4\u65b9\u6848\uff0c"
            "\u5efa\u8bae\u4f18\u5148\u5173\u6ce8\u9996\u9009\uff0c\u518d\u7ed3\u5408\u4e2a\u4eba\u98ce\u9669\u504f\u597d\u8fdb\u884c\u7b5b\u9009\uff0c\u7406\u6027\u8d2d\u5f69\u3002"
        ),
    )


def _build_ai_user_prompt(
    all_draws_count: int,
    active_elements: list[str],
    favored_tails: list[int],
    front_candidates: list[CandidateBreakdown],
    back_candidates: list[CandidateBreakdown],
    final_schemes: list[FinalScheme],
) -> str:
    display_elements = _display_elements(active_elements)
    hot_front = sorted(front_candidates, key=lambda item: (-item.recent_hits, -item.score))[:5]
    cold_front = sorted(front_candidates, key=lambda item: (-item.omission, -item.score))[:5]
    top_front = sorted(front_candidates, key=lambda item: (-item.score))[:8]
    top_back = sorted(back_candidates, key=lambda item: (-item.score))[:5]

    def fmt_candidate(c: CandidateBreakdown) -> str:
        return (
            f"{c.number:02d}(\u5f97\u5206{c.score:.2f}/\u9057\u6f0f{c.omission}/"
            f"\u9891\u7387{c.frequency}/\u8fd130\u671f\u547d\u4e2d{c.recent_hits})"
        )

    schemes_lines = []
    for index, scheme in enumerate(final_schemes, start=1):
        schemes_lines.append(
            f"\u7b2c{index}\u7ec4 [{scheme.label}] \u524d\u533a {scheme.front_numbers} + \u540e\u533a {scheme.back_numbers}\uff0c"
            f"\u7f6e\u4fe1\u5ea6 {scheme.confidence:.2f}"
        )

    allowed_front = ", ".join(f"{item.number:02d}" for item in front_candidates[:25])
    allowed_back = ", ".join(f"{item.number:02d}" for item in back_candidates[:8])

    return (
        "\u8bf7\u6839\u636e\u4ee5\u4e0b\u5927\u4e50\u900f\u63a8\u6f14\u4e0a\u4e0b\u6587\uff0c\u5148\u5bf9\u672c\u5730\u7ed9\u51fa\u7684\u5019\u9009\u65b9\u6848\u505a\u6700\u7ec8\u786e\u8ba4\u6216\u5fae\u8c03\uff0c"
        "\u518d\u8f93\u51fa\u4e00\u4efd\u7b80\u6d01\u3001\u4e13\u4e1a\u7684\u5206\u6790\u70b9\u8bc4\u3002\n\n"
        f"\u5168\u5386\u53f2\u6837\u672c\uff1a{all_draws_count} \u671f\n"
        f"\u672c\u671f\u5366\u8c61\u4e94\u884c\u6fc0\u6d3b\uff1a{', '.join(display_elements)}\n"
        f"\u5c3e\u6570\u504f\u597d\uff1a{', '.join(str(t) for t in favored_tails[:6])}\n\n"
        f"\u524d\u533a\u9ad8\u5206 Top 8\uff1a{', '.join(fmt_candidate(c) for c in top_front)}\n"
        f"\u524d\u533a\u8fd1\u671f\u70ed\u53f7\uff1a{', '.join(fmt_candidate(c) for c in hot_front)}\n"
        f"\u524d\u533a\u51b7\u53f7\u56de\u8865\uff1a{', '.join(fmt_candidate(c) for c in cold_front)}\n"
        f"\u540e\u533a\u9ad8\u5206 Top 5\uff1a{', '.join(fmt_candidate(c) for c in top_back)}\n\n"
        f"\u5141\u8bb8\u9009\u7528\u7684\u524d\u533a\u53f7\u7801\u6c60\uff08\u4ec5\u53ef\u4ece\u6b64\u8303\u56f4\u9009\uff09\uff1a{allowed_front}\n"
        f"\u5141\u8bb8\u9009\u7528\u7684\u540e\u533a\u53f7\u7801\u6c60\uff08\u4ec5\u53ef\u4ece\u6b64\u8303\u56f4\u9009\uff09\uff1a{allowed_back}\n\n"
        "\u672c\u6b21\u63a8\u6f14\u8fd4\u56de\u7684\u65b9\u6848\uff1a\n"
        + "\n".join(schemes_lines)
        + "\n\n"
        "\u8bf7\u5bf9\u4e0a\u8ff0\u65b9\u6848\u8fdb\u884c\u201cAI \u6700\u7ec8\u786e\u8ba4\u201d\uff1a\n"
        "1. \u53ef\u4ee5\u76f4\u63a5\u4fdd\u7559\u67d0\u7ec4\u65b9\u6848\uff1b\n"
        "2. \u53ef\u4ee5\u5728\u53f7\u7801\u6c60\u5185\u5bf9\u5355\u7ec4\u65b9\u6848\u505a\u5c0f\u5e45\u66ff\u6362\u6216\u91cd\u6392\uff1b\n"
        "3. \u4e0d\u8981\u8d85\u8fc7\u8f93\u5165\u8981\u6c42\u7684\u7ec4\u6570\uff1b\n"
        "4. \u6bcf\u7ec4\u524d\u533a\u5fc5\u987b 5 \u4e2a\u4e0d\u91cd\u590d\u53f7\u7801\uff0c\u540e\u533a\u5fc5\u987b 2 \u4e2a\u4e0d\u91cd\u590d\u53f7\u7801\uff1b\n"
        "5. \u4e0d\u8981\u4f7f\u7528\u53f7\u7801\u6c60\u4e4b\u5916\u7684\u53f7\u7801\u3002\n\n"
        "\u8bf7\u4ee5 JSON \u683c\u5f0f\u8f93\u51fa\uff0c\u4e0d\u8981\u5305\u88f9\u5728 markdown \u4ee3\u7801\u5757\u91cc\uff0c\u5b57\u6bb5\u5982\u4e0b\uff1a\n"
        "{\n"
        '  "selected_schemes": [\n'
        '    {\n'
        '      "label": "<方案名>",\n'
        '      "front_numbers": [1, 2, 3, 4, 5],\n'
        '      "back_numbers": [1, 2],\n'
        '      "confidence": 0.78,\n'
        '      "strategy": "<保留或调整原因>",\n'
        '      "rationale": "<该组最终确认逻辑>"\n'
        "    }\n"
        "  ],\n"
        '  "overview": "<2-4\u53e5\u8bdd\u603b\u4f53\u70b9\u8bc4\u672c\u671f\u9009\u53f7\u903b\u8f91\u4e0e\u4e3b\u8981\u4fe1\u53f7>",\n'
        '  "key_factors": ["<\u5173\u952e\u56e0\u7d201>", "<\u5173\u952e\u56e0\u7d202>", "<\u5173\u952e\u56e0\u7d203>"],\n'
        '  "final_advice": "<\u5bf9\u591a\u7ec4\u65b9\u6848\u7684\u9009\u62e9\u5efa\u8bae\u548c\u98ce\u9669\u63d0\u793a\uff0c1-3\u53e5>"\n'
        "}\n"
        "\u8bf7\u52ff\u8f93\u51fa\u5176\u4ed6\u6587\u672c\u3001\u52ff\u8bb8\u8bfa\u4e2d\u5956\u7ed3\u679c\u3002"
    )


def _build_ai_repair_prompt(raw: str, final_schemes: list[FinalScheme]) -> str:
    allowed_lines = [
        f"{index + 1}. {scheme.label}: front_numbers={scheme.front_numbers}, back_numbers={scheme.back_numbers}, confidence={scheme.confidence}"
        for index, scheme in enumerate(final_schemes)
    ]
    return (
        "上一轮回答没有提供可解析的 selected_schemes。请只做格式修复，不要解释。\n"
        "你必须返回一个 JSON object，且必须包含 selected_schemes 数组。\n"
        f"selected_schemes 必须正好 {len(final_schemes)} 组；每组 front_numbers 正好 5 个 1-35 的整数，"
        "back_numbers 正好 2 个 1-12 的整数。\n"
        "如果上一轮没有明确号码，请从以下本地候选方案中选择或原样保留：\n"
        + "\n".join(allowed_lines)
        + "\n\n上一轮 AI 原文如下：\n"
        + raw[:4000]
        + "\n\n只输出如下 JSON：\n"
        "{\n"
        '  "selected_schemes": [\n'
        '    {"label": "方案A", "front_numbers": [1,2,3,4,5], "back_numbers": [1,2], "confidence": 0.75, "strategy": "格式修复后确认", "rationale": "简短理由"}\n'
        "  ],\n"
        '  "overview": "简短总评",\n'
        '  "key_factors": ["关键因素1", "关键因素2", "关键因素3"],\n'
        '  "final_advice": "简短建议"\n'
        "}"
    )


def _parse_ai_json(text: str) -> dict | None:
    """Try to extract a JSON object from LLM output (handles ```json blocks and surrounding text)."""
    if not text:
        return None
    # Strip markdown code fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidate = fence.group(1) if fence else text
    # Find the first {...} block
    match = re.search(r"\{[\s\S]*\}", candidate)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _parse_ai_partial_json(text: str) -> dict | None:
    """Recover complete scheme objects from a truncated JSON response."""
    if not text or "selected_schemes" not in text:
        return None

    schemes: list[dict] = []
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        start = text.find("{", pos)
        if start < 0:
            break
        try:
            item, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            pos = start + 1
            continue
        if isinstance(item, dict) and (
            "front_numbers" in item
            or "back_numbers" in item
            or "front" in item
            or "back" in item
            or "numbers" in item
        ):
            schemes.append(item)
        pos = start + max(end, 1)

    if schemes:
        return {
            "selected_schemes": schemes,
            "overview": "AI 返回 JSON 被截断，已从可解析的号码方案中恢复。",
            "key_factors": ["AI 已返回号码方案", "原始 JSON 未完整闭合", "后端已执行容错恢复"],
            "final_advice": "请理性参考，避免将任何单次推演视为确定结果。",
        }
    regex_schemes = _parse_ai_number_patterns(text)
    if regex_schemes:
        return {
            "selected_schemes": regex_schemes,
            "overview": "AI 返回 JSON 被截断，已从号码数组中恢复方案。",
            "key_factors": ["AI 已返回号码数组", "原始 JSON 未完整闭合", "后端已执行号码级恢复"],
            "final_advice": "请理性参考，避免将任何单次推演视为确定结果。",
        }
    return None


def _parse_ai_number_patterns(text: str) -> list[dict]:
    schemes: list[dict] = []
    pattern = re.compile(
        r'"front_numbers"\s*:\s*\[([^\]]+)\][\s\S]{0,1200}?"back_numbers"\s*:\s*\[([^\]]+)\]',
        re.IGNORECASE,
    )
    for index, match in enumerate(pattern.finditer(text), start=1):
        front = _numbers_from_csv(match.group(1))
        back = _numbers_from_csv(match.group(2))
        if len(front) == 5 and len(back) == 2:
            schemes.append(
                {
                    "label": f"AI恢复方案{index}",
                    "front_numbers": front,
                    "back_numbers": back,
                    "confidence": 0.65,
                    "strategy": "从截断 JSON 的号码数组中恢复",
                    "rationale": "AI 已返回号码数组，但响应正文未完整闭合。",
                }
            )
    return schemes


def _numbers_from_csv(value: str) -> list[int]:
    numbers: list[int] = []
    for item in re.findall(r"\d+", value):
        try:
            numbers.append(int(item))
        except ValueError:
            continue
    return numbers


def _normalize_scheme_numbers(values: object, *, expected_count: int, min_value: int, max_value: int) -> list[int] | None:
    if not isinstance(values, list):
        return None
    normalized: list[int] = []
    for item in values:
        try:
            number = int(item)
        except (TypeError, ValueError):
            return None
        if number < min_value or number > max_value:
            return None
        normalized.append(number)
    unique_sorted = sorted(set(normalized))
    if len(unique_sorted) != expected_count or len(normalized) != expected_count:
        return None
    return unique_sorted


def _scheme_from_local_pool(
    payload: dict,
    *,
    index: int,
    strategy_mode: str,
    front_pool: list[CandidateBreakdown],
    back_pool: list[CandidateBreakdown],
) -> FinalScheme | None:
    front_numbers = _normalize_scheme_numbers(
        _first_present(
            payload,
            "front_numbers",
            "front",
            "front_area",
            "frontArea",
            "red",
            "reds",
            "qianqu",
            "前区",
        ),
        expected_count=5,
        min_value=1,
        max_value=35,
    )
    back_numbers = _normalize_scheme_numbers(
        _first_present(
            payload,
            "back_numbers",
            "back",
            "back_area",
            "backArea",
            "blue",
            "blues",
            "houqu",
            "后区",
        ),
        expected_count=2,
        min_value=1,
        max_value=12,
    )
    if (not front_numbers or not back_numbers) and isinstance(payload.get("numbers"), list):
        values = payload.get("numbers")
        if isinstance(values, list) and len(values) == 7:
            front_numbers = _normalize_scheme_numbers(values[:5], expected_count=5, min_value=1, max_value=35)
            back_numbers = _normalize_scheme_numbers(values[5:], expected_count=2, min_value=1, max_value=12)
    if not front_numbers or not back_numbers:
        return None

    allowed_front = {item.number for item in front_pool}
    allowed_back = {item.number for item in back_pool}
    if any(number not in allowed_front for number in front_numbers):
        return None
    if any(number not in allowed_back for number in back_numbers):
        return None

    label = str(payload.get("label") or "").strip() or (
        SCHEME_STYLES[index] if index < len(SCHEME_STYLES) else f"Scheme {index + 1}"
    )
    strategy = str(payload.get("strategy") or "").strip() or (
        "AI 最终确认保留当前组合。" if strategy_mode == "single_hit" else "AI 最终确认当前覆盖组合。"
    )
    rationale = str(payload.get("rationale") or "").strip() or "AI 基于候选号池完成最终确认。"

    confidence_raw = payload.get("confidence")
    if isinstance(confidence_raw, (int, float)):
        confidence = round(max(0.45, min(0.98, float(confidence_raw))), 2)
    else:
        confidence_front = _confidence_from_scores(front_numbers, front_pool)
        confidence_back = _confidence_from_scores(back_numbers, back_pool)
        confidence = round(confidence_front * 0.7 + confidence_back * 0.3, 2)

    return FinalScheme(
        label=label,
        confidence=confidence,
        strategy=strategy,
        front_numbers=front_numbers,
        back_numbers=back_numbers,
        rationale=rationale,
    )


def _first_present(payload: dict, *keys: str) -> object:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _candidate_scheme_items(payload: dict) -> object:
    for key in (
        "selected_schemes",
        "schemes",
        "final_schemes",
        "recommended_schemes",
        "recommendations",
        "tickets",
        "plans",
        "方案",
        "推荐方案",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return None


def _extract_ai_selected_schemes(
    payload: dict | None,
    *,
    scheme_count: int,
    strategy_mode: str,
    front_pool: list[CandidateBreakdown],
    back_pool: list[CandidateBreakdown],
) -> list[FinalScheme] | None:
    if not payload:
        return None
    raw_items = _candidate_scheme_items(payload)
    if not isinstance(raw_items, list):
        return None
    raw_items = raw_items[:scheme_count]

    schemes: list[FinalScheme] = []
    seen_keys: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        scheme = _scheme_from_local_pool(
            item,
            index=index,
            strategy_mode=strategy_mode,
            front_pool=front_pool,
            back_pool=back_pool,
        )
        if not scheme:
            continue
        key = (tuple(scheme.front_numbers), tuple(scheme.back_numbers))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        schemes.append(scheme)
    return schemes or None


def _fill_missing_ai_schemes(ai_schemes: list[FinalScheme], local_schemes: list[FinalScheme]) -> list[FinalScheme]:
    if len(ai_schemes) >= len(local_schemes):
        return ai_schemes[: len(local_schemes)]
    merged = list(ai_schemes)
    seen = {(tuple(item.front_numbers), tuple(item.back_numbers)) for item in merged}
    for local in local_schemes:
        key = (tuple(local.front_numbers), tuple(local.back_numbers))
        if key in seen:
            continue
        merged.append(local)
        seen.add(key)
        if len(merged) >= len(local_schemes):
            break
    return merged


def _build_ai_analysis(
    all_draws_count: int,
    active_elements: list[str],
    favored_tails: list[int],
    front_candidates: list[CandidateBreakdown],
    back_candidates: list[CandidateBreakdown],
    final_schemes: list[FinalScheme],
    strategy_mode: str,
    ai_config: AIConfigRequest | None,
    *,
    force_ai: bool = False,
) -> tuple[AIAnalysis, list[FinalScheme]]:
    # If external AI not enabled / configured, fall back to local template.
    if not (ai_config and ai_config.enabled and ai_config.base_url and ai_config.api_key and ai_config.model):
        if force_ai:
            raise AIConfigurationError("号码推演已强制启用 AI，请先在设置中启用外部 AI，并填写接口地址、API Key 和模型。")
        logger.info(
            "[AI] skip external call: enabled=%s base_url=%s model=%s api_key=%s",
            bool(ai_config and ai_config.enabled),
            bool(ai_config and ai_config.base_url),
            bool(ai_config and ai_config.model),
            bool(ai_config and ai_config.api_key),
        )
        return _local_ai_analysis(
            all_draws_count,
            active_elements,
            favored_tails,
            front_candidates,
            final_schemes,
            engine_label="Local Ensemble AI",
        ), final_schemes

    system_prompt = (ai_config.system_prompt or "").strip() or DEFAULT_AI_SYSTEM_PROMPT
    user_prompt = _build_ai_user_prompt(
        all_draws_count,
        active_elements,
        favored_tails,
        front_candidates,
        back_candidates,
        final_schemes,
    )

    logger.info("[AI] calling external chat completion: base_url=%s model=%s", ai_config.base_url, ai_config.model)
    try:
        raw = chat_completion(
            base_url=ai_config.base_url,
            api_key=ai_config.api_key,
            model=ai_config.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_completion_tokens=4096,
            json_mode=True,
            reasoning_effort="minimal",
            timeout=120,
        )
        logger.info("[AI] external chat completion succeeded, response chars=%d", len(raw))
    except Exception as exc:  # noqa: BLE001
        if force_ai:
            raise AIGenerationError(f"AI 号码推演调用失败：{exc}") from exc
        logger.warning("[AI] external call FAILED, falling back to local: %s", exc)
        return _local_ai_analysis(
            all_draws_count,
            active_elements,
            favored_tails,
            front_candidates,
            final_schemes,
            engine_label=f"AI \u63a5\u53e3 / {ai_config.model} (\u8c03\u7528\u5931\u8d25\uff0c\u5df2\u56de\u9000\u672c\u5730)",
            extra_overview=f"[\u5916\u90e8 AI \u8c03\u7528\u5f02\u5e38\uff1a{exc}] ",
        ), final_schemes

    local_schemes = list(final_schemes)
    parsed = _parse_ai_json(raw) or _parse_ai_partial_json(raw)
    ai_schemes = _extract_ai_selected_schemes(
        parsed,
        scheme_count=len(final_schemes),
        strategy_mode=strategy_mode,
        front_pool=front_candidates,
        back_pool=back_candidates,
    )
    if ai_schemes:
        final_schemes = _fill_missing_ai_schemes(ai_schemes, local_schemes)
        logger.info("[AI] accepted structured selected_schemes, count=%d recovered=%d", len(final_schemes), len(ai_schemes))
    else:
        logger.info(
            "[AI] structured scheme parse failed: parsed_keys=%s raw_preview=%s",
            list(parsed.keys()) if isinstance(parsed, dict) else None,
            raw[:800].replace("\r", "\\r").replace("\n", "\\n"),
        )
        repaired_schemes: list[FinalScheme] | None = None
        if force_ai:
            try:
                repaired_raw = chat_completion(
                    base_url=ai_config.base_url,
                    api_key=ai_config.api_key,
                    model=ai_config.model,
                    system_prompt="你是 JSON 格式修复器。只输出一个合法 JSON object，不要 markdown，不要解释。",
                    user_prompt=_build_ai_repair_prompt(raw, final_schemes),
                    temperature=0,
                    max_completion_tokens=4096,
                    json_mode=True,
                    reasoning_effort="minimal",
                    timeout=120,
                )
                repaired = _parse_ai_json(repaired_raw) or _parse_ai_partial_json(repaired_raw)
                repaired_schemes = _extract_ai_selected_schemes(
                    repaired,
                    scheme_count=len(final_schemes),
                    strategy_mode=strategy_mode,
                    front_pool=front_candidates,
                    back_pool=back_candidates,
                )
                if repaired_schemes:
                    parsed = repaired
                    raw = repaired_raw
                    final_schemes = _fill_missing_ai_schemes(repaired_schemes, local_schemes)
                    logger.info("[AI] accepted repaired selected_schemes, count=%d recovered=%d", len(final_schemes), len(repaired_schemes))
                else:
                    logger.info(
                        "[AI] repaired scheme parse failed: parsed_keys=%s raw_preview=%s",
                        list(repaired.keys()) if isinstance(repaired, dict) else None,
                        repaired_raw[:800].replace("\r", "\\r").replace("\n", "\\n"),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.info("[AI] structured scheme repair failed: %s", exc)
        if force_ai and not repaired_schemes:
            raise AIGenerationError("AI 已返回内容，但 selected_schemes 缺失或格式不符合要求，无法确认 AI 号码方案。")
        logger.info("[AI] selected_schemes missing or invalid, keeping local schemes")

    if parsed and isinstance(parsed.get("overview"), str):
        key_factors_raw = parsed.get("key_factors") or []
        key_factors: list[str] = []
        if isinstance(key_factors_raw, list):
            key_factors = [str(item) for item in key_factors_raw if str(item).strip()][:6]
        elif isinstance(key_factors_raw, str):
            key_factors = [key_factors_raw]
        if not key_factors:
            key_factors = ["\u672a\u63d0\u4f9b\u5173\u952e\u56e0\u7d20"]
        final_advice = parsed.get("final_advice") or ""
        logger.info("[AI] parsed structured JSON output successfully")
        return AIAnalysis(
            engine=f"\u2728 AI \u63a5\u53e3 / {ai_config.model}",
            overview=str(parsed.get("overview", "")).strip(),
            key_factors=key_factors,
            final_advice=str(final_advice).strip() or "\u8bf7\u7406\u6027\u8d2d\u5f69\uff0c\u4ee5\u5a31\u4e50\u4e3a\u4e3b\u3002",
        ), final_schemes

    logger.info("[AI] response was not JSON-parsable, returning raw text")
    if force_ai:
        raise AIGenerationError("AI 已返回内容，但不是可解析的 JSON，无法完成强制 AI 号码推演。")
    # Couldn't parse structured JSON — surface raw text in overview.
    truncated = raw.strip()
    if len(truncated) > 800:
        truncated = truncated[:800] + "..."
    return AIAnalysis(
        engine=f"\u2728 AI \u63a5\u53e3 / {ai_config.model} (\u539f\u59cb\u8f93\u51fa)",
        overview=truncated,
        key_factors=["\u6a21\u578b\u672a\u8fd4\u56de\u6807\u51c6 JSON\uff0c\u4ee5\u4e0b\u4e3a\u539f\u6587\u3002"],
        final_advice="\u5982\u9700\u7ed3\u6784\u5316\u8f93\u51fa\uff0c\u53ef\u5728\u8bbe\u7f6e\u4e2d\u8c03\u6574\u7cfb\u7edf\u63d0\u793a\u8bcd\uff0c\u6216\u66f4\u6362\u66f4\u9075\u5faa\u6307\u4ee4\u7684\u6a21\u578b\u3002",
    ), final_schemes


def generate_divination(
    history: list,
    issue: str | None = None,
    timestamp: str | None = None,
    scheme_count: int = 3,
    strategy_mode: str = "multi_cover",
    ai_config: AIConfigRequest | None = None,
    target_draw_date: date | None = None,
    score_weights: dict[str, float] | None = None,
    combo_weights: dict[str, float] | None = None,
    history_context: PrecomputedHistoryFeatures | None = None,
    search_profile: str = "full",
    force_ai: bool = False,
) -> DivinationResponse:
    resolved_target_draw_datetime = _resolve_target_draw_datetime(history, target_draw_date)
    seed = _seed_from_request(issue, timestamp, target_draw_datetime=resolved_target_draw_datetime)
    derived = _derive_hexagrams(seed)
    front_seed = _zone_seed(seed, "front")
    back_seed = _zone_seed(seed, "back")
    front_derived = _derive_hexagrams(front_seed)
    back_derived = _derive_hexagrams(back_seed)
    active_elements = [derived.main.element, derived.mutual.element, derived.changed.element]
    front_active_elements = [front_derived.main.element, front_derived.mutual.element, front_derived.changed.element]
    back_active_elements = [back_derived.main.element, back_derived.mutual.element, back_derived.changed.element]
    front_tail_weights = _build_tail_weights(front_active_elements, front_derived)
    back_tail_weights = _build_tail_weights(back_active_elements, back_derived)
    front_tail_weight_items = _tail_weight_items(front_tail_weights)
    back_tail_weight_items = _tail_weight_items(back_tail_weights)
    tail_weights = _merge_tail_weights(front_tail_weights, back_tail_weights)
    tail_weight_items = _tail_weight_items(tail_weights)
    favored_tails = [item.tail for item in tail_weight_items[:6]]

    context = history_context or build_history_feature_context(history)

    front_scored = _score_candidates(
        range(1, 36),
        front_tail_weights,
        context.front_omission,
        context.front_frequency,
        context.front_recent_hits,
        score_weights,
        history_size=context.history_size,
        window_hits=context.front_window_hits,
    )
    back_scored = _score_candidates(
        range(1, 13),
        back_tail_weights,
        context.back_omission,
        context.back_frequency,
        context.back_recent_hits,
        score_weights,
        history_size=context.history_size,
        window_hits=context.back_window_hits,
    )
    front_recommendations, front_candidates = _pick_recommendations(front_scored, 5)
    back_recommendations, back_candidates = _pick_recommendations(back_scored, 2)
    final_schemes = _build_final_schemes(
        front_candidates,
        back_candidates,
        scheme_count,
        strategy_mode=strategy_mode,
        combo_weights=combo_weights,
        search_profile=search_profile,
    )
    if strategy_mode == "multi_cover" and scheme_count >= 5:
        final_schemes = _apply_floor_harvest_schemes(
            final_schemes[:scheme_count],
            history_desc=history,
            front_candidates=front_candidates,
            back_candidates=back_candidates,
            combo_weights=combo_weights,
            search_profile=search_profile,
        )
    all_draws_count = context.history_size if history_context is not None else len(history)
    ai_analysis, final_schemes = _build_ai_analysis(
        all_draws_count,
        active_elements,
        favored_tails,
        front_candidates,
        back_candidates,
        final_schemes,
        strategy_mode,
        ai_config,
        force_ai=force_ai,
    )

    summary = _build_summary(
        [item.number for item in front_recommendations],
        [item.number for item in back_recommendations],
        favored_tails,
        front_active_elements + back_active_elements,
    )
    summary.explanation = (
        f"本次起卦取推算时点 {_format_seed_datetime(seed.divination_datetime)}，"
        f"应期开奖时点取 {_format_seed_datetime(seed.target_draw_datetime)}，"
        f"{summary.explanation}"
    )

    return DivinationResponse(
        seed_mode=seed.mode,  # type: ignore[arg-type]
        seed_value=seed.seed_value,
        divination_datetime=_format_seed_datetime(seed.divination_datetime),
        target_draw_datetime=_format_seed_datetime(seed.target_draw_datetime),
        strategy_mode=strategy_mode,  # type: ignore[arg-type]
        moving_line=derived.moving_line,
        main_hexagram=derived.main,
        mutual_hexagram=derived.mutual,
        changed_hexagram=derived.changed,
        active_elements=active_elements,
        favored_tails=favored_tails,
        tail_weights=tail_weight_items,
        front_recommendations=front_recommendations,
        back_recommendations=back_recommendations,
        front_candidates=front_candidates,
        back_candidates=back_candidates,
        front_signal=ZoneSignal(
            zone="front",
            main_hexagram=front_derived.main,
            mutual_hexagram=front_derived.mutual,
            changed_hexagram=front_derived.changed,
            active_elements=front_active_elements,
            favored_tails=[item.tail for item in front_tail_weight_items[:6]],
            tail_weights=front_tail_weight_items,
        ),
        back_signal=ZoneSignal(
            zone="back",
            main_hexagram=back_derived.main,
            mutual_hexagram=back_derived.mutual,
            changed_hexagram=back_derived.changed,
            active_elements=back_active_elements,
            favored_tails=[item.tail for item in back_tail_weight_items[:6]],
            tail_weights=back_tail_weight_items,
        ),
        summary=summary,
        ai_analysis=ai_analysis,
        final_schemes=final_schemes,
    )


def run_divination(
    issue: str | None = None,
    timestamp: str | None = None,
    scheme_count: int = 3,
    strategy_mode: str = "multi_cover",
    ai_config: AIConfigRequest | None = None,
    score_weights: dict[str, float] | None = None,
    combo_weights: dict[str, float] | None = None,
    search_profile: str = "full",
) -> DivinationResponse:
    history = get_history(limit=5000)
    return generate_divination(
        history,
        issue=issue,
        timestamp=timestamp,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ai_config=ai_config,
        score_weights=score_weights,
        combo_weights=combo_weights,
        search_profile=search_profile,
    )
