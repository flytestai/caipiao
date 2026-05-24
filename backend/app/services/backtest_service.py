from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
import logging
import os
import random
from itertools import combinations
from math import comb
from typing import Callable

from app.models import (
    BacktestCoverageMetrics,
    BacktestCoverageScoreComponents,
    AIConfigRequest,
    BacktestBenchmark,
    BacktestIssueComparison,
    BacktestIssueResult,
    BacktestIssueModeComparison,
    BacktestModeSummary,
    BacktestResponse,
    BacktestThresholdScanItem,
    BacktestStabilityBreakdown,
    BacktestTuningCandidate,
    BacktestTuningIssueComparison,
    BacktestTuningIssueSide,
    BacktestTuningWalkForwardDetail,
    BacktestTuningSummary,
    BacktestWalkForwardWindow,
    BacktestWindowSummary,
    DivinationResponse,
)
from app.services.meihua import (
    DEFAULT_COMBO_WEIGHTS,
    DEFAULT_SCORE_WEIGHTS,
    PrecomputedHistoryFeatures,
    build_history_feature_context,
    generate_divination,
)
from app.services.repository import build_backtest_stats, evaluate_scheme_against_draw, get_all_history_asc

logger = logging.getLogger(__name__)

TICKET_PRICE = 2.0
ADDITIONAL_TICKET_PRICE = 3.0
RANDOM_BASELINE_RUNS = 24
WINDOW_MODEL_WINDOWS = [(5, 0.32), (10, 0.24), (20, 0.2), (50, 0.14), (100, 0.1)]
WIN_RULES = [
    (5, 2),
    (5, 1),
    (5, 0),
    (4, 2),
    (4, 1),
    (4, 0),
    (3, 2),
    (3, 1),
    (2, 2),
    (3, 0),
    (2, 1),
    (1, 2),
    (0, 2),
]
WINDOW_SUMMARY_SIZES = [20, 50, 100, 200]
THRESHOLD_SCAN_VALUES = [
    0.04,
    0.05,
    0.06,
    0.07,
    0.08,
    0.10,
    0.12,
    0.14,
    0.16,
    0.18,
    0.20,
    0.22,
    0.24,
    0.26,
    0.28,
    0.30,
    0.32,
]
LIVE_TUNING_RECENT_ISSUES = 200
BACKTEST_FAST_PATH_ENGINE_SUFFIX = " / Historical Fast Path"
FAST_TUNING_RECENT_ISSUES_THRESHOLD = 40
FAST_TUNING_TARGET_ISSUES_THRESHOLD = 40
FAST_TUNING_COARSE_QUOTA = 12
TUNING_SUMMARY_CACHE_MAX_ITEMS = 16
BACKTEST_PARALLEL_MIN_ISSUES = 24
BACKTEST_LOCAL_MAX_WORKERS = 8
BACKTEST_EXTERNAL_AI_MAX_WORKERS = 2
OVERALL_WIN_RATE_TARGET = 0.10
_tuning_summary_cache: dict[tuple, BacktestTuningSummary] = {}


def _ticket_unit_price(ticket_mode: str) -> float:
    return ADDITIONAL_TICKET_PRICE if ticket_mode == "additional" else TICKET_PRICE


def _ticket_is_additional(ticket_mode: str) -> bool:
    return ticket_mode == "additional"


def _external_ai_ready(ai_config: AIConfigRequest | None) -> bool:
    return bool(ai_config and ai_config.enabled and ai_config.base_url and ai_config.api_key and ai_config.model)


def _resolve_backtest_ai_config(
    ai_replay_mode: str,
    ai_config: AIConfigRequest | None,
) -> AIConfigRequest | None:
    if ai_replay_mode == "local_only":
        return None
    if ai_replay_mode != "external_rerank":
        raise ValueError(f"Unsupported backtest ai_replay_mode: {ai_replay_mode}")
    if not _external_ai_ready(ai_config):
        raise ValueError("历史回测切换到 AI 重排时，需要先启用并完整配置外部 AI。")
    return ai_config


CALIBRATION_PRIOR_WEIGHT = 24
CALIBRATION_MIN_SAMPLES = 24
CALIBRATION_RADII = [0.0125, 0.025, 0.04, 0.06]
SUPERVISED_WINDOWS = [(12, 0.42), (36, 0.33), (108, 0.25)]
BACKTEST_HISTORY_RECENT_WINDOW = max(
    max(window for window, _ in WINDOW_MODEL_WINDOWS),
    max(window for window, _ in SUPERVISED_WINDOWS),
)
BACKTEST_RECENT_HITS_LOOKBACK = 30
SCORE_WEIGHT_PROFILES: list[tuple[str, str, dict[str, float]]] = [
    ("balanced", "均衡", DEFAULT_SCORE_WEIGHTS),
    ("cold_bias", "冷号偏置", {"tail": 0.10, "omission": 0.46, "frequency": 0.26, "recent_hits": 0.18}),
    ("recent_bias", "近期反转", {"tail": 0.10, "omission": 0.25, "frequency": 0.23, "recent_hits": 0.42}),
    ("frequency_revert", "频率回归", {"tail": 0.12, "omission": 0.22, "frequency": 0.46, "recent_hits": 0.20}),
    ("hexagram_bias", "卦象增强", {"tail": 0.28, "omission": 0.30, "frequency": 0.22, "recent_hits": 0.20}),
]
COMBO_WEIGHT_PROFILES: list[tuple[str, dict[str, float]]] = [
    ("balanced_combo", DEFAULT_COMBO_WEIGHTS),
    (
        "structure_focus",
        {
            "candidate": 0.54,
            "structure": 0.46,
            "pair_front": 0.70,
            "pair_back": 0.30,
            "multi_cover_pair": 0.66,
            "multi_cover_novelty": 0.34,
            "single_hit_pair": 0.88,
            "single_hit_novelty": 0.12,
        },
    ),
    (
        "candidate_focus",
        {
            "candidate": 0.74,
            "structure": 0.26,
            "pair_front": 0.78,
            "pair_back": 0.22,
            "multi_cover_pair": 0.82,
            "multi_cover_novelty": 0.18,
            "single_hit_pair": 0.96,
            "single_hit_novelty": 0.04,
        },
    ),
    (
        "candidate_focus_jackpot_floor_guarded",
        {
            "candidate": 0.74,
            "structure": 0.26,
            "pair_front": 0.78,
            "pair_back": 0.22,
            "multi_cover_pair": 0.82,
            "multi_cover_novelty": 0.18,
            "single_hit_pair": 0.96,
            "single_hit_novelty": 0.04,
            "back_usage_penalty": 0.14,
            "fresh_back_bonus": 0.26,
            "crowd_penalty": 0.12,
            "floor_harvest_slots": 2.0,
            "front_jackpot_pattern": 0.08,
            "back_pair_floor_bonus": 0.14,
            "back_pair_coverage_bonus": 0.20,
        },
    ),
    (
        "front_focus",
        {
            "candidate": 0.82,
            "structure": 0.18,
            "pair_front": 0.88,
            "pair_back": 0.12,
            "multi_cover_pair": 0.94,
            "multi_cover_novelty": 0.06,
            "single_hit_pair": 0.97,
            "single_hit_novelty": 0.03,
            "overlap_front": 0.02,
            "overlap_back": 0.22,
            "same_back_pair_penalty": 1.35,
            "back_usage_penalty": 0.10,
            "fresh_back_bonus": 0.18,
            "crowd_penalty": 0.08,
        },
    ),
    (
        "front_focus_floor_guarded",
        {
            "candidate": 0.82,
            "structure": 0.18,
            "pair_front": 0.88,
            "pair_back": 0.12,
            "multi_cover_pair": 0.94,
            "multi_cover_novelty": 0.06,
            "single_hit_pair": 0.97,
            "single_hit_novelty": 0.03,
            "overlap_front": 0.02,
            "overlap_back": 0.22,
            "same_back_pair_penalty": 1.35,
            "back_usage_penalty": 0.07,
            "fresh_back_bonus": 0.26,
            "crowd_penalty": 0.08,
            "floor_harvest_slots": 2.0,
            "back_pair_floor_bonus": 0.14,
            "back_pair_coverage_bonus": 0.20,
        },
    ),
    (
        "jackpot_focus",
        {
            "candidate": 0.86,
            "structure": 0.14,
            "pair_front": 0.90,
            "pair_back": 0.10,
            "multi_cover_pair": 0.95,
            "multi_cover_novelty": 0.05,
            "single_hit_pair": 0.98,
            "single_hit_novelty": 0.02,
            "overlap_front": 0.015,
            "overlap_back": 0.24,
            "same_back_pair_penalty": 1.45,
            "back_usage_penalty": 0.12,
            "fresh_back_bonus": 0.20,
            "crowd_penalty": 0.06,
            "jackpot_front_core": 1.0,
        },
    ),
    (
        "jackpot_guarded",
        {
            **DEFAULT_COMBO_WEIGHTS,
            "crowd_penalty": 0.14,
            "jackpot_mid_probe": 1.0,
            "jackpot_probe_slots": 1.0,
            "jackpot_probe_front_rank_low": 20.0,
            "jackpot_probe_front_rank_high": 80.0,
        },
    ),
    (
        "ultra_core_jackpot",
        {
            "candidate": 0.90,
            "structure": 0.10,
            "pair_front": 0.94,
            "pair_back": 0.06,
            "multi_cover_pair": 0.97,
            "multi_cover_novelty": 0.03,
            "single_hit_pair": 0.98,
            "single_hit_novelty": 0.02,
            "overlap_front": 0.008,
            "overlap_back": 0.18,
            "same_back_pair_penalty": 1.55,
            "back_usage_penalty": 0.08,
            "fresh_back_bonus": 0.22,
            "crowd_penalty": 0.05,
            "jackpot_front_core": 1.0,
            "front_jackpot_pattern": 0.24,
        },
    ),
    (
        "ultra_core_guarded",
        {
            "candidate": 0.88,
            "structure": 0.12,
            "pair_front": 0.92,
            "pair_back": 0.08,
            "multi_cover_pair": 0.96,
            "multi_cover_novelty": 0.04,
            "single_hit_pair": 0.98,
            "single_hit_novelty": 0.02,
            "overlap_front": 0.010,
            "overlap_back": 0.16,
            "same_back_pair_penalty": 1.48,
            "back_usage_penalty": 0.07,
            "fresh_back_bonus": 0.24,
            "crowd_penalty": 0.07,
            "jackpot_front_core": 1.0,
            "front_jackpot_pattern": 0.20,
        },
    ),
    (
        "front_back_split",
        {
            "candidate": 0.89,
            "structure": 0.11,
            "pair_front": 0.93,
            "pair_back": 0.07,
            "multi_cover_pair": 0.96,
            "multi_cover_novelty": 0.04,
            "single_hit_pair": 0.98,
            "single_hit_novelty": 0.02,
            "overlap_front": 0.010,
            "overlap_back": 0.14,
            "same_back_pair_penalty": 1.52,
            "back_usage_penalty": 0.05,
            "fresh_back_bonus": 0.30,
            "crowd_penalty": 0.06,
            "jackpot_front_core": 1.0,
            "front_jackpot_pattern": 0.22,
            "front_probe_slots": 1.0,
            "front_probe_anchor_bonus": 0.08,
            "front_probe_support_bonus": 0.035,
            "back_independent_coverage": 1.0,
            "back_jackpot_slots": 4.0,
            "back_pair_floor_bonus": 0.18,
            "back_pair_coverage_bonus": 0.34,
            "floor_harvest_slots": 1.0,
        },
    ),
    (
        "wide_split_guarded",
        {
            "candidate": 0.88,
            "structure": 0.12,
            "pair_front": 0.92,
            "pair_back": 0.08,
            "multi_cover_pair": 0.95,
            "multi_cover_novelty": 0.05,
            "single_hit_pair": 0.98,
            "single_hit_novelty": 0.02,
            "overlap_front": 0.012,
            "overlap_back": 0.14,
            "same_back_pair_penalty": 1.50,
            "back_usage_penalty": 0.05,
            "fresh_back_bonus": 0.32,
            "crowd_penalty": 0.08,
            "jackpot_front_core": 1.0,
            "front_jackpot_pattern": 0.20,
            "front_probe_slots": 1.0,
            "front_probe_anchor_bonus": 0.07,
            "front_probe_support_bonus": 0.03,
            "back_independent_coverage": 1.0,
            "back_jackpot_slots": 4.0,
            "back_pair_floor_bonus": 0.16,
            "back_pair_coverage_bonus": 0.36,
            "front_pool_boost": 4.0,
            "back_pool_boost": 2.0,
            "front_combo_limit_boost": 60.0,
            "back_combo_limit_boost": 4.0,
            "ticket_candidate_budget_boost": 300.0,
            "floor_harvest_slots": 1.0,
        },
    ),
    (
        "front_wheel_split_guarded",
        {
            "candidate": 0.88,
            "structure": 0.12,
            "pair_front": 0.94,
            "pair_back": 0.06,
            "multi_cover_pair": 0.96,
            "multi_cover_novelty": 0.04,
            "single_hit_pair": 0.98,
            "single_hit_novelty": 0.02,
            "overlap_front": 0.010,
            "overlap_back": 0.14,
            "same_back_pair_penalty": 1.50,
            "back_usage_penalty": 0.05,
            "fresh_back_bonus": 0.30,
            "crowd_penalty": 0.08,
            "jackpot_front_core": 1.0,
            "front_wheel_mode": 1.0,
            "front_jackpot_pattern": 0.22,
            "back_independent_coverage": 1.0,
            "back_jackpot_slots": 4.0,
            "back_pair_floor_bonus": 0.16,
            "back_pair_coverage_bonus": 0.34,
            "front_pool_boost": 4.0,
            "back_pool_boost": 2.0,
            "front_combo_limit_boost": 60.0,
            "back_combo_limit_boost": 4.0,
            "ticket_candidate_budget_boost": 300.0,
            "floor_harvest_slots": 1.0,
        },
    ),
    (
        "core_back_wheel_guarded",
        {
            "candidate": 0.89,
            "structure": 0.11,
            "pair_front": 0.93,
            "pair_back": 0.07,
            "multi_cover_pair": 0.97,
            "multi_cover_novelty": 0.03,
            "single_hit_pair": 0.98,
            "single_hit_novelty": 0.02,
            "overlap_front": 0.006,
            "overlap_back": 0.22,
            "same_back_pair_penalty": 1.05,
            "back_usage_penalty": 0.08,
            "fresh_back_bonus": 0.08,
            "crowd_penalty": 0.06,
            "jackpot_front_core": 1.0,
            "front_jackpot_pattern": 0.18,
            "back_wheel_mode": 1.0,
            "front_pool_boost": 2.0,
            "back_pool_boost": 1.0,
            "front_combo_limit_boost": 40.0,
            "back_combo_limit_boost": 2.0,
            "ticket_candidate_budget_boost": 220.0,
            "back_pair_floor_bonus": 0.14,
            "floor_harvest_slots": 0.0,
        },
    ),
    (
        "front_wheel_back_wheel_guarded",
        {
            "candidate": 0.89,
            "structure": 0.11,
            "pair_front": 0.94,
            "pair_back": 0.06,
            "multi_cover_pair": 0.97,
            "multi_cover_novelty": 0.03,
            "single_hit_pair": 0.98,
            "single_hit_novelty": 0.02,
            "overlap_front": 0.006,
            "overlap_back": 0.22,
            "same_back_pair_penalty": 1.05,
            "back_usage_penalty": 0.08,
            "fresh_back_bonus": 0.08,
            "crowd_penalty": 0.06,
            "jackpot_front_core": 1.0,
            "front_wheel_mode": 1.0,
            "front_jackpot_pattern": 0.20,
            "back_wheel_mode": 1.0,
            "front_pool_boost": 4.0,
            "back_pool_boost": 1.0,
            "front_combo_limit_boost": 60.0,
            "back_combo_limit_boost": 2.0,
            "ticket_candidate_budget_boost": 260.0,
            "back_pair_floor_bonus": 0.14,
            "floor_harvest_slots": 0.0,
        },
    ),
    (
        "anchor_back_ladder_guarded",
        {
            "candidate": 0.89,
            "structure": 0.11,
            "pair_front": 0.94,
            "pair_back": 0.06,
            "multi_cover_pair": 0.98,
            "multi_cover_novelty": 0.02,
            "single_hit_pair": 0.98,
            "single_hit_novelty": 0.02,
            "overlap_front": 0.0,
            "overlap_back": 0.24,
            "same_back_pair_penalty": 1.0,
            "back_usage_penalty": 0.08,
            "fresh_back_bonus": 0.06,
            "crowd_penalty": 0.05,
            "jackpot_front_core": 1.0,
            "front_anchor_repeat_mode": 3.0,
            "front_jackpot_pattern": 0.16,
            "back_wheel_mode": 1.0,
            "front_pool_boost": 2.0,
            "back_pool_boost": 1.0,
            "front_combo_limit_boost": 40.0,
            "back_combo_limit_boost": 2.0,
            "ticket_candidate_budget_boost": 220.0,
            "back_pair_floor_bonus": 0.12,
            "floor_harvest_slots": 0.0,
        },
    ),
    (
        "wide_search",
        {
            **DEFAULT_COMBO_WEIGHTS,
            "front_pool_boost": 4.0,
            "front_combo_limit_boost": 60.0,
            "ticket_candidate_budget_boost": 300.0,
            "crowd_penalty": 0.18,
        },
    ),
    (
        "wide_guarded",
        {
            **DEFAULT_COMBO_WEIGHTS,
            "front_pool_boost": 4.0,
            "front_combo_limit_boost": 60.0,
            "ticket_candidate_budget_boost": 300.0,
            "crowd_penalty": 0.14,
            "jackpot_mid_probe": 1.0,
            "jackpot_probe_slots": 1.0,
            "jackpot_probe_front_rank_low": 20.0,
            "jackpot_probe_front_rank_high": 80.0,
        },
    ),
    (
        "wide_floor_harvest",
        {
            **DEFAULT_COMBO_WEIGHTS,
            "front_pool_boost": 4.0,
            "front_combo_limit_boost": 60.0,
            "ticket_candidate_budget_boost": 300.0,
            "crowd_penalty": 0.18,
            "floor_harvest_slots": 2.0,
        },
    ),
    (
        "wide_front_jackpot",
        {
            **DEFAULT_COMBO_WEIGHTS,
            "front_pool_boost": 4.0,
            "front_combo_limit_boost": 60.0,
            "ticket_candidate_budget_boost": 300.0,
            "crowd_penalty": 0.18,
            "floor_harvest_slots": 2.0,
            "front_jackpot_pattern": 0.18,
        },
    ),
]
HIGH_TIER_SCORE_PROFILE_NAMES = ("frequency_revert", "balanced", "recent_bias", "cold_bias")
HIGH_TIER_FAST_SCORE_PROFILE_NAMES = ("frequency_revert", "balanced", "recent_bias")
HIGH_TIER_COMBO_PROFILE_NAMES = (
    "candidate_focus",
    "candidate_focus_jackpot_floor_guarded",
    "front_focus",
    "front_focus_floor_guarded",
    "jackpot_focus",
    "jackpot_guarded",
    "ultra_core_jackpot",
    "ultra_core_guarded",
    "front_back_split",
    "wide_split_guarded",
    "front_wheel_split_guarded",
    "core_back_wheel_guarded",
    "front_wheel_back_wheel_guarded",
    "anchor_back_ladder_guarded",
)
HIGH_TIER_FAST_COMBO_PROFILE_NAMES = (
    "candidate_focus_jackpot_floor_guarded",
    "front_focus",
    "front_focus_floor_guarded",
    "jackpot_focus",
    "ultra_core_jackpot",
    "ultra_core_guarded",
    "front_back_split",
)
HIGH_TIER_FALLBACK_PROFILE = "frequency_revert+candidate_focus"
TOP3_PRIZE_LEVELS = {"一等奖", "二等奖", "三等奖"}
TOP4_PRIZE_LEVELS = {"一等奖", "二等奖", "三等奖", "四等奖"}
LOW_TIER_PRIZE_LEVELS = ("五等奖", "六等奖", "七等奖")
LOW_TIER_PRIZE_SIGNAL_SCORES = {
    "五等奖": 0.04,
    "六等奖": 0.025,
    "七等奖": 0.01,
}

ProgressCallback = Callable[..., None]
CancelCheck = Callable[[], None]
SCORE_WEIGHT_DISPLAY_NAMES = {
    "balanced": "均衡",
    "cold_bias": "冷号偏置",
    "recent_bias": "近期反转",
    "frequency_revert": "频率回归",
    "hexagram_bias": "卦象增强",
}
COMBO_WEIGHT_DISPLAY_NAMES = {
    "balanced_combo": "均衡组合",
    "structure_focus": "结构优先",
    "candidate_focus": "候选优先",
    "candidate_focus_jackpot_floor_guarded": "候选优先头奖兜底",
    "front_focus": "前区聚焦",
    "front_focus_floor_guarded": "前区聚焦兜底",
    "jackpot_focus": "头奖聚焦",
    "jackpot_guarded": "头奖约束冲刺",
    "front_back_split": "前后区解耦冲刺",
    "wide_split_guarded": "宽域解耦冲刺",
    "front_wheel_split_guarded": "前区六码轮转冲刺",
    "core_back_wheel_guarded": "前核后区集束轮转",
    "front_wheel_back_wheel_guarded": "前后区双轮转收束",
    "anchor_back_ladder_guarded": "前锚重复后区阶梯",
    "wide_search": "宽域搜索",
    "wide_guarded": "宽域冲刺",
    "wide_floor_harvest": "宽域收割",
    "wide_front_jackpot": "宽域前区冲刺",
}


def _backtest_confidence_threshold(strategy_mode: str, scheme_count: int) -> float:
    base = 0.66 if strategy_mode == "single_hit" else 0.64
    if scheme_count >= 5:
        base += 0.02
    elif scheme_count <= 2:
        base -= 0.01
    return round(max(0.60, min(0.82, base)), 2)


def _pool_signal_strength(candidates: list, *, top_n: int) -> float:
    if not candidates:
        return 0.0
    scores = [max(0.0, min(1.0, getattr(item, "score", 0.0))) for item in candidates[:top_n]]
    if not scores:
        return 0.0
    avg = sum(scores) / len(scores)
    spread = max(scores) - min(scores)
    leader = scores[0]
    return round(leader * 0.45 + avg * 0.4 + spread * 0.15, 4)


def _zone_scheme_confidence(final_schemes: list, pool: list, *, zone: str) -> float:
    if not final_schemes or not pool:
        return 0.0
    score_map = {item.number: max(0.0, min(1.0, item.score)) for item in pool}
    numbers = []
    for scheme in final_schemes:
        selected = scheme.front_numbers if zone == "front" else scheme.back_numbers
        numbers.extend(selected)
    selected_scores = [score_map[number] for number in numbers if number in score_map]
    if not selected_scores:
        return 0.0
    selected_scores.sort(reverse=True)
    avg = sum(selected_scores) / len(selected_scores)
    peak = sum(selected_scores[: min(3, len(selected_scores))]) / min(3, len(selected_scores))
    return round(peak * 0.55 + avg * 0.45, 4)


def _dynamic_confidence_threshold(
    *,
    strategy_mode: str,
    scheme_count: int,
    front_candidates: list,
    back_candidates: list,
) -> float:
    base = _backtest_confidence_threshold(strategy_mode, scheme_count)
    front_signal = _pool_signal_strength(front_candidates, top_n=8)
    back_signal = _pool_signal_strength(back_candidates, top_n=5)
    pool_signal = front_signal * 0.65 + back_signal * 0.35
    pivot = 0.62 if strategy_mode == "single_hit" else 0.64
    adjustment = (pivot - pool_signal) * 0.10
    return round(max(0.58, min(0.76, base + adjustment)), 4)


def _zone_confidence_gate(
    *,
    strategy_mode: str,
    zone: str,
    candidates: list,
) -> float:
    signal = _pool_signal_strength(candidates, top_n=8 if zone == "front" else 5)
    if zone == "front":
        base = 0.54 if strategy_mode == "single_hit" else 0.50
        adjustment = (0.64 - signal) * 0.08
        return round(max(0.44, min(0.66, base + adjustment)), 4)
    base = 0.40 if strategy_mode == "single_hit" else 0.36
    adjustment = (0.62 - signal) * 0.08
    return round(max(0.30, min(0.54, base + adjustment)), 4)


def _issue_confidence(final_schemes: list) -> float:
    if not final_schemes:
        return 0.0
    confidences = sorted((max(0.0, min(1.0, scheme.confidence)) for scheme in final_schemes), reverse=True)
    peak = confidences[0]
    avg = sum(confidences) / len(confidences)
    support = sum(confidences[: min(2, len(confidences))]) / min(2, len(confidences))
    return round(peak * 0.5 + support * 0.25 + avg * 0.25, 4)


def _global_issue_hit_prior(strategy_mode: str) -> float:
    return 0.072 if strategy_mode == "single_hit" else 0.088


def _calibrate_binary_confidence(
    raw_confidence: float,
    history: list[dict],
    *,
    history_key: str,
    hit_key: str,
    prior: float,
    floor: float,
    cap: float,
    anchor_low: float,
    anchor_span: float,
    anchor_strength: float,
) -> float:
    if not history:
        return round(prior, 4)
    selected = []
    for radius in CALIBRATION_RADII:
        selected = [
            item
            for item in history
            if history_key in item and hit_key in item and abs(item[history_key] - raw_confidence) <= radius
        ]
        if len(selected) >= CALIBRATION_MIN_SAMPLES:
            break
    if len(selected) < CALIBRATION_MIN_SAMPLES:
        selected = sorted(
            [item for item in history if history_key in item and hit_key in item],
            key=lambda item: abs(item[history_key] - raw_confidence),
        )[:CALIBRATION_MIN_SAMPLES]
    if not selected:
        return round(prior, 4)
    local_hits = sum(item[hit_key] for item in selected)
    local_count = len(selected)
    global_pool = [item for item in history if history_key in item and hit_key in item]
    global_hits = sum(item[hit_key] for item in global_pool)
    global_rate = (global_hits / len(global_pool)) if global_pool else prior
    smoothed = (local_hits + global_rate * CALIBRATION_PRIOR_WEIGHT) / (local_count + CALIBRATION_PRIOR_WEIGHT)
    anchor = max(0.0, min(1.0, (raw_confidence - anchor_low) / anchor_span))
    anchored = smoothed * (1 - anchor_strength) + (prior + anchor * (cap - prior) * 0.35) * anchor_strength
    return round(max(floor, min(cap, anchored)), 4)


def _calibrate_issue_confidence(raw_confidence: float, history: list[dict], *, strategy_mode: str) -> float:
    return _calibrate_binary_confidence(
        raw_confidence,
        history,
        history_key="raw_confidence",
        hit_key="hit",
        prior=_global_issue_hit_prior(strategy_mode),
        floor=0.01,
        cap=0.35,
        anchor_low=0.55,
        anchor_span=0.25,
        anchor_strength=0.15,
    )


def _zone_hit_prior(strategy_mode: str, zone: str) -> float:
    if zone == "front":
        return 0.22 if strategy_mode == "single_hit" else 0.28
    return 0.34 if strategy_mode == "single_hit" else 0.42


def _calibrate_zone_confidence(raw_confidence: float, history: list[dict], *, strategy_mode: str, zone: str) -> float:
    history_key = f"raw_{zone}_confidence"
    hit_key = f"{zone}_hit"
    return _calibrate_binary_confidence(
        raw_confidence,
        history,
        history_key=history_key,
        hit_key=hit_key,
        prior=_zone_hit_prior(strategy_mode, zone),
        floor=0.05,
        cap=0.88 if zone == "back" else 0.80,
        anchor_low=0.36 if zone == "back" else 0.42,
        anchor_span=0.36 if zone == "back" else 0.30,
        anchor_strength=0.22,
    )


def _zone_hit_from_evaluations(evaluations: list[dict], *, zone: str) -> int:
    if zone == "front":
        return 1 if any(item["front_match_count"] >= 3 for item in evaluations) else 0
    return 1 if any(item["back_match_count"] >= 1 for item in evaluations) else 0


def _evaluation_power_score(*, front_match_count: int, back_match_count: int, prize_level: str | None) -> float:
    score = (front_match_count / 5) * 0.74 + (back_match_count / 2) * 0.16
    if front_match_count >= 4:
        score += 0.10
    elif front_match_count == 3:
        score += 0.04
    if front_match_count == 5:
        score += 0.06
    if prize_level in TOP4_PRIZE_LEVELS:
        score += 0.10
    elif prize_level:
        score += LOW_TIER_PRIZE_SIGNAL_SCORES.get(prize_level, 0.0)
    return round(min(1.0, score), 4)


def _issue_quality_signals_from_evaluations(evaluations: list[dict]) -> dict[str, bool | int | float]:
    if not evaluations:
        return {
            "top3_hit": False,
            "top4_hit": False,
            "front_4plus_hit": False,
            "front_5_hit": False,
            "five_plus_zero_hit": False,
            "five_plus_one_hit": False,
            "five_plus_two_hit": False,
            "four_plus_two_hit": False,
            "back_2plus_hit": False,
            "front_best_match_count": 0,
            "back_best_match_count": 0,
            "issue_power_score": 0.0,
        }
    top3_hit = any(item.get("prize_level") in TOP3_PRIZE_LEVELS for item in evaluations)
    top4_hit = any(item.get("prize_level") in TOP4_PRIZE_LEVELS for item in evaluations)
    front_best_match_count = max(int(item.get("front_match_count") or 0) for item in evaluations)
    back_best_match_count = max(int(item.get("back_match_count") or 0) for item in evaluations)
    five_plus_zero_hit = any(
        int(item.get("front_match_count") or 0) >= 5 and int(item.get("back_match_count") or 0) == 0
        for item in evaluations
    )
    five_plus_one_hit = any(
        int(item.get("front_match_count") or 0) >= 5 and int(item.get("back_match_count") or 0) >= 1
        for item in evaluations
    )
    five_plus_two_hit = any(
        int(item.get("front_match_count") or 0) >= 5 and int(item.get("back_match_count") or 0) >= 2
        for item in evaluations
    )
    four_plus_two_hit = any(
        int(item.get("front_match_count") or 0) >= 4 and int(item.get("back_match_count") or 0) >= 2
        for item in evaluations
    )
    back_2plus_hit = any(int(item.get("back_match_count") or 0) >= 2 for item in evaluations)
    issue_power_score = max(
        _evaluation_power_score(
            front_match_count=int(item.get("front_match_count") or 0),
            back_match_count=int(item.get("back_match_count") or 0),
            prize_level=item.get("prize_level"),
        )
        for item in evaluations
    )
    return {
        "top3_hit": top3_hit,
        "top4_hit": top4_hit,
        "front_4plus_hit": front_best_match_count >= 4,
        "front_5_hit": front_best_match_count >= 5,
        "five_plus_zero_hit": five_plus_zero_hit,
        "five_plus_one_hit": five_plus_one_hit,
        "five_plus_two_hit": five_plus_two_hit,
        "four_plus_two_hit": four_plus_two_hit,
        "back_2plus_hit": back_2plus_hit,
        "front_best_match_count": front_best_match_count,
        "back_best_match_count": back_best_match_count,
        "issue_power_score": round(issue_power_score, 4),
    }


_MID_TIER_PRIZE_LEVELS = ("\u4e00\u7b49\u5956", "\u4e8c\u7b49\u5956", "\u4e09\u7b49\u5956", "\u56db\u7b49\u5956", "\u4e94\u7b49\u5956")  # \u4e00~\u4e94\u7b49\u5956\uff0c\u5373"\u4e94\u7b49\u5956\u53ca\u4ee5\u4e0a"
_SIX_PLUS_PRIZE_LEVELS = _MID_TIER_PRIZE_LEVELS + ("\u516d\u7b49\u5956",)  # \u4e00~\u516d\u7b49\u5956\uff0c\u5373"\u516d\u7b49\u5956\u53ca\u4ee5\u4e0a"


def _empty_performance_signal_totals() -> dict[str, float]:
    return {
        "top3_hit_issues": 0.0,
        "top4_hit_issues": 0.0,
        "front_4plus_hit_issues": 0.0,
        "front_5_hit_issues": 0.0,
        "five_plus_zero_hit_issues": 0.0,
        "five_plus_one_hit_issues": 0.0,
        "five_plus_two_hit_issues": 0.0,
        "four_plus_two_hit_issues": 0.0,
        "back_2plus_hit_issues": 0.0,
        "front_best_match_total": 0.0,
        "back_best_match_total": 0.0,
        "issue_power_total": 0.0,
        "six_plus_hit_issues": 0.0,
        "mid_tier_hit_issues": 0.0,
        "six_plus_total_wins": 0.0,
    }


def _performance_signal_totals(issue_results: list[BacktestIssueResult | dict]) -> dict[str, float]:
    totals = _empty_performance_signal_totals()
    for raw_item in issue_results:
        item = raw_item.model_dump() if isinstance(raw_item, BacktestIssueResult) else raw_item
        totals["top3_hit_issues"] += 1.0 if item.get("top3_hit") else 0.0
        totals["top4_hit_issues"] += 1.0 if item.get("top4_hit") else 0.0
        totals["front_4plus_hit_issues"] += 1.0 if item.get("front_4plus_hit") else 0.0
        totals["front_5_hit_issues"] += 1.0 if item.get("front_5_hit") else 0.0
        totals["five_plus_zero_hit_issues"] += 1.0 if item.get("five_plus_zero_hit") else 0.0
        totals["five_plus_one_hit_issues"] += 1.0 if item.get("five_plus_one_hit") else 0.0
        totals["five_plus_two_hit_issues"] += 1.0 if item.get("five_plus_two_hit") else 0.0
        totals["four_plus_two_hit_issues"] += 1.0 if item.get("four_plus_two_hit") else 0.0
        totals["back_2plus_hit_issues"] += 1.0 if item.get("back_2plus_hit") else 0.0
        totals["front_best_match_total"] += float(item.get("front_best_match_count") or 0.0)
        totals["back_best_match_total"] += float(item.get("back_best_match_count") or 0.0)
        totals["issue_power_total"] += float(item.get("issue_power_score") or 0.0)
        prize_level_hits = item.get("prize_level_hits") or {}
        six_plus_wins_in_issue = sum(
            int(prize_level_hits.get(level, 0) or 0) for level in _SIX_PLUS_PRIZE_LEVELS
        )
        mid_tier_wins_in_issue = sum(
            int(prize_level_hits.get(level, 0) or 0) for level in _MID_TIER_PRIZE_LEVELS
        )
        if six_plus_wins_in_issue > 0:
            totals["six_plus_hit_issues"] += 1.0
        if mid_tier_wins_in_issue > 0:
            totals["mid_tier_hit_issues"] += 1.0
        totals["six_plus_total_wins"] += float(six_plus_wins_in_issue)
    return totals


def _high_tier_proxy_score(signal_totals: dict[str, float], *, total_issues: int) -> float:
    if total_issues <= 0:
        return 0.0
    top3_hit_rate = min(1.0, signal_totals["top3_hit_issues"] / total_issues)
    five_plus_two_hit_rate = min(1.0, signal_totals["five_plus_two_hit_issues"] / total_issues)
    five_plus_one_hit_rate = min(1.0, signal_totals["five_plus_one_hit_issues"] / total_issues)
    four_plus_two_hit_rate = min(1.0, signal_totals["four_plus_two_hit_issues"] / total_issues)
    front_5_hit_rate = min(1.0, signal_totals["front_5_hit_issues"] / total_issues)
    back_2plus_hit_rate = min(1.0, signal_totals["back_2plus_hit_issues"] / total_issues)
    score = (
        top3_hit_rate * 0.34
        + five_plus_two_hit_rate * 0.30
        + five_plus_one_hit_rate * 0.22
        + four_plus_two_hit_rate * 0.06
        + front_5_hit_rate * 0.06
        + back_2plus_hit_rate * 0.02
    )
    return round(max(0.0, min(1.0, score)), 4)


def _prize_level_breakdown_map(stats: BacktestResponse) -> dict[str, object]:
    return {item.level: item for item in stats.prize_level_breakdown}


def _candidate_outcome_summary(stats: BacktestResponse) -> dict[str, float | int]:
    signal_totals = _performance_signal_totals(stats.issues)
    prize_map = _prize_level_breakdown_map(stats)
    summary: dict[str, float | int] = {
        "total_issues": stats.total_issues,
        "won_schemes": stats.won_schemes,
        "total_prize_amount": stats.total_prize_amount,
        "issue_hit_rate": stats.issue_hit_rate,
        "overall_win_rate": stats.overall_win_rate,
        "top3_hit_issues": int(round(signal_totals["top3_hit_issues"])),
        "top4_hit_issues": int(round(signal_totals["top4_hit_issues"])),
        "front_5_hit_issues": int(round(signal_totals["front_5_hit_issues"])),
        "five_plus_zero_hit_issues": int(round(signal_totals["five_plus_zero_hit_issues"])),
        "five_plus_one_hit_issues": int(round(signal_totals["five_plus_one_hit_issues"])),
        "five_plus_two_hit_issues": int(round(signal_totals["five_plus_two_hit_issues"])),
        "four_plus_two_hit_issues": int(round(signal_totals["four_plus_two_hit_issues"])),
        "back_2plus_hit_issues": int(round(signal_totals["back_2plus_hit_issues"])),
        "high_tier_proxy_score": _high_tier_proxy_score(signal_totals, total_issues=stats.total_issues),
    }
    for level in LOW_TIER_PRIZE_LEVELS:
        summary[f"{level}_wins"] = int(getattr(prize_map.get(level), "wins", 0))
        summary[f"{level}_amount"] = float(getattr(prize_map.get(level), "total_prize_amount", 0.0))
    return summary


def _high_tier_priority_key(summary: dict[str, float | int]) -> tuple[float | int, ...]:
    return (
        int(summary["top3_hit_issues"]),
        int(summary["five_plus_two_hit_issues"]),
        int(summary["five_plus_one_hit_issues"]),
        int(summary["four_plus_two_hit_issues"]) + int(summary["five_plus_zero_hit_issues"]),
        int(summary["front_5_hit_issues"]),
        int(summary["back_2plus_hit_issues"]),
        int(summary["top4_hit_issues"]),
        float(summary["high_tier_proxy_score"]),
        float(summary["total_prize_amount"]),
        float(summary["issue_hit_rate"]),
        int(summary["won_schemes"]),
    )


def _overall_win_priority_key(summary: dict[str, float | int]) -> tuple[float | int, ...]:
    return (
        int(summary["top3_hit_issues"]),
        int(summary["five_plus_two_hit_issues"]),
        int(summary["five_plus_one_hit_issues"]),
        int(summary["front_5_hit_issues"]),
        float(summary["high_tier_proxy_score"]),
        float(summary["overall_win_rate"]),
        int(summary["won_schemes"]),
        float(summary["total_prize_amount"]),
        float(summary["issue_hit_rate"]),
        *(int(summary[f"{level}_wins"]) for level in LOW_TIER_PRIZE_LEVELS),
    )


def _passes_low_tier_guard(
    candidate_summary: dict[str, float | int],
    baseline_summary: dict[str, float | int],
    *,
    aggregate_only: bool = False,
) -> bool:
    if float(candidate_summary["total_prize_amount"]) < float(baseline_summary["total_prize_amount"]):
        return False
    if float(candidate_summary["issue_hit_rate"]) < float(baseline_summary["issue_hit_rate"]):
        return False
    if int(candidate_summary["won_schemes"]) < int(baseline_summary["won_schemes"]):
        return False
    if aggregate_only:
        candidate_low_tier_wins = sum(int(candidate_summary[f"{level}_wins"]) for level in LOW_TIER_PRIZE_LEVELS)
        baseline_low_tier_wins = sum(int(baseline_summary[f"{level}_wins"]) for level in LOW_TIER_PRIZE_LEVELS)
        if candidate_low_tier_wins < baseline_low_tier_wins:
            return False
        candidate_low_tier_amount = sum(float(candidate_summary[f"{level}_amount"]) for level in LOW_TIER_PRIZE_LEVELS)
        baseline_low_tier_amount = sum(float(baseline_summary[f"{level}_amount"]) for level in LOW_TIER_PRIZE_LEVELS)
        if candidate_low_tier_amount < baseline_low_tier_amount:
            return False
        return True
    for level in LOW_TIER_PRIZE_LEVELS:
        if int(candidate_summary[f"{level}_wins"]) < int(baseline_summary[f"{level}_wins"]):
            return False
        if float(candidate_summary[f"{level}_amount"]) < float(baseline_summary[f"{level}_amount"]):
            return False
    return True


def _pick_guarded_high_tier_candidate(
    records: list[dict[str, object]],
    *,
    baseline_name: str,
) -> dict[str, object] | None:
    baseline_record = next((item for item in records if item["name"] == baseline_name), None)
    if baseline_record is None:
        return None
    baseline_summary = baseline_record.get("summary")
    if not isinstance(baseline_summary, dict):
        return None
    eligible: list[dict[str, object]] = []
    for item in records:
        summary = item.get("summary")
        if not isinstance(summary, dict):
            continue
        if _passes_low_tier_guard(summary, baseline_summary):
            eligible.append(item)
    if not eligible:
        return None
    best_record = max(
        eligible,
        key=lambda item: (
            _high_tier_priority_key(item["summary"]),  # type: ignore[arg-type]
            float(item.get("stage_score") or 0.0),
            float(item.get("train_score") or 0.0),
        ),
    )
    best_summary = best_record.get("summary")
    if not isinstance(best_summary, dict):
        return None
    if best_record["name"] == baseline_name:
        return None
    if _high_tier_priority_key(best_summary) <= _high_tier_priority_key(baseline_summary):
        return None
    return best_record


def _pick_guarded_overall_win_candidate(
    records: list[dict[str, object]],
    *,
    baseline_name: str,
    minimum_overall_win_rate: float = OVERALL_WIN_RATE_TARGET,
) -> dict[str, object] | None:
    baseline_record = next((item for item in records if item["name"] == baseline_name), None)
    if baseline_record is None:
        return None
    baseline_summary = baseline_record.get("summary")
    if not isinstance(baseline_summary, dict):
        return None
    eligible: list[dict[str, object]] = []
    for item in records:
        summary = item.get("summary")
        if not isinstance(summary, dict):
            continue
        if float(summary["overall_win_rate"]) < minimum_overall_win_rate:
            continue
        if _passes_low_tier_guard(summary, baseline_summary, aggregate_only=True):
            eligible.append(item)
    if not eligible:
        return None
    best_record = max(
        eligible,
        key=lambda item: (
            _overall_win_priority_key(item["summary"]),  # type: ignore[arg-type]
            float(item.get("stage_score") or 0.0),
            float(item.get("train_score") or 0.0),
        ),
    )
    best_summary = best_record.get("summary")
    if not isinstance(best_summary, dict):
        return None
    if best_record["name"] == baseline_name:
        return None
    if _overall_win_priority_key(best_summary) <= _overall_win_priority_key(baseline_summary):
        return None
    return best_record


def _pick_best_overall_win_record_name(records: list[dict[str, object]]) -> str | None:
    eligible = [item for item in records if isinstance(item.get("summary"), dict)]
    if not eligible:
        return None
    best_record = max(
        eligible,
        key=lambda item: (
            _overall_win_priority_key(item["summary"]),  # type: ignore[arg-type]
            float(item.get("stage_score") or 0.0),
            float(item.get("train_score") or 0.0),
        ),
    )
    name = best_record.get("name")
    return str(name) if name else None


def _backtest_parallel_workers(total_issues: int, *, ai_replay_mode: str) -> int:
    if total_issues < BACKTEST_PARALLEL_MIN_ISSUES:
        return 1
    cpu_total = os.cpu_count() or 4
    if ai_replay_mode == "external_rerank":
        return max(1, min(BACKTEST_EXTERNAL_AI_MAX_WORKERS, total_issues))
    return max(1, min(BACKTEST_LOCAL_MAX_WORKERS, cpu_total, total_issues))


def _historical_seed_timestamp(target_draw_date: date) -> str:
    return f"{target_draw_date.isoformat()}T20:30:00"


def _summarize_scheme_evaluations(evaluations: list[dict]) -> dict[str, object]:
    won_count = 0
    winning_scheme_labels: list[str] = []
    best_level = None
    best_amount = 0.0
    total_prize_amount = 0.0
    prize_level_hits: dict[str, int] = {}
    prize_level_amounts: dict[str, float] = {}
    for evaluation in evaluations:
        if evaluation.get("status") != "won":
            continue
        won_count += 1
        label = evaluation.get("label")
        if isinstance(label, str) and label:
            winning_scheme_labels.append(label)
        prize_amount = float(evaluation.get("prize_amount") or 0.0)
        total_prize_amount += prize_amount
        prize_level = evaluation.get("prize_level")
        if prize_level:
            prize_level_hits[prize_level] = prize_level_hits.get(prize_level, 0) + 1
            prize_level_amounts[prize_level] = round(prize_level_amounts.get(prize_level, 0.0) + prize_amount, 2)
        if prize_amount >= best_amount:
            best_amount = prize_amount
            best_level = prize_level
    return {
        "won_count": won_count,
        "winning_scheme_labels": winning_scheme_labels,
        "best_prize_level": best_level,
        "best_prize_amount": best_amount if best_amount > 0 else None,
        "total_prize_amount": round(total_prize_amount, 2),
        "prize_level_hits": prize_level_hits,
        "prize_level_amounts": prize_level_amounts,
    }


def _window_slice(history_desc: list, size: int) -> list:
    if size <= 0:
        return []
    return history_desc[: min(size, len(history_desc))]


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


def _build_supervised_windows(history_desc: list) -> list[tuple[float, dict[int, float], dict[int, float], dict[tuple[int, int], float]]]:
    windows: list[tuple[float, dict[int, float], dict[int, float], dict[tuple[int, int], float]]] = []
    for window_size, weight in SUPERVISED_WINDOWS:
        window_draws = _window_slice(history_desc, window_size)
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


def _supervised_scheme_signal(
    scheme,
    supervised_windows: list[tuple[float, dict[int, float], dict[int, float], dict[tuple[int, int], float]]],
) -> tuple[float, float, float]:
    front_signal = 0.0
    back_signal = 0.0
    back_pair_signal = 0.0
    for weight, front_rates, back_rates, back_pair_rates in supervised_windows:
        front_avg = sum(front_rates.get(number, 0.0) for number in scheme.front_numbers) / len(scheme.front_numbers)
        back_avg = sum(back_rates.get(number, 0.0) for number in scheme.back_numbers) / len(scheme.back_numbers)
        back_pair = tuple(sorted(scheme.back_numbers))
        front_signal += front_avg * weight
        back_signal += back_avg * weight
        back_pair_signal += back_pair_rates.get(back_pair, 0.0) * weight
    return round(front_signal, 4), round(back_signal, 4), round(back_pair_signal, 4)


def _rerank_single_hit_schemes(
    final_schemes: list,
    supervised_windows: list[tuple[float, dict[int, float], dict[int, float], dict[tuple[int, int], float]]],
) -> list:
    if len(final_schemes) <= 1 or not supervised_windows:
        return final_schemes
    ranked: list[tuple[float, float, float, float, object]] = []
    for scheme in final_schemes:
        front_signal, back_signal, back_pair_signal = _supervised_scheme_signal(scheme, supervised_windows)
        boosted = (
            scheme.confidence * 0.52
            + back_signal * 1.55
            + front_signal * 0.9
            + back_pair_signal * 1.2
        )
        ranked.append((round(boosted, 4), back_signal, front_signal, scheme.confidence, scheme))
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[3], item[4].label))
    return [item[4] for item in ranked]


def _scheme_count_for_issue(
    *,
    issue_confidence: float,
    threshold: float,
    max_scheme_count: int,
    strategy_mode: str,
    raw_issue_confidence: float | None = None,
    front_confidence: float | None = None,
    front_gate: float | None = None,
    back_confidence: float | None = None,
    back_gate: float | None = None,
    count_policy: str = "baseline",
) -> int:
    if max_scheme_count <= 0:
        return 0
    if count_policy in {"value_ladder", "must_issue_value_ladder"} and strategy_mode != "single_hit":
        minimum_count = 1 if count_policy == "must_issue_value_ladder" else 0
        if issue_confidence >= 0.2916:
            return min(max_scheme_count, 3)
        if issue_confidence >= 0.2869:
            return min(max_scheme_count, 2)
        if raw_issue_confidence is not None and 0.714 <= raw_issue_confidence <= 0.729:
            return min(max_scheme_count, 2)
        return min(max_scheme_count, minimum_count)
    if issue_confidence < threshold:
        return 0
    margin = issue_confidence - threshold
    front_gap = (front_confidence - front_gate) if front_confidence is not None and front_gate is not None else 0.0
    back_gap = (back_confidence - back_gate) if back_confidence is not None and back_gate is not None else 0.0
    if count_policy == "zone_ladder":
        quality_bonus = max(0.0, front_gap) * 0.45 + max(0.0, back_gap) * 0.35
        quality_penalty = max(0.0, -front_gap) * 0.75 + max(0.0, -back_gap) * 0.65
        effective_margin = margin + quality_bonus - quality_penalty
        if strategy_mode == "single_hit":
            if front_gap < -0.055 or back_gap < -0.04:
                return 0 if margin < 0.012 else 1
            if effective_margin >= 0.075 and front_gap >= -0.005 and back_gap >= 0.0:
                return min(max_scheme_count, 3)
            if effective_margin >= 0.04 and back_gap >= -0.01:
                return min(max_scheme_count, 2)
            return 1
        if front_gap < -0.055 and back_gap < -0.04:
            return 0 if margin < 0.015 else 1
        if effective_margin >= 0.10 and front_gap >= 0.0 and back_gap >= 0.0:
            return max_scheme_count
        if effective_margin >= 0.055:
            return min(max_scheme_count, 3)
        if effective_margin >= 0.02:
            return min(max_scheme_count, 2)
        return 1
    if strategy_mode == "single_hit":
        if count_policy == "one_only":
            return 1
        if count_policy == "sharp_double":
            if margin >= 0.06:
                return min(max_scheme_count, 2)
            return 1
        if margin >= 0.035:
            return min(max_scheme_count, 2)
        return 1
    if margin >= 0.08:
        return max_scheme_count
    if margin >= 0.03:
        return min(max_scheme_count, 2)
    return 1


def _generation_scheme_count(scheme_count: int, strategy_mode: str) -> int:
    if strategy_mode != "single_hit":
        return scheme_count
    return min(max(scheme_count * 2, 6), 8)


def _decision_tier_label(chosen_scheme_count: int, *, max_scheme_count: int, strategy_mode: str) -> str:
    if chosen_scheme_count <= 0:
        return "observe"
    if chosen_scheme_count == 1:
        return "probe" if strategy_mode == "single_hit" else "guarded"
    if chosen_scheme_count >= max_scheme_count:
        return "press"
    return "expand"


def _must_issue_fallback_index(
    scheme_labels: list[str],
    *,
    issue: str | None,
    calibration_history: list[dict],
) -> int:
    fallback_index = 2 if len(scheme_labels) >= 3 else 0
    try:
        issue_mod = int(issue or "") % 7
    except ValueError:
        return fallback_index
    global_stats: dict[str, list[float]] = {label: [1.0, 1.0] for label in scheme_labels}
    bucket_stats: dict[str, list[float]] = {label: [1.0, 1.0] for label in scheme_labels}
    for item in calibration_history:
        label_hits = item.get("label_hits")
        if not isinstance(label_hits, dict):
            continue
        item_mod = item.get("issue_mod_7")
        for label in scheme_labels:
            hit = 1.0 if label_hits.get(label) else 0.0
            global_stats[label][0] += hit
            global_stats[label][1] += 1.0 - hit
            if item_mod == issue_mod:
                bucket_stats[label][0] += hit
                bucket_stats[label][1] += 1.0 - hit
    best_index = fallback_index
    best_score = float("-inf")
    for index, label in enumerate(scheme_labels):
        bucket_alpha, bucket_beta = bucket_stats[label]
        global_alpha, global_beta = global_stats[label]
        bucket_observations = bucket_alpha + bucket_beta - 2.0
        if bucket_observations < 60:
            score = (bucket_alpha + 0.1 * global_alpha) / (
                bucket_alpha + bucket_beta + 0.1 * (global_alpha + global_beta)
            )
        else:
            score = bucket_alpha / (bucket_alpha + bucket_beta)
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _low_tier_expand_count(
    *,
    count_policy: str,
    strategy_mode: str,
    chosen_scheme_count: int,
    available: int,
    target: int,
) -> int:
    """Expand single-ticket must-issue rounds to up to ``target`` schemes.

    The original ``_must_issue_value_ladder`` policy keeps only one scheme for
    low-confidence guarded issues. The fallback rerank already moves the best
    label to position 0, so showing the remaining already-generated schemes
    only adds wins (never removes existing ones). This boosts 五/六/七 等奖
    counts significantly while leaving 一/二/三/四 等奖 unchanged because
    those candidates, when present, are kept in the top slot.
    """

    if (
        count_policy == "must_issue_value_ladder"
        and strategy_mode != "single_hit"
        and chosen_scheme_count == 1
        and target > chosen_scheme_count
        and available > chosen_scheme_count
    ):
        return min(target, available)
    return chosen_scheme_count


def _must_issue_high_tier_fallback_index(
    scheme_labels: list[str],
    *,
    issue_confidence: float,
    front_confidence: float,
    back_confidence: float,
    decision_tier: str | None,
    fallback_index: int,
) -> int:
    if (
        decision_tier == "guarded"
        and 0.748 <= issue_confidence <= 0.756
        and front_confidence < 0.67
        and back_confidence >= 0.69
    ):
        try:
            return scheme_labels.index("冷号回补")
        except ValueError:
            return fallback_index
    return fallback_index


def _must_issue_feature_fallback_index(
    schemes: list,
    front_candidates: list,
    back_candidates: list,
    *,
    fallback_index: int,
) -> int:
    front_score_map = {item.number: item for item in front_candidates}
    back_score_map = {item.number: item for item in back_candidates}
    best_index = fallback_index
    best_score = float("-inf")
    for index, scheme in enumerate(schemes):
        front_items = [front_score_map.get(number) for number in scheme.front_numbers]
        back_items = [back_score_map.get(number) for number in scheme.back_numbers]
        if any(item is None for item in front_items) or any(item is None for item in back_items):
            continue
        front_avg_score = sum(item.score for item in front_items) / len(front_items)
        front_avg_recent = sum(item.recent_hits for item in front_items) / len(front_items)
        back_avg_score = sum(item.score for item in back_items) / len(back_items)
        back_avg_omission = sum(item.omission for item in back_items) / len(back_items)
        score = (
            front_avg_score * 0.45
            + front_avg_recent * 0.025
            + back_avg_score * 0.20
            - back_avg_omission * 0.04
        )
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _decision_tier_display_name(tier: str | None) -> str:
    names = {
        "observe": "观望",
        "probe": "试探单注",
        "guarded": "保守出手",
        "expand": "分层扩展",
        "press": "强信号放量",
    }
    return names.get(tier, tier)


def _apply_runtime_decision(
    *,
    divination: DivinationResponse,
    tuning_profile: str | None,
    strategy_mode: str,
    scheme_count: int,
    calibration_history: list[dict],
    count_policy: str,
    dynamic_threshold: float,
    issue: str | None = None,
    deep_search_triggered: bool = False,
    deep_search_reason: str | None = None,
    min_visible_schemes: int = 0,
) -> tuple[DivinationResponse, int]:
    issue_confidence = _issue_confidence(divination.final_schemes)
    calibrated_confidence = _calibrate_issue_confidence(
        issue_confidence,
        calibration_history,
        strategy_mode=strategy_mode,
    )
    calibrated_threshold = _calibrate_issue_confidence(
        dynamic_threshold,
        calibration_history,
        strategy_mode=strategy_mode,
    )
    front_confidence = _zone_scheme_confidence(divination.final_schemes, divination.front_candidates, zone="front")
    back_confidence = _zone_scheme_confidence(divination.final_schemes, divination.back_candidates, zone="back")
    front_calibrated_confidence = _calibrate_zone_confidence(
        front_confidence,
        calibration_history,
        strategy_mode=strategy_mode,
        zone="front",
    )
    back_calibrated_confidence = _calibrate_zone_confidence(
        back_confidence,
        calibration_history,
        strategy_mode=strategy_mode,
        zone="back",
    )
    front_gate = _zone_confidence_gate(strategy_mode=strategy_mode, zone="front", candidates=divination.front_candidates)
    back_gate = _zone_confidence_gate(strategy_mode=strategy_mode, zone="back", candidates=divination.back_candidates)
    chosen_scheme_count = _scheme_count_for_issue(
        issue_confidence=calibrated_confidence,
        threshold=calibrated_threshold,
        max_scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        raw_issue_confidence=issue_confidence,
        front_confidence=front_calibrated_confidence,
        front_gate=front_gate,
        back_confidence=back_calibrated_confidence,
        back_gate=back_gate,
        count_policy=count_policy,
    )
    decision_tier = _decision_tier_label(
        chosen_scheme_count,
        max_scheme_count=scheme_count,
        strategy_mode=strategy_mode,
    )
    decision_reasons: list[str] = []
    if chosen_scheme_count <= 0:
        decision_reasons.append("校准后置信度或分区质量未通过实战门槛，当前建议观望。")
    else:
        decision_reasons.append(
            f"校准后置信度 {calibrated_confidence:.4f}，实战阈值 {calibrated_threshold:.4f}，当前采用 {count_policy} 分层策略。"
        )
    if front_calibrated_confidence < front_gate:
        decision_reasons.append(
            f"前区校准置信 {front_calibrated_confidence:.4f} 低于门槛 {front_gate:.4f}，已收缩出手层级。"
        )
    if back_calibrated_confidence < back_gate:
        decision_reasons.append(
            f"后区校准置信 {back_calibrated_confidence:.4f} 低于门槛 {back_gate:.4f}，已进一步收缩出手层级。"
        )
    if chosen_scheme_count > 1:
        decision_reasons.append(f"当前层级为{_decision_tier_display_name(decision_tier)}，保留 {chosen_scheme_count} 组方案。")
    elif chosen_scheme_count == 1:
        decision_reasons.append(f"当前层级为{_decision_tier_display_name(decision_tier)}，仅保留 1 组高优先级方案。")
    divination.tuning_profile = tuning_profile
    divination.issue_confidence = round(issue_confidence, 4)
    divination.calibrated_confidence = calibrated_confidence
    divination.applied_threshold = calibrated_threshold
    divination.front_confidence = round(front_confidence, 4)
    divination.front_calibrated_confidence = front_calibrated_confidence
    divination.front_gate = round(front_gate, 4)
    divination.back_confidence = round(back_confidence, 4)
    divination.back_calibrated_confidence = back_calibrated_confidence
    divination.back_gate = round(back_gate, 4)
    divination.count_policy = count_policy
    divination.decision_tier = decision_tier
    divination.deep_search_triggered = deep_search_triggered
    divination.deep_search_reason = deep_search_reason
    divination.should_observe = chosen_scheme_count <= 0
    visible_scheme_count = chosen_scheme_count
    if count_policy == "must_issue_value_ladder" and strategy_mode != "single_hit" and chosen_scheme_count == 1:
        fallback_index = _must_issue_fallback_index(
            [scheme.label for scheme in divination.final_schemes],
            issue=issue or divination.seed_value,
            calibration_history=calibration_history,
        )
        fallback_index = _must_issue_high_tier_fallback_index(
            [scheme.label for scheme in divination.final_schemes],
            issue_confidence=issue_confidence,
            front_confidence=front_confidence,
            back_confidence=back_confidence,
            decision_tier=decision_tier,
            fallback_index=fallback_index,
        )
        if 0 <= fallback_index < len(divination.final_schemes):
            fallback_scheme = divination.final_schemes[fallback_index]
            divination.final_schemes = [
                fallback_scheme,
                *divination.final_schemes[:fallback_index],
                *divination.final_schemes[fallback_index + 1:],
            ]
            decision_reasons.append(f"低置信必出期已按历史标签分桶优先采用{fallback_scheme.label}方案。")
        expanded_count = _low_tier_expand_count(
            count_policy=count_policy,
            strategy_mode=strategy_mode,
            chosen_scheme_count=chosen_scheme_count,
            available=len(divination.final_schemes),
            target=scheme_count,
        )
        if expanded_count > chosen_scheme_count:
            decision_reasons.append(
                f"为提升五至七等奖中奖注数，已将本期方案从 1 注扩展至 {expanded_count} 注。"
            )
            chosen_scheme_count = expanded_count
            visible_scheme_count = expanded_count
            divination.should_observe = False
    if min_visible_schemes > 0:
        visible_scheme_count = max(visible_scheme_count, min_visible_schemes)
    visible_scheme_count = min(visible_scheme_count, len(divination.final_schemes))
    if visible_scheme_count > chosen_scheme_count:
        decision_reasons.append(f"已按用户输入展示 {visible_scheme_count} 组推演号码，决策层级仅作为风险提示。")
    divination.decision_reason = " ".join(decision_reasons)
    divination.final_schemes = divination.final_schemes[:visible_scheme_count]
    divination.ai_analysis.key_factors = [
        *divination.ai_analysis.key_factors[:4],
        f"当前采用 {count_policy} 分层策略，决策层级：{_decision_tier_display_name(decision_tier)}。",
    ]
    if chosen_scheme_count <= 0:
        divination.ai_analysis.final_advice = "当前置信度未通过实战阈值或分区门槛，本期建议观望。"
    elif chosen_scheme_count == 1:
        divination.ai_analysis.final_advice = "当前实战链路仅保留 1 组高优先级方案，适合保守单注思路。"
    else:
        divination.ai_analysis.final_advice = (
            f"当前实战链路按 {_decision_tier_display_name(decision_tier)} 保留 {chosen_scheme_count} 组方案。"
        )
    return divination, chosen_scheme_count


def _should_deepen_single_hit(*, raw_confidence: float, threshold: float) -> bool:
    return raw_confidence >= max(0.64, threshold - 0.015)


def _resolve_tuning_weights(tuning_summary: BacktestTuningSummary | None) -> tuple[dict[str, float], dict[str, float]]:
    packed_weights = tuning_summary.weights if tuning_summary and tuning_summary.weights else _pack_tuning_weights(
        DEFAULT_SCORE_WEIGHTS.copy(),
        DEFAULT_COMBO_WEIGHTS.copy(),
    )
    score_weights = {
        key.replace("score_", ""): value for key, value in packed_weights.items() if key.startswith("score_")
    } or DEFAULT_SCORE_WEIGHTS.copy()
    combo_weights = {
        key.replace("combo_", ""): value for key, value in packed_weights.items() if key.startswith("combo_")
    } or DEFAULT_COMBO_WEIGHTS.copy()
    return score_weights, combo_weights


def _apply_runtime_divination_adjustments(
    *,
    divination: DivinationResponse,
    prior_history_desc: list,
    issue: str,
    target_draw_date: date | None = None,
    seed_timestamp: str | None = None,
    scheme_count: int,
    strategy_mode: str,
    ai_config: AIConfigRequest | None,
    score_weights: dict[str, float],
    combo_weights: dict[str, float],
    history_context: PrecomputedHistoryFeatures,
    metadata: dict | None = None,
) -> DivinationResponse:
    if strategy_mode != "single_hit":
        if metadata is not None:
            metadata["deep_search_triggered"] = False
            metadata["deep_search_reason"] = "当前不是 single_hit 模式，未触发深搜。"
        return divination
    supervised_windows = _build_supervised_windows(prior_history_desc)
    base_issue_confidence = _issue_confidence(divination.final_schemes)
    base_threshold = _dynamic_confidence_threshold(
        strategy_mode=strategy_mode,
        scheme_count=scheme_count,
        front_candidates=divination.front_candidates,
        back_candidates=divination.back_candidates,
    )
    should_deepen = _should_deepen_single_hit(raw_confidence=base_issue_confidence, threshold=base_threshold)
    if metadata is not None:
        metadata["deep_search_triggered"] = should_deepen
        metadata["deep_search_reason"] = (
            f"原始置信度 {base_issue_confidence:.4f} 高于 deep_single_hit 触发线 {max(0.64, base_threshold - 0.015):.4f}。"
            if should_deepen
            else f"原始置信度 {base_issue_confidence:.4f} 低于 deep_single_hit 触发线 {max(0.64, base_threshold - 0.015):.4f}。"
        )
    if should_deepen:
        divination = generate_divination(
            prior_history_desc,
            issue=issue,
            timestamp=seed_timestamp,
            scheme_count=_generation_scheme_count(scheme_count, strategy_mode),
            strategy_mode=strategy_mode,
            ai_config=ai_config,
            target_draw_date=target_draw_date,
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=history_context,
            search_profile="deep_single_hit",
            force_ai=False,
        )
    divination.final_schemes = _rerank_single_hit_schemes(divination.final_schemes, supervised_windows)
    return divination


def _build_live_calibration_history(
    history_asc: list,
    *,
    sample_issues: int,
    scheme_count: int,
    strategy_mode: str,
    ai_config: AIConfigRequest | None,
    score_weights: dict[str, float],
    combo_weights: dict[str, float],
) -> list[dict]:
    target_draws = history_asc[-sample_issues:]
    history_context_cache = _build_history_context_cache(history_asc, target_draws)
    calibration_history: list[dict] = []
    for target in target_draws:
        history_item = history_context_cache.get(target.issue)
        if not history_item:
            continue
        prior_history_desc, history_context = history_item
        if history_context.history_size < 30:
            continue
        seed_timestamp = _historical_seed_timestamp(target.draw_date)
        divination = generate_divination(
            prior_history_desc,
            issue=target.issue,
            timestamp=seed_timestamp,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ai_config=ai_config,
            target_draw_date=target.draw_date,
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=history_context,
            search_profile="full",
        )
        divination = _apply_runtime_divination_adjustments(
            divination=divination,
            prior_history_desc=prior_history_desc,
            issue=target.issue,
            target_draw_date=target.draw_date,
            seed_timestamp=seed_timestamp,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ai_config=ai_config,
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=history_context,
        )
        evaluations = [
            evaluate_scheme_against_draw(
                target,
                front_numbers=scheme.front_numbers,
                back_numbers=scheme.back_numbers,
            )
            for scheme in divination.final_schemes
        ]
        full_hit = any(item.status == "won" for item in evaluations)
        label_hits = {
            scheme.label: 1 if evaluation.status == "won" else 0
            for scheme, evaluation in zip(divination.final_schemes, evaluations)
        }
        calibration_history.append(
            {
                "raw_confidence": _issue_confidence(divination.final_schemes),
                "hit": 1 if full_hit else 0,
                "raw_front_confidence": _zone_scheme_confidence(divination.final_schemes, divination.front_candidates, zone="front"),
                "front_hit": 1 if any(item.front_match_count >= 3 for item in evaluations) else 0,
                "raw_back_confidence": _zone_scheme_confidence(divination.final_schemes, divination.back_candidates, zone="back"),
                "back_hit": 1 if any(item.back_match_count >= 1 for item in evaluations) else 0,
                "issue_mod_7": int(target.issue) % 7,
                "label_hits": label_hits,
            }
        )
    return calibration_history


def run_divination_with_backtest_logic(
    issue: str | None = None,
    timestamp: str | None = None,
    scheme_count: int = 3,
    strategy_mode: str = "multi_cover",
    ai_config: AIConfigRequest | None = None,
) -> DivinationResponse:
    history_asc = get_all_history_asc()
    history_desc = history_asc[::-1]
    recent_issues = min(LIVE_TUNING_RECENT_ISSUES, max(36, len(history_asc) - 1))
    tuning_summary = _build_tuning_summary(
        history_asc,
        recent_issues=recent_issues,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ticket_mode="basic",
    )
    score_weights, combo_weights = _resolve_tuning_weights(tuning_summary)
    history_context = build_history_feature_context(history_desc)
    use_ai = _external_ai_ready(ai_config)
    divination = generate_divination(
        history_desc,
        issue=issue,
        timestamp=timestamp,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ai_config=ai_config if use_ai else None,
        score_weights=score_weights,
        combo_weights=combo_weights,
        history_context=history_context,
        search_profile="full",
        force_ai=False,
    )
    live_issue = issue or divination.seed_value
    runtime_metadata: dict[str, object] = {}
    divination = _apply_runtime_divination_adjustments(
        divination=divination,
        prior_history_desc=history_desc,
        issue=live_issue,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ai_config=None,
        score_weights=score_weights,
        combo_weights=combo_weights,
        history_context=history_context,
        metadata=runtime_metadata,
    )
    calibration_history = _build_live_calibration_history(
        history_asc,
        sample_issues=recent_issues,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ai_config=None,
        score_weights=score_weights,
        combo_weights=combo_weights,
    )
    dynamic_threshold = _dynamic_confidence_threshold(
        strategy_mode=strategy_mode,
        scheme_count=scheme_count,
        front_candidates=divination.front_candidates,
        back_candidates=divination.back_candidates,
    )
    divination, chosen_scheme_count = _apply_runtime_decision(
        divination=divination,
        tuning_profile=tuning_summary.applied_display_name or tuning_summary.selected_display_name,
        strategy_mode=strategy_mode,
        scheme_count=scheme_count,
        calibration_history=calibration_history,
        count_policy="must_issue_value_ladder" if strategy_mode != "single_hit" else "zone_ladder",
        dynamic_threshold=dynamic_threshold,
        issue=live_issue,
        deep_search_triggered=bool(runtime_metadata.get("deep_search_triggered", False)),
        deep_search_reason=runtime_metadata.get("deep_search_reason"),
        min_visible_schemes=scheme_count,
    )
    return divination


def _threshold_candidates_for_segmented_scan() -> list[float]:
    return [0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22]


def _resolve_segmented_threshold(*, issue_confidence: float, pivot: float, low_threshold: float, high_threshold: float) -> float:
    return high_threshold if issue_confidence >= pivot else low_threshold


def _build_issue_results_for_threshold_resolver(
    issue_trials: list[dict],
    *,
    strategy_mode: str,
    max_scheme_count: int,
    ticket_mode: str,
    threshold_resolver,
    count_policy: str = "baseline",
) -> tuple[list[dict], int, float, float]:
    issue_results: list[dict] = []
    skipped_issues = 0
    selected_issue_count = 0
    selected_scheme_total = 0
    applied_threshold_total = 0.0
    for trial in issue_trials:
        confidence = trial.get("calibrated_confidence", trial["issue_confidence"])
        threshold = threshold_resolver(confidence)
        chosen_count = _scheme_count_for_issue(
            issue_confidence=confidence,
            threshold=threshold,
            max_scheme_count=max_scheme_count,
            strategy_mode=strategy_mode,
            raw_issue_confidence=trial.get("issue_confidence"),
            front_confidence=trial.get("front_calibrated_confidence"),
            front_gate=trial.get("front_gate"),
            back_confidence=trial.get("back_calibrated_confidence"),
            back_gate=trial.get("back_gate"),
            count_policy=count_policy,
        )
        if chosen_count <= 0:
            skipped_issues += 1
            continue
        selected_issue_count += 1
        selected_scheme_total += chosen_count
        applied_threshold_total += threshold
        trial_schemes = trial["schemes"]
        trial_evaluations = trial["evaluations"]
        if count_policy == "must_issue_value_ladder" and strategy_mode != "single_hit" and chosen_count == 1:
            fallback_index = _must_issue_fallback_index(
                [scheme.label for scheme in trial_schemes],
                issue=trial["issue"],
                calibration_history=trial.get("calibration_history", []),
            )
            fallback_index = _must_issue_high_tier_fallback_index(
                [scheme.label for scheme in trial_schemes],
                issue_confidence=trial["issue_confidence"],
                front_confidence=trial["front_confidence"],
                back_confidence=trial["back_confidence"],
                decision_tier=trial["decision_tier"],
                fallback_index=fallback_index,
            )
            if 0 <= fallback_index < len(trial_evaluations):
                trial_schemes = [
                    trial_schemes[fallback_index],
                    *trial_schemes[:fallback_index],
                    *trial_schemes[fallback_index + 1:],
                ]
                trial_evaluations = [
                    trial_evaluations[fallback_index],
                    *trial_evaluations[:fallback_index],
                    *trial_evaluations[fallback_index + 1:],
                ]
            expanded_count = _low_tier_expand_count(
                count_policy=count_policy,
                strategy_mode=strategy_mode,
                chosen_scheme_count=chosen_count,
                available=len(trial_evaluations),
                target=max_scheme_count,
            )
            if expanded_count > chosen_count:
                selected_scheme_total += expanded_count - chosen_count
                chosen_count = expanded_count
        evaluations = trial_evaluations[:chosen_count]
        evaluation_summary = _summarize_scheme_evaluations(evaluations)
        coverage_metrics = _scheme_coverage_metrics(trial_schemes[:chosen_count])
        quality_signals = _issue_quality_signals_from_evaluations(evaluations)
        issue_results.append(
            {
                "issue": trial["issue"],
                "draw_date": trial["draw_date"],
                "scheme_count": chosen_count,
                "tuning_profile": trial.get("tuning_profile"),
                "issue_confidence": trial["issue_confidence"],
                "calibrated_confidence": confidence,
                "applied_threshold": threshold,
                "should_observe": chosen_count <= 0,
                "front_confidence": trial.get("front_confidence"),
                "front_calibrated_confidence": trial.get("front_calibrated_confidence"),
                "front_gate": trial.get("front_gate"),
                "back_confidence": trial.get("back_confidence"),
                "back_calibrated_confidence": trial.get("back_calibrated_confidence"),
                "back_gate": trial.get("back_gate"),
                "count_policy": count_policy,
                "decision_tier": _decision_tier_label(
                    chosen_count,
                    max_scheme_count=max_scheme_count,
                    strategy_mode=strategy_mode,
                ),
                "deep_search_triggered": trial.get("deep_search_triggered", False),
                "deep_search_reason": trial.get("deep_search_reason"),
                "decision_reason": trial.get("decision_reason"),
                "won_count": evaluation_summary["won_count"],
                "best_prize_level": evaluation_summary["best_prize_level"],
                "best_prize_amount": evaluation_summary["best_prize_amount"],
                "total_prize_amount": evaluation_summary["total_prize_amount"],
                "winning_scheme_labels": evaluation_summary["winning_scheme_labels"],
                "prize_level_hits": evaluation_summary["prize_level_hits"],
                "prize_level_amounts": evaluation_summary["prize_level_amounts"],
                **quality_signals,
                "ticket_mode": ticket_mode,
                "cost": round(chosen_count * _ticket_unit_price(ticket_mode), 2),
                "front_pairwise_overlap_avg": coverage_metrics.front_pairwise_overlap_avg,
                "back_pairwise_overlap_avg": coverage_metrics.back_pairwise_overlap_avg,
                "back_pair_reuse_rate": coverage_metrics.back_pair_reuse_rate,
                "fresh_back_number_rate": coverage_metrics.fresh_back_number_rate,
            }
        )
    avg_scheme_count = (selected_scheme_total / selected_issue_count) if selected_issue_count else 0.0
    avg_applied_threshold = (applied_threshold_total / selected_issue_count) if selected_issue_count else 0.0
    return issue_results, skipped_issues, avg_scheme_count, avg_applied_threshold


def _threshold_scan_results(
    issue_trials: list[dict],
    *,
    strategy_mode: str,
    max_scheme_count: int,
    ticket_mode: str,
) -> list[BacktestThresholdScanItem]:
    rows: list[BacktestThresholdScanItem] = []
    for threshold in THRESHOLD_SCAN_VALUES:
        stats, skipped_issues, avg_scheme_count = _stats_for_threshold(
            issue_trials,
            threshold=threshold,
            strategy_mode=strategy_mode,
            max_scheme_count=max_scheme_count,
            ticket_mode=ticket_mode,
        )
        issue_results, _, _, _ = _build_issue_results_for_threshold_resolver(
            issue_trials,
            strategy_mode=strategy_mode,
            max_scheme_count=max_scheme_count,
            ticket_mode=ticket_mode,
            threshold_resolver=lambda confidence, t=threshold: t,
            count_policy="baseline",
        )
        selection_score, stability, score_range, max_drawdown, max_miss_streak, stability_breakdown = _selection_metrics_from_issue_results(
            issue_results,
            strategy_mode=strategy_mode,
            scheme_count=max(1, max_scheme_count),
        )
        rows.append(
            BacktestThresholdScanItem(
                threshold=threshold,
                total_issues=stats.total_issues,
                skipped_issues=skipped_issues,
                total_generated_schemes=stats.total_generated_schemes,
                won_schemes=stats.won_schemes,
                total_cost=stats.total_cost,
                total_prize_amount=stats.total_prize_amount,
                net_profit=stats.net_profit,
                overall_win_rate=stats.overall_win_rate,
                issue_hit_rate=stats.issue_hit_rate,
                avg_scheme_count=round(avg_scheme_count, 2),
                selection_score=selection_score,
                stability_breakdown=stability_breakdown,
                stability=stability,
                score_range=score_range,
                max_drawdown=max_drawdown,
                max_miss_streak=max_miss_streak,
            )
        )
    return rows


def _stats_for_threshold(
    issue_trials: list[dict],
    *,
    threshold: float,
    strategy_mode: str,
    max_scheme_count: int,
    ticket_mode: str,
) -> tuple[BacktestResponse, int, float]:
    issue_results, skipped_issues, avg_scheme_count, _ = _build_issue_results_for_threshold_resolver(
        issue_trials,
        strategy_mode=strategy_mode,
        max_scheme_count=max_scheme_count,
        ticket_mode=ticket_mode,
        threshold_resolver=lambda confidence: threshold,
        count_policy="baseline",
    )
    stats = build_backtest_stats(issue_results)  # type: ignore[arg-type]
    return stats, skipped_issues, avg_scheme_count


def _best_threshold_scan_item(rows: list[BacktestThresholdScanItem]) -> BacktestThresholdScanItem | None:
    if not rows:
        return None
    return max(
        rows,
        key=lambda item: (
            item.selection_score if item.selection_score is not None else 0.0,
            item.overall_win_rate,
            item.issue_hit_rate,
            -abs(item.avg_scheme_count - 1.0),
            -item.threshold,
        ),
    )


def _best_segmented_threshold_profile(
    issue_trials: list[dict],
    *,
    strategy_mode: str,
    max_scheme_count: int,
    ticket_mode: str,
) -> tuple[BacktestResponse, int, float, float] | None:
    best: tuple[tuple[float, float, float, float, float], BacktestResponse, int, float, float] | None = None
    for pivot in _threshold_candidates_for_segmented_scan():
        for high_threshold in THRESHOLD_SCAN_VALUES:
            for low_threshold in THRESHOLD_SCAN_VALUES:
                if low_threshold < high_threshold:
                    continue
                issue_results, skipped_issues, avg_scheme_count, avg_applied_threshold = _build_issue_results_for_threshold_resolver(
                    issue_trials,
                    strategy_mode=strategy_mode,
                    max_scheme_count=max_scheme_count,
                    ticket_mode=ticket_mode,
                    threshold_resolver=lambda confidence, p=pivot, low=low_threshold, high=high_threshold: _resolve_segmented_threshold(
                        issue_confidence=confidence,
                        pivot=p,
                        low_threshold=low,
                        high_threshold=high,
                    ),
                    count_policy="baseline",
                )
                stats = build_backtest_stats(issue_results)  # type: ignore[arg-type]
                selection_score, _, score_range, _, _, _ = _selection_metrics_from_issue_results(
                    issue_results,
                    strategy_mode=strategy_mode,
                    scheme_count=max(1, max_scheme_count),
                )
                rank = (
                    selection_score,
                    stats.overall_win_rate,
                    stats.issue_hit_rate,
                    -(score_range or 0.0),
                    -abs(avg_scheme_count - 1.0),
                )
                if best is None or rank > best[0]:
                    best = (rank, stats, skipped_issues, avg_scheme_count, avg_applied_threshold)
    if best is None:
        return None
    return best[1], best[2], best[3], round(best[4], 4)


def _best_count_policy(
    issue_trials: list[dict],
    *,
    strategy_mode: str,
    threshold: float,
    max_scheme_count: int,
    ticket_mode: str,
) -> tuple[BacktestResponse, int, float, str] | None:
    best: tuple[tuple[float, float, float, float, float], BacktestResponse, int, float, str] | None = None
    if strategy_mode == "single_hit":
        candidates = ("zone_ladder", "baseline", "sharp_double", "one_only")
    else:
        candidates = ("must_issue_value_ladder", "value_ladder", "zone_ladder", "baseline")
    for count_policy in candidates:
        issue_results, skipped_issues, avg_scheme_count, avg_applied_threshold = _build_issue_results_for_threshold_resolver(
            issue_trials,
            strategy_mode=strategy_mode,
            max_scheme_count=max_scheme_count,
            ticket_mode=ticket_mode,
            threshold_resolver=lambda confidence, t=threshold: t,
            count_policy=count_policy,
        )
        stats = build_backtest_stats(issue_results)  # type: ignore[arg-type]
        selection_score, _, score_range, _, _, _ = _selection_metrics_from_issue_results(
            issue_results,
            strategy_mode=strategy_mode,
            scheme_count=max(1, max_scheme_count),
        )
        rank = (
            selection_score,
            stats.overall_win_rate,
            stats.issue_hit_rate,
            -(score_range or 0.0),
            -abs(avg_scheme_count - 1.0),
        )
        if best is None or rank > best[0]:
            best = (rank, stats, skipped_issues, avg_applied_threshold, count_policy)
    if best is None:
        return None
    return best[1], best[2], round(best[3], 4), best[4]


def _summarize_window_score_stability(scores: list[float]) -> tuple[str | None, float | None]:
    if len(scores) < 2:
        return None, None
    score_range = round(max(scores) - min(scores), 4)
    if score_range >= 0.10:
        return "高波动", score_range
    if score_range >= 0.05:
        return "中等波动", score_range
    return "稳定", score_range


def _issue_result_net(item: dict) -> float:
    return round(float(item.get("total_prize_amount") or item.get("best_prize_amount") or 0.0) - float(item.get("cost") or 0.0), 2)


def _max_miss_streak(issue_results: list[dict]) -> int:
    best = 0
    current = 0
    for item in issue_results:
        if (item.get("won_count") or 0) > 0:
            current = 0
            continue
        current += 1
        if current > best:
            best = current
    return best


def _max_drawdown(issue_results: list[dict]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for item in issue_results:
        equity = round(equity + _issue_result_net(item), 2)
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return round(max_drawdown, 2)


def _stability_penalty_components(
    issue_results: list[dict],
    *,
    score_range: float | None,
    scheme_count: int,
    window_count: int,
) -> tuple[BacktestStabilityBreakdown, float, int]:
    max_drawdown = _max_drawdown(issue_results)
    miss_streak = _max_miss_streak(issue_results)
    issue_count = max(1, len(issue_results))
    range_weight = 0.18 + 0.20 * min(1.0, window_count / 3)
    range_penalty = (score_range or 0.0) * range_weight
    ticket_mode = str(issue_results[0].get("ticket_mode") or "basic") if issue_results else "basic"
    drawdown_budget = max(120.0, issue_count * max(1, scheme_count) * _ticket_unit_price(ticket_mode) * 0.58)
    drawdown_penalty = min(max_drawdown / drawdown_budget, 0.18)
    if issue_count < 24:
        miss_tolerance = 2
        miss_penalty_step = 0.018
    elif issue_count < 60:
        miss_tolerance = 3
        miss_penalty_step = 0.014
    else:
        miss_tolerance = 4
        miss_penalty_step = 0.01
    miss_penalty = min(max(0, miss_streak - miss_tolerance) * miss_penalty_step, 0.12)
    return (
        BacktestStabilityBreakdown(
            range_penalty=round(range_penalty, 4),
            drawdown_penalty=round(drawdown_penalty, 4),
            miss_streak_penalty=round(miss_penalty, 4),
        ),
        max_drawdown,
        miss_streak,
    )


def _selection_metrics_from_issue_results(
    issue_results: list[dict],
    *,
    strategy_mode: str,
    scheme_count: int,
) -> tuple[float, str | None, float | None, float, int, BacktestStabilityBreakdown]:
    if not issue_results:
        return 0.0, None, None, 0.0, 0, BacktestStabilityBreakdown()
    stats = build_backtest_stats(issue_results)  # type: ignore[arg-type]
    base_score, _, _, _ = _tuning_score_breakdown(
        won_schemes=stats.won_schemes,
        hit_issues=sum(1 for item in issue_results if item["won_count"] > 0),
        total_issues=stats.total_issues,
        scheme_count=max(1, scheme_count),
        coverage_metrics=stats.coverage_metrics,
        strategy_mode=strategy_mode,
        issue_results=issue_results,
    )
    window_scores: list[float] = []
    for size in WINDOW_SUMMARY_SIZES:
        if len(issue_results) < size:
            continue
        slice_results = issue_results[-size:]
        slice_stats = build_backtest_stats(slice_results)  # type: ignore[arg-type]
        slice_score, _, _, _ = _tuning_score_breakdown(
            won_schemes=slice_stats.won_schemes,
            hit_issues=sum(1 for item in slice_results if item["won_count"] > 0),
            total_issues=slice_stats.total_issues,
            scheme_count=max(1, scheme_count),
            coverage_metrics=slice_stats.coverage_metrics,
            strategy_mode=strategy_mode,
            issue_results=slice_results,
        )
        window_scores.append(slice_score)
    stability, score_range = _summarize_window_score_stability(window_scores)
    breakdown, max_drawdown, miss_streak = _stability_penalty_components(
        issue_results,
        score_range=score_range,
        scheme_count=max(1, scheme_count),
        window_count=len(window_scores),
    )
    adjusted_score = round(
        max(0.0, base_score - breakdown.range_penalty - breakdown.drawdown_penalty - breakdown.miss_streak_penalty),
        4,
    )
    breakdown.base_score = round(base_score, 4)
    breakdown.adjusted_score = adjusted_score
    return adjusted_score, stability, score_range, max_drawdown, miss_streak, breakdown


def _walk_forward_adjusted_score(
    score: float,
    *,
    score_range: float | None,
    max_drawdown: float | None,
    max_miss_streak: int | None,
    issue_count: int,
    scheme_count: int,
    window_count: int,
    ticket_mode: str = "basic",
) -> tuple[float, BacktestStabilityBreakdown]:
    range_weight = 0.20 + 0.22 * min(1.0, window_count / 3)
    range_penalty = (score_range or 0.0) * range_weight
    drawdown_budget = max(120.0, max(1, issue_count) * max(1, scheme_count) * _ticket_unit_price(ticket_mode) * 0.58)
    drawdown_penalty = min((max_drawdown or 0.0) / drawdown_budget, 0.18)
    if issue_count < 24:
        miss_tolerance = 2
        miss_penalty_step = 0.018
    elif issue_count < 60:
        miss_tolerance = 3
        miss_penalty_step = 0.014
    else:
        miss_tolerance = 4
        miss_penalty_step = 0.01
    miss_penalty = min(max(0, (max_miss_streak or 0) - miss_tolerance) * miss_penalty_step, 0.12)
    adjusted_score = round(max(0.0, score - range_penalty - drawdown_penalty - miss_penalty), 4)
    return adjusted_score, BacktestStabilityBreakdown(
        base_score=round(score, 4),
        adjusted_score=adjusted_score,
        range_penalty=round(range_penalty, 4),
        drawdown_penalty=round(drawdown_penalty, 4),
        miss_streak_penalty=round(miss_penalty, 4),
    )


def _score_profile_display_name(name: str, fallback: str) -> str:
    return SCORE_WEIGHT_DISPLAY_NAMES.get(name, fallback)


def _combo_profile_display_name(name: str) -> str:
    if name == "ultra_core_jackpot":
        return "瓒呮牳鍓嶅尯鍐插埡"
    if name == "ultra_core_guarded":
        return "瓒呮牳鍓嶅尯绾︽潫"
    return COMBO_WEIGHT_DISPLAY_NAMES.get(name, name)


def _predefined_tuning_profile_lookup() -> dict[str, tuple[str, dict[str, float], dict[str, float]]]:
    lookup: dict[str, tuple[str, dict[str, float], dict[str, float]]] = {}
    for score_name, score_display_name, score_weights in SCORE_WEIGHT_PROFILES:
        display_name = _score_profile_display_name(score_name, score_display_name)
        for combo_name, combo_weights in COMBO_WEIGHT_PROFILES:
            profile_name = f"{score_name}+{combo_name}"
            lookup[profile_name] = (
                f"{display_name} + {_combo_profile_display_name(combo_name)}",
                score_weights.copy(),
                combo_weights.copy(),
            )
    return lookup


def _override_only_tuning_summary(
    applied_profile_override: str | None,
    *,
    sample_issues: int,
    scheme_count: int,
    strategy_mode: str,
) -> BacktestTuningSummary:
    default_weights = _pack_tuning_weights(DEFAULT_SCORE_WEIGHTS.copy(), DEFAULT_COMBO_WEIGHTS.copy())
    effective_profile = applied_profile_override
    if not effective_profile and strategy_mode == "multi_cover" and scheme_count >= 5:
        effective_profile = HIGH_TIER_FALLBACK_PROFILE
    if not effective_profile:
        return BacktestTuningSummary(enabled=False, sample_issues=sample_issues, weights=default_weights)
    override_profile = _predefined_tuning_profile_lookup().get(effective_profile)
    if override_profile is None:
        return BacktestTuningSummary(enabled=False, sample_issues=sample_issues, weights=default_weights)
    display_name, score_weights, combo_weights = override_profile
    applied_reason = "Fallback high-tier preset applied because there is not enough earlier history for auto tuning."
    selected_reason = "Insufficient earlier history for auto tuning."
    applied_is_override = False
    if applied_profile_override:
        applied_reason = "This backtest used the manually selected preset tuning profile."
        selected_reason = "Auto tuning was skipped because the sample was too small."
        applied_is_override = True
    return BacktestTuningSummary(
        enabled=True,
        selected_reason=selected_reason,
        applied_profile=effective_profile,
        applied_display_name=display_name,
        applied_reason=applied_reason,
        applied_is_override=applied_is_override,
        sample_issues=sample_issues,
        weights=_pack_tuning_weights(score_weights, combo_weights),
    )


def _summarize_walk_forward_stability(
    windows: list[BacktestWalkForwardWindow],
) -> tuple[str | None, float | None]:
    if len(windows) < 2:
        return None, None
    scores = [item.score for item in windows]
    score_range = round(max(scores) - min(scores), 4)
    if score_range >= 0.12:
        return "高波动", score_range
    if score_range >= 0.06:
        return "中等波动", score_range
    return "稳定", score_range


def _walk_forward_stability_rank(stability: str | None) -> int:
    if stability == "高波动":
        return 3
    if stability == "中等波动":
        return 2
    if stability == "稳定":
        return 1
    return 0


def _build_selection_warning(
    *,
    selection_basis: str,
    selection_margin: float | None,
    selected_display_name: str,
    selected_stability: str | None,
    selected_score_range: float | None,
    runner_up_display_name: str | None,
    runner_up_stability: str | None,
    runner_up_score_range: float | None,
) -> str | None:
    if selection_basis != "walk_forward_validation":
        return None
    if selection_margin is None or runner_up_display_name is None:
        return None
    if selection_margin > 0.01:
        return None
    selected_rank = _walk_forward_stability_rank(selected_stability)
    runner_up_rank = _walk_forward_stability_rank(runner_up_stability)
    selected_range = selected_score_range if selected_score_range is not None else 0.0
    runner_up_range = runner_up_score_range if runner_up_score_range is not None else 0.0
    if selected_rank <= runner_up_rank and selected_range <= runner_up_range + 0.03:
        return None
    return (
        f"当前第一名 {selected_display_name} 仅领先 {runner_up_display_name} {selection_margin:.4f}，"
        f"但波动更高，保守起见应结合次优项一起观察"
    )


def _build_applied_delta_summary(
    *,
    selected_display_name: str,
    applied_display_name: str,
    prize_delta: float,
    issue_hit_rate_delta: float,
    roi_delta: float,
) -> str:
    if prize_delta >= 0 and issue_hit_rate_delta >= 0 and roi_delta >= 0:
        return (
            f"当前应用方案 {applied_display_name} 相比自动方案 {selected_display_name} "
            f"同时提升了收益与命中表现"
        )
    if prize_delta < 0 and issue_hit_rate_delta < 0 and roi_delta < 0:
        return (
            f"当前应用方案 {applied_display_name} 更偏保守，但相较自动方案 {selected_display_name} "
            f"收益和命中表现均有回落"
        )
    if prize_delta < 0 <= issue_hit_rate_delta:
        return (
            f"当前应用方案 {applied_display_name} 命中更稳，但相较自动方案 {selected_display_name} "
            f"收益有所回落"
        )
    if prize_delta >= 0 > issue_hit_rate_delta:
        return (
            f"当前应用方案 {applied_display_name} 收益更高，但相较自动方案 {selected_display_name} "
            f"命中表现略弱"
        )
    return (
        f"当前应用方案 {applied_display_name} 与自动方案 {selected_display_name} 各有取舍，"
        f"建议结合收益与命中率一起判断"
    )


def _build_tuning_issue_comparison(
    applied: BacktestResponse,
    selected: BacktestResponse,
    *,
    applied_profile_name: str,
    applied_display_name: str,
    selected_profile_name: str,
    selected_display_name: str,
) -> list[BacktestTuningIssueComparison]:
    selected_map = {item.issue: item for item in selected.issues}
    rows: list[BacktestTuningIssueComparison] = []
    for item in applied.issues:
        other = selected_map.get(item.issue)
        if not other:
            continue
        applied_amount = item.total_prize_amount or item.best_prize_amount or 0.0
        selected_amount = other.total_prize_amount or other.best_prize_amount or 0.0
        rows.append(
            BacktestTuningIssueComparison(
                issue=item.issue,
                draw_date=item.draw_date,
                applied=BacktestTuningIssueSide(
                    profile_name=applied_profile_name,
                    display_name=applied_display_name,
                    won_count=item.won_count,
                    best_prize_level=item.best_prize_level,
                    best_prize_amount=item.best_prize_amount,
                    cost=item.cost,
                ),
                selected=BacktestTuningIssueSide(
                    profile_name=selected_profile_name,
                    display_name=selected_display_name,
                    won_count=other.won_count,
                    best_prize_level=other.best_prize_level,
                    best_prize_amount=other.best_prize_amount,
                    cost=other.cost,
                ),
                won_count_delta=item.won_count - other.won_count,
                prize_amount_delta=round(applied_amount - selected_amount, 2),
            )
        )
    rows.sort(
        key=lambda row: (
            -abs(row.prize_amount_delta),
            -abs(row.won_count_delta),
            row.issue,
        )
    )
    return rows


def _theoretical_single_win_rate() -> float:
    total = comb(35, 5) * comb(12, 2)
    winning = 0
    for front_match, back_match in WIN_RULES:
        winning += (
            comb(5, front_match)
            * comb(30, 5 - front_match)
            * comb(2, back_match)
            * comb(10, 2 - back_match)
        )
    return winning / total


def _random_scheme(issue: str, scheme_index: int, *, run_index: int = 0) -> tuple[list[int], list[int]]:
    rng = random.Random(f"{issue}:{scheme_index}:random_uniform:{run_index}")
    return sorted(rng.sample(range(1, 36), 5)), sorted(rng.sample(range(1, 13), 2))


def _recent_omission(history_desc: list, number: int, *, zone: str) -> int:
    miss = 0
    for draw in history_desc:
        values = draw.front_numbers if zone == "front" else draw.back_numbers
        if number in values:
            break
        miss += 1
    return miss


def _window_scores(
    history_desc: list,
    *,
    zone: str,
    omission_map: dict[int, int] | None = None,
) -> list[tuple[int, float, int]]:
    pool = range(1, 36) if zone == "front" else range(1, 13)
    per_draw_rate = (5 / 35) if zone == "front" else (2 / 12)
    window_samples = [(window, weight, history_desc[:window]) for window, weight in WINDOW_MODEL_WINDOWS]
    scores: list[tuple[int, float, int]] = []
    for number in pool:
        score = 0.0
        for _window, weight, sample in window_samples:
            if not sample:
                continue
            hits = sum(
                1
                for draw in sample
                if number in (draw.front_numbers if zone == "front" else draw.back_numbers)
            )
            hit_rate = hits / len(sample)
            score += weight * (hit_rate / per_draw_rate)
        omission = omission_map.get(number, 0) if omission_map is not None else _recent_omission(history_desc, number, zone=zone)
        score += min(omission / 20, 1.0) * 0.08
        scores.append((number, score, omission))
    scores.sort(key=lambda item: (-item[1], item[0]))
    return scores


def _pick_numbers_from_scores(scored: list[tuple[int, float, int]], count: int, *, variant: int) -> list[int]:
    pool = list(scored[: max(15, count * 5)])
    if variant % 3 == 1:
        pool.sort(key=lambda item: (-item[2], -item[1], item[0]))
    elif variant % 3 == 2:
        pool.sort(key=lambda item: (-item[1], item[2], item[0]))

    picked: list[int] = []
    used_tails: set[int] = set()
    for number, _, _ in pool:
        tail = number % 10
        if len(picked) == count:
            break
        if tail in used_tails and len(used_tails) < count:
            continue
        picked.append(number)
        used_tails.add(tail)
    for number, _, _ in pool:
        if len(picked) == count:
            break
        if number not in picked:
            picked.append(number)
    return sorted(picked[:count])


def _window_model_schemes(
    history_desc: list,
    scheme_count: int,
    *,
    history_context: PrecomputedHistoryFeatures | None = None,
) -> list[tuple[list[int], list[int]]]:
    front_scored = _window_scores(
        history_desc,
        zone="front",
        omission_map=(history_context.front_omission if history_context is not None else None),
    )
    back_scored = _window_scores(
        history_desc,
        zone="back",
        omission_map=(history_context.back_omission if history_context is not None else None),
    )
    schemes: list[tuple[list[int], list[int]]] = []
    for index in range(scheme_count):
        schemes.append(
            (
                _pick_numbers_from_scores(front_scored, 5, variant=index),
                _pick_numbers_from_scores(back_scored, 2, variant=index),
            )
        )
    return schemes


def _build_benchmark(
    name: str,
    display_name: str,
    issue_results: list[dict],
    *,
    sample_runs: int = 1,
) -> BacktestBenchmark:
    stats = build_backtest_stats(issue_results)  # type: ignore[arg-type]
    return BacktestBenchmark(
        name=name,
        display_name=display_name,
        sample_runs=sample_runs,
        total_issues=stats.total_issues,
        total_generated_schemes=stats.total_generated_schemes,
        won_schemes=stats.won_schemes,
        total_prize_amount=stats.total_prize_amount,
        total_cost=stats.total_cost,
        net_profit=stats.net_profit,
        overall_win_rate=stats.overall_win_rate,
        issue_hit_rate=stats.issue_hit_rate,
        prize_rates=stats.prize_rates,
    )


def _build_window_summaries(issue_results: list[dict]) -> list[BacktestWindowSummary]:
    summaries: list[BacktestWindowSummary] = []
    for size in WINDOW_SUMMARY_SIZES:
        if len(issue_results) < size:
            continue
        window_issue_results = issue_results[-size:]
        stats = build_backtest_stats(window_issue_results)  # type: ignore[arg-type]
        summaries.append(
            BacktestWindowSummary(
                label=f"最近 {size} 期",
                total_issues=stats.total_issues,
                won_schemes=stats.won_schemes,
                total_prize_amount=stats.total_prize_amount,
                total_cost=stats.total_cost,
                net_profit=stats.net_profit,
                overall_win_rate=stats.overall_win_rate,
                issue_hit_rate=stats.issue_hit_rate,
                max_drawdown=_max_drawdown(window_issue_results),
                max_miss_streak=_max_miss_streak(window_issue_results),
            )
        )
    return summaries


def _scheme_coverage_metrics(final_schemes: list) -> BacktestCoverageMetrics:
    if len(final_schemes) <= 1:
        fresh_back_rate = 0.0
        if final_schemes:
            fresh_back_rate = round(len(set(final_schemes[0].back_numbers)) / len(final_schemes[0].back_numbers), 4)
        return BacktestCoverageMetrics(fresh_back_number_rate=fresh_back_rate)

    front_overlaps: list[int] = []
    back_overlaps: list[int] = []
    for left, right in combinations(final_schemes, 2):
        front_overlaps.append(len(set(left.front_numbers).intersection(right.front_numbers)))
        back_overlaps.append(len(set(left.back_numbers).intersection(right.back_numbers)))

    back_pairs = [tuple(scheme.back_numbers) for scheme in final_schemes]
    repeated_pairs = len(back_pairs) - len(set(back_pairs))
    unique_back_numbers = len({number for scheme in final_schemes for number in scheme.back_numbers})
    total_back_slots = len(final_schemes) * 2
    return BacktestCoverageMetrics(
        front_pairwise_overlap_avg=round(sum(front_overlaps) / len(front_overlaps), 4) if front_overlaps else 0.0,
        back_pairwise_overlap_avg=round(sum(back_overlaps) / len(back_overlaps), 4) if back_overlaps else 0.0,
        back_pair_reuse_rate=round(repeated_pairs / max(1, len(final_schemes) - 1), 4),
        fresh_back_number_rate=round(unique_back_numbers / total_back_slots, 4) if total_back_slots else 0.0,
    )


def _normalize_score_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in weights.values()) or 1.0
    return {key: round(max(0.0, value) / total, 4) for key, value in weights.items()}


def _normalize_combo_weights(weights: dict[str, float]) -> dict[str, float]:
    normalized = {**DEFAULT_COMBO_WEIGHTS, **weights}
    normalized["candidate"] = round(min(max(normalized["candidate"], 0.2), 0.9), 4)
    normalized["structure"] = round(1 - normalized["candidate"], 4)
    normalized["pair_front"] = round(min(max(normalized["pair_front"], 0.55), 0.9), 4)
    normalized["pair_back"] = round(1 - normalized["pair_front"], 4)
    normalized["multi_cover_novelty"] = round(min(max(normalized["multi_cover_novelty"], 0.05), 0.45), 4)
    normalized["multi_cover_pair"] = round(1 - normalized["multi_cover_novelty"], 4)
    normalized["single_hit_novelty"] = round(min(max(normalized["single_hit_novelty"], 0.0), 0.2), 4)
    normalized["single_hit_pair"] = round(1 - normalized["single_hit_novelty"], 4)
    normalized["overlap_front"] = round(min(max(normalized["overlap_front"], 0.0), 0.22), 4)
    normalized["overlap_back"] = round(min(max(normalized["overlap_back"], 0.18), 0.65), 4)
    normalized["same_back_pair_penalty"] = round(min(max(normalized["same_back_pair_penalty"], 0.5), 1.8), 4)
    normalized["back_usage_penalty"] = round(min(max(normalized["back_usage_penalty"], 0.08), 0.4), 4)
    normalized["fresh_back_bonus"] = round(min(max(normalized["fresh_back_bonus"], 0.05), 0.45), 4)
    normalized["crowd_penalty"] = round(min(max(normalized["crowd_penalty"], 0.05), 0.4), 4)
    return normalized


def _pack_tuning_weights(score_weights: dict[str, float], combo_weights: dict[str, float]) -> dict[str, float]:
    packed = {f"score_{key}": value for key, value in score_weights.items()}
    packed.update({f"combo_{key}": value for key, value in combo_weights.items()})
    return packed


def _freeze_weights(weights: dict[str, float]) -> tuple[tuple[str, float], ...]:
    return tuple(sorted((key, round(float(value), 6)) for key, value in weights.items()))


def _issue_eval_cache_key(
    *,
    issue: str,
    scheme_count: int,
    strategy_mode: str,
    ticket_mode: str,
    search_profile: str,
    score_weights: dict[str, float],
    combo_weights: dict[str, float],
) -> tuple:
    return (
        issue,
        scheme_count,
        strategy_mode,
        ticket_mode,
        search_profile,
        _freeze_weights(score_weights),
        _freeze_weights(combo_weights),
    )


def _tuning_summary_cache_key(
    history_asc: list,
    *,
    recent_issues: int,
    scheme_count: int,
    strategy_mode: str,
    ticket_mode: str,
    applied_profile_override: str | None,
) -> tuple:
    latest_issue = history_asc[-1].issue if history_asc else None
    latest_draw_date = history_asc[-1].draw_date.isoformat() if history_asc else None
    return (
        latest_issue,
        latest_draw_date,
        len(history_asc),
        recent_issues,
        scheme_count,
        strategy_mode,
        ticket_mode,
        applied_profile_override,
    )


def _clone_tuning_summary(summary: BacktestTuningSummary) -> BacktestTuningSummary:
    return summary.model_copy(deep=True)


def _get_cached_tuning_summary(cache_key: tuple) -> BacktestTuningSummary | None:
    summary = _tuning_summary_cache.get(cache_key)
    if summary is None:
        return None
    _tuning_summary_cache.pop(cache_key, None)
    _tuning_summary_cache[cache_key] = summary
    return _clone_tuning_summary(summary)


def _store_tuning_summary(cache_key: tuple, summary: BacktestTuningSummary) -> None:
    _tuning_summary_cache[cache_key] = _clone_tuning_summary(summary)
    while len(_tuning_summary_cache) > TUNING_SUMMARY_CACHE_MAX_ITEMS:
        oldest_key = next(iter(_tuning_summary_cache))
        _tuning_summary_cache.pop(oldest_key, None)


def _should_use_fast_tuning(*, recent_issues: int, target_issue_count: int) -> bool:
    return (
        recent_issues <= FAST_TUNING_RECENT_ISSUES_THRESHOLD
        or target_issue_count <= FAST_TUNING_TARGET_ISSUES_THRESHOLD
    )


def _iter_tuning_profiles(
    *,
    scheme_count: int,
    strategy_mode: str,
    fast_tuning: bool,
) -> list[tuple[str, str, dict[str, float], dict[str, float]]]:
    score_profiles = SCORE_WEIGHT_PROFILES
    combo_profiles = COMBO_WEIGHT_PROFILES
    if strategy_mode == "multi_cover" and scheme_count >= 5:
        score_name_allow = set(HIGH_TIER_FAST_SCORE_PROFILE_NAMES if fast_tuning else HIGH_TIER_SCORE_PROFILE_NAMES)
        combo_name_allow = set(HIGH_TIER_FAST_COMBO_PROFILE_NAMES if fast_tuning else HIGH_TIER_COMBO_PROFILE_NAMES)
        score_profiles = [item for item in SCORE_WEIGHT_PROFILES if item[0] in score_name_allow]
        combo_profiles = [item for item in COMBO_WEIGHT_PROFILES if item[0] in combo_name_allow]
    profiles: list[tuple[str, str, dict[str, float], dict[str, float]]] = []
    for score_name, score_display_name, score_weights in score_profiles:
        for combo_name, combo_weights in combo_profiles:
            profiles.append(
                (
                    f"{score_name}+{combo_name}",
                    f"{_score_profile_display_name(score_name, score_display_name)} + {_combo_profile_display_name(combo_name)}",
                    score_weights.copy(),
                    combo_weights.copy(),
                )
            )
    return profiles


def _evaluate_tuning_issue(
    target,
    prior_history_desc: list,
    history_context: PrecomputedHistoryFeatures,
    *,
    scheme_count: int,
    strategy_mode: str,
    ticket_mode: str,
    score_weights: dict[str, float],
    combo_weights: dict[str, float],
    search_profile: str,
    issue_evaluation_cache: dict[tuple, dict] | None = None,
) -> dict:
    cache_key: tuple | None = None
    if issue_evaluation_cache is not None:
        cache_key = _issue_eval_cache_key(
            issue=target.issue,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ticket_mode=ticket_mode,
            search_profile=search_profile,
            score_weights=score_weights,
            combo_weights=combo_weights,
        )
        cached = issue_evaluation_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

    seed_timestamp = _historical_seed_timestamp(target.draw_date)
    divination = generate_divination(
        prior_history_desc,
        issue=target.issue,
        timestamp=seed_timestamp,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ai_config=None,
        target_draw_date=target.draw_date,
        score_weights=score_weights,
        combo_weights=combo_weights,
        history_context=history_context,
        search_profile=search_profile,
    )
    if strategy_mode == "single_hit":
        supervised_windows = _build_supervised_windows(prior_history_desc)
        divination.final_schemes = _rerank_single_hit_schemes(divination.final_schemes, supervised_windows)
        divination.final_schemes = divination.final_schemes[:scheme_count]
    coverage_metrics = _scheme_coverage_metrics(divination.final_schemes)
    scheme_evaluations: list[dict] = []
    for scheme in divination.final_schemes:
        evaluation = evaluate_scheme_against_draw(
            target,
            front_numbers=scheme.front_numbers,
            back_numbers=scheme.back_numbers,
            is_additional=_ticket_is_additional(ticket_mode),
        )
        scheme_evaluations.append(
            {
                "label": scheme.label,
                "status": evaluation.status,
                "front_match_count": evaluation.front_match_count,
                "back_match_count": evaluation.back_match_count,
                "prize_level": evaluation.prize_level,
                "prize_amount": evaluation.prize_amount,
            }
        )
    evaluation_summary = _summarize_scheme_evaluations(scheme_evaluations)
    quality_signals = _issue_quality_signals_from_evaluations(scheme_evaluations)
    issue_result = {
        "issue": target.issue,
        "draw_date": target.draw_date,
        "scheme_count": scheme_count,
        "ticket_mode": ticket_mode,
        "won_count": evaluation_summary["won_count"],
        "best_prize_level": evaluation_summary["best_prize_level"],
        "best_prize_amount": evaluation_summary["best_prize_amount"],
        "total_prize_amount": evaluation_summary["total_prize_amount"],
        "winning_scheme_labels": evaluation_summary["winning_scheme_labels"],
        "prize_level_hits": evaluation_summary["prize_level_hits"],
        "prize_level_amounts": evaluation_summary["prize_level_amounts"],
        **quality_signals,
        "cost": round(scheme_count * _ticket_unit_price(ticket_mode), 2),
        "front_pairwise_overlap_avg": coverage_metrics.front_pairwise_overlap_avg,
        "back_pairwise_overlap_avg": coverage_metrics.back_pairwise_overlap_avg,
        "back_pair_reuse_rate": coverage_metrics.back_pair_reuse_rate,
        "fresh_back_number_rate": coverage_metrics.fresh_back_number_rate,
    }
    if issue_evaluation_cache is not None and cache_key is not None:
        issue_evaluation_cache[cache_key] = dict(issue_result)
    return issue_result


def _build_history_context_cache(history_asc: list, target_draws: list) -> dict[str, tuple[list, PrecomputedHistoryFeatures]]:
    cache: dict[str, tuple[list, PrecomputedHistoryFeatures]] = {}
    ordered_targets = sorted(target_draws, key=lambda draw: draw.issue)
    if not ordered_targets:
        return cache

    front_pool = tuple(range(1, 36))
    back_pool = tuple(range(1, 13))
    front_frequency = {number: 0 for number in front_pool}
    back_frequency = {number: 0 for number in back_pool}
    front_last_seen = {number: -1 for number in front_pool}
    back_last_seen = {number: -1 for number in back_pool}
    front_recent_hits = {number: 0 for number in front_pool}
    back_recent_hits = {number: 0 for number in back_pool}
    recent_front_draws: deque[tuple[int, ...]] = deque()
    recent_back_draws: deque[tuple[int, ...]] = deque()
    recent_history_desc: deque = deque(maxlen=BACKTEST_HISTORY_RECENT_WINDOW)
    history_size = 0
    target_index = 0

    def _snapshot_window_hits(*, zone: str) -> dict[int, dict[int, int]]:
        pool = front_pool if zone == "front" else back_pool
        hits_by_window: dict[int, dict[int, int]] = {}
        recent_draws = list(recent_history_desc)
        for window_size, _weight in SUPERVISED_WINDOWS:
            hits = {number: 0 for number in pool}
            for draw_item in recent_draws[:window_size]:
                values = draw_item.front_numbers if zone == "front" else draw_item.back_numbers
                for number in values:
                    hits[number] += 1
            hits_by_window[window_size] = hits
        return hits_by_window

    def _snapshot_context() -> PrecomputedHistoryFeatures:
        return PrecomputedHistoryFeatures(
            history_size=history_size,
            front_frequency=front_frequency.copy(),
            back_frequency=back_frequency.copy(),
            front_omission={
                number: (history_size if front_last_seen[number] < 0 else history_size - 1 - front_last_seen[number])
                for number in front_pool
            },
            back_omission={
                number: (history_size if back_last_seen[number] < 0 else history_size - 1 - back_last_seen[number])
                for number in back_pool
            },
            front_recent_hits=front_recent_hits.copy(),
            back_recent_hits=back_recent_hits.copy(),
            front_window_hits=_snapshot_window_hits(zone="front"),
            back_window_hits=_snapshot_window_hits(zone="back"),
        )

    for draw in history_asc:
        while target_index < len(ordered_targets) and ordered_targets[target_index].issue == draw.issue:
            cache[draw.issue] = (list(recent_history_desc), _snapshot_context())
            target_index += 1

        front_numbers = tuple(draw.front_numbers)
        back_numbers = tuple(draw.back_numbers)

        history_size += 1
        recent_history_desc.appendleft(draw)
        recent_front_draws.append(front_numbers)
        recent_back_draws.append(back_numbers)

        for number in front_numbers:
            front_frequency[number] += 1
            front_last_seen[number] = history_size - 1
            front_recent_hits[number] += 1
        for number in back_numbers:
            back_frequency[number] += 1
            back_last_seen[number] = history_size - 1
            back_recent_hits[number] += 1

        if len(recent_front_draws) > BACKTEST_RECENT_HITS_LOOKBACK:
            expired_front_numbers = recent_front_draws.popleft()
            for number in expired_front_numbers:
                front_recent_hits[number] -= 1
        if len(recent_back_draws) > BACKTEST_RECENT_HITS_LOOKBACK:
            expired_back_numbers = recent_back_draws.popleft()
            for number in expired_back_numbers:
                back_recent_hits[number] -= 1

        if target_index >= len(ordered_targets):
            break
    return cache


def _select_segmented_tuning_draws(history_asc: list, *, eval_end: int, recent_issues: int) -> list:
    max_sample_size = min(90, max(36, recent_issues))
    candidate_pool = history_asc[max(30, eval_end - min(180, max_sample_size * 2)) : eval_end]
    if len(candidate_pool) <= max_sample_size:
        return candidate_pool

    segment_count = 3 if len(candidate_pool) < 90 else 4
    selected: list = []
    for segment_index in range(segment_count):
        start = (len(candidate_pool) * segment_index) // segment_count
        end = (len(candidate_pool) * (segment_index + 1)) // segment_count
        segment = candidate_pool[start:end]
        if not segment:
            continue
        quota = max(8, max_sample_size // segment_count)
        if len(segment) <= quota:
            selected.extend(segment)
            continue
        step = len(segment) / quota
        for pick_index in range(quota):
            position = min(len(segment) - 1, int(round(pick_index * step)))
            selected.append(segment[position])

    deduped: list = []
    seen_issues: set[str] = set()
    for draw in selected:
        if draw.issue in seen_issues:
            continue
        seen_issues.add(draw.issue)
        deduped.append(draw)
    deduped.sort(key=lambda draw: draw.issue)
    if len(deduped) > max_sample_size:
        deduped = deduped[-max_sample_size:]
    return deduped


def _select_coarse_tuning_draws(target_draws: list, *, quota_total: int = 24) -> list:
    if len(target_draws) <= max(12, quota_total):
        return target_draws
    segment_count = 3 if len(target_draws) < max(72, quota_total * 3) else 4
    coarse_selected: list = []
    for segment_index in range(segment_count):
        start = (len(target_draws) * segment_index) // segment_count
        end = (len(target_draws) * (segment_index + 1)) // segment_count
        segment = target_draws[start:end]
        if not segment:
            continue
        quota = max(4, quota_total // segment_count)
        if len(segment) <= quota:
            coarse_selected.extend(segment)
            continue
        step = len(segment) / quota
        for pick_index in range(quota):
            position = min(len(segment) - 1, int(round(pick_index * step)))
            coarse_selected.append(segment[position])
    deduped: list = []
    seen_issues: set[str] = set()
    for draw in coarse_selected:
        if draw.issue in seen_issues:
            continue
        seen_issues.add(draw.issue)
        deduped.append(draw)
    deduped.sort(key=lambda draw: draw.issue)
    return deduped


def _split_tuning_train_validation(target_draws: list) -> tuple[list, list]:
    if len(target_draws) < 32:
        return target_draws, []
    validation_count = min(18, max(10, len(target_draws) // 4))
    train_draws = target_draws[:-validation_count]
    validation_draws = target_draws[-validation_count:]
    if len(train_draws) < 20:
        return target_draws, []
    return train_draws, validation_draws


def _build_walk_forward_windows(target_draws: list) -> list[tuple[list, list]]:
    if len(target_draws) < 42:
        return []
    test_size = min(12, max(8, len(target_draws) // 5))
    min_train_size = max(24, test_size * 2)
    windows: list[tuple[list, list]] = []
    split_end = min_train_size
    while split_end + test_size <= len(target_draws):
        windows.append((target_draws[:split_end], target_draws[split_end : split_end + test_size]))
        split_end += test_size
    return windows[-3:]


def _coarse_seed_keep_count(seed_count: int, *, fast_mode: bool = False) -> int:
    if fast_mode:
        return max(3, min(4, seed_count // 3 or 3))
    return max(4, min(7, seed_count // 2))


def _local_search_candidate_count(candidates: list[BacktestTuningCandidate], best_score: float) -> int:
    if not candidates or best_score <= 0:
        return 0
    ranked = sorted(candidates, key=lambda item: (-item.score, item.name))
    top_score = ranked[0].score
    if top_score < 0.08:
        return 0
    if len(ranked) == 1:
        return 1

    gap_1 = top_score - ranked[1].score
    gap_2 = top_score - ranked[2].score if len(ranked) > 2 else gap_1

    if gap_1 > 0.03:
        return 0
    if gap_1 > 0.02:
        return 1
    if gap_2 > 0.035:
        return 2
    return 3


def _should_continue_local_search(
    *,
    base_score: float,
    prior_best_score: float,
    current_best_score: float,
    attempt_index: int,
) -> bool:
    improvement = current_best_score - prior_best_score
    total_gain = current_best_score - base_score
    if attempt_index == 0:
        return improvement >= 0.004
    if total_gain >= 0.01:
        return False
    return improvement >= 0.0025


def _coverage_score_components(metrics: BacktestCoverageMetrics) -> BacktestCoverageScoreComponents:
    return BacktestCoverageScoreComponents(
        front_diversity=round(max(0.0, 1 - (metrics.front_pairwise_overlap_avg / 5)), 4),
        back_diversity=round(max(0.0, 1 - (metrics.back_pairwise_overlap_avg / 2)), 4),
        back_pair_diversity=round(max(0.0, 1 - metrics.back_pair_reuse_rate), 4),
        fresh_back=round(max(0.0, min(1.0, metrics.fresh_back_number_rate)), 4),
    )


def _coverage_quality_score(
    metrics: BacktestCoverageMetrics,
    *,
    strategy_mode: str,
) -> tuple[float, BacktestCoverageScoreComponents]:
    components = _coverage_score_components(metrics)
    if strategy_mode == "single_hit":
        score = (
            components.front_diversity * 0.28
            + components.back_diversity * 0.24
            + components.back_pair_diversity * 0.20
            + components.fresh_back * 0.28
        )
    else:
        score = (
            components.front_diversity * 0.22
            + components.back_diversity * 0.32
            + components.back_pair_diversity * 0.24
            + components.fresh_back * 0.22
        )
    return round(max(0.0, min(1.0, score)), 4), components


def _performance_score_from_counts(
    *,
    won_schemes: int,
    hit_issues: int,
    total_issues: int,
    scheme_count: int,
    signal_totals: dict[str, float] | None = None,
) -> float:
    if total_issues <= 0 or scheme_count <= 0:
        return 0.0
    overall_win_rate = won_schemes / (total_issues * scheme_count)
    issue_hit_rate = hit_issues / total_issues
    totals = signal_totals or _empty_performance_signal_totals()
    top3_hit_rate = min(1.0, totals["top3_hit_issues"] / total_issues)
    top4_hit_rate = min(1.0, totals["top4_hit_issues"] / total_issues)
    front_4plus_hit_rate = min(1.0, totals["front_4plus_hit_issues"] / total_issues)
    front_5_hit_rate = min(1.0, totals["front_5_hit_issues"] / total_issues)
    five_plus_one_hit_rate = min(1.0, totals["five_plus_one_hit_issues"] / total_issues)
    five_plus_two_hit_rate = min(1.0, totals["five_plus_two_hit_issues"] / total_issues)
    four_plus_two_hit_rate = min(1.0, totals["four_plus_two_hit_issues"] / total_issues)
    back_2plus_hit_rate = min(1.0, totals["back_2plus_hit_issues"] / total_issues)
    front_best_match_rate = min(1.0, totals["front_best_match_total"] / (total_issues * 5))
    back_best_match_rate = min(1.0, totals["back_best_match_total"] / (total_issues * 2))
    avg_issue_power_score = min(1.0, totals["issue_power_total"] / total_issues)
    six_plus_hit_rate = min(1.0, totals.get("six_plus_hit_issues", 0.0) / total_issues)
    mid_tier_hit_rate = min(1.0, totals.get("mid_tier_hit_issues", 0.0) / total_issues)
    # 六等奖以上的"per-scheme"率，归一化按 scheme_count，反映前后区联动的"每注"效率
    six_plus_scheme_rate = min(
        1.0, totals.get("six_plus_total_wins", 0.0) / max(1, total_issues * scheme_count)
    )
    # 头奖型信号 (top3 / front_5 / 5+x / 4+2) 直接影响一二三等奖候选排序，
    # 同时保留 overall_win_rate 权重和 10% 底线惩罚，避免 tuning 为冲高奖级丢掉综合命中率。
    score = (
        top4_hit_rate * 0.10
        + top3_hit_rate * 0.10
        + front_4plus_hit_rate * 0.09
        + front_5_hit_rate * 0.07
        + five_plus_one_hit_rate * 0.05
        + five_plus_two_hit_rate * 0.06
        + four_plus_two_hit_rate * 0.04
        + front_best_match_rate * 0.12
        + avg_issue_power_score * 0.07
        + issue_hit_rate * 0.04
        + overall_win_rate * 0.08
        + back_best_match_rate * 0.03
        + back_2plus_hit_rate * 0.01
        + six_plus_hit_rate * 0.10
        + mid_tier_hit_rate * 0.02
        + six_plus_scheme_rate * 0.02
    )
    # 综合命中率底线惩罚：低于 10% 时按比例打折，保证 tuning 不会选出"丢底线"的方案。
    # 在 0.04 处惩罚拉满 (×0.40)，0.10 及以上无惩罚，0.04~0.10 之间线性。
    floor_target = 0.10
    floor_min = 0.04
    if overall_win_rate >= floor_target:
        floor_factor = 1.0
    elif overall_win_rate <= floor_min:
        floor_factor = 0.40
    else:
        floor_factor = 0.40 + (overall_win_rate - floor_min) / (floor_target - floor_min) * 0.60
    score *= floor_factor
    return round(max(0.0, min(1.0, score)), 4)


def _tuning_score_breakdown(
    *,
    won_schemes: int,
    hit_issues: int,
    total_issues: int,
    scheme_count: int,
    coverage_metrics: BacktestCoverageMetrics | None,
    strategy_mode: str,
    issue_results: list[BacktestIssueResult | dict] | None = None,
    signal_totals: dict[str, float] | None = None,
) -> tuple[float, float, float | None, BacktestCoverageScoreComponents | None]:
    if signal_totals is None and issue_results is not None:
        signal_totals = _performance_signal_totals(issue_results)
    performance_score = _performance_score_from_counts(
        won_schemes=won_schemes,
        hit_issues=hit_issues,
        total_issues=total_issues,
        scheme_count=scheme_count,
        signal_totals=signal_totals,
    )
    if not coverage_metrics:
        return performance_score, performance_score, None, None
    coverage_score, coverage_components = _coverage_quality_score(coverage_metrics, strategy_mode=strategy_mode)
    if strategy_mode == "single_hit":
        blend = 0.10
    elif scheme_count >= 5:
        blend = 0.12
    else:
        blend = 0.18
    total_score = round(performance_score * (1 - blend) + coverage_score * blend, 4)
    return total_score, performance_score, coverage_score, coverage_components


def _tuning_score_from_counts(
    *,
    won_schemes: int,
    hit_issues: int,
    total_issues: int,
    scheme_count: int,
    coverage_metrics: BacktestCoverageMetrics | None = None,
    strategy_mode: str,
    issue_results: list[BacktestIssueResult | dict] | None = None,
    signal_totals: dict[str, float] | None = None,
) -> float:
    return _tuning_score_breakdown(
        won_schemes=won_schemes,
        hit_issues=hit_issues,
        total_issues=total_issues,
        scheme_count=scheme_count,
        coverage_metrics=coverage_metrics,
        strategy_mode=strategy_mode,
        issue_results=issue_results,
        signal_totals=signal_totals,
    )[0]


def _tuning_prune_threshold(best_score: float, *, total_issues: int) -> float:
    if best_score <= 0:
        return 0.0
    margin = max(0.01, min(0.025, 1.0 / max(1, total_issues) + 0.004))
    return max(0.0, best_score - margin)


def _evaluate_weight_config(
    history_asc: list,
    target_draws: list,
    *,
    scheme_count: int,
    strategy_mode: str,
    ticket_mode: str,
    score_weights: dict[str, float],
    combo_weights: dict[str, float],
    history_context_cache: dict[str, tuple[list, PrecomputedHistoryFeatures]] | None = None,
    issue_evaluation_cache: dict[tuple, dict] | None = None,
    search_profile: str = "tuning",
    score_to_beat: float | None = None,
    cancel_check: CancelCheck | None = None,
) -> tuple[float, BacktestResponse, bool]:
    prepared_targets: list[tuple[object, list, PrecomputedHistoryFeatures]] = []
    for target in target_draws:
        if cancel_check:
            cancel_check()
        if history_context_cache and target.issue in history_context_cache:
            prior_history_desc, history_context = history_context_cache[target.issue]
        else:
            prior_history_asc = [draw for draw in history_asc if draw.issue < target.issue]
            prior_history_desc = prior_history_asc[::-1]
            history_context = build_history_feature_context(prior_history_desc)
        if history_context.history_size < 30:
            continue
        prepared_targets.append((target, prior_history_desc, history_context))

    total_issues = len(prepared_targets)
    issue_results: list[dict] = []
    accumulated_won_schemes = 0
    accumulated_hit_issues = 0
    accumulated_signal_totals = _empty_performance_signal_totals()
    for index, (target, prior_history_desc, history_context) in enumerate(prepared_targets):
        if cancel_check:
            cancel_check()
        issue_result = _evaluate_tuning_issue(
            target,
            prior_history_desc,
            history_context,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ticket_mode=ticket_mode,
            score_weights=score_weights,
            combo_weights=combo_weights,
            search_profile=search_profile,
            issue_evaluation_cache=issue_evaluation_cache,
        )
        won_count = int(issue_result["won_count"])
        accumulated_won_schemes += won_count
        if won_count > 0:
            accumulated_hit_issues += 1
        accumulated_signal_totals["top3_hit_issues"] += 1.0 if issue_result.get("top3_hit") else 0.0
        accumulated_signal_totals["top4_hit_issues"] += 1.0 if issue_result.get("top4_hit") else 0.0
        accumulated_signal_totals["front_4plus_hit_issues"] += 1.0 if issue_result.get("front_4plus_hit") else 0.0
        accumulated_signal_totals["front_5_hit_issues"] += 1.0 if issue_result.get("front_5_hit") else 0.0
        accumulated_signal_totals["five_plus_zero_hit_issues"] += 1.0 if issue_result.get("five_plus_zero_hit") else 0.0
        accumulated_signal_totals["five_plus_one_hit_issues"] += 1.0 if issue_result.get("five_plus_one_hit") else 0.0
        accumulated_signal_totals["five_plus_two_hit_issues"] += 1.0 if issue_result.get("five_plus_two_hit") else 0.0
        accumulated_signal_totals["four_plus_two_hit_issues"] += 1.0 if issue_result.get("four_plus_two_hit") else 0.0
        accumulated_signal_totals["back_2plus_hit_issues"] += 1.0 if issue_result.get("back_2plus_hit") else 0.0
        accumulated_signal_totals["front_best_match_total"] += float(issue_result.get("front_best_match_count") or 0.0)
        accumulated_signal_totals["back_best_match_total"] += float(issue_result.get("back_best_match_count") or 0.0)
        accumulated_signal_totals["issue_power_total"] += float(issue_result.get("issue_power_score") or 0.0)
        issue_results.append(issue_result)
        if score_to_beat is not None and index + 1 < total_issues:
            evaluated_issues = index + 1
            min_issues_before_prune = min(total_issues - 1, max(12, total_issues // 3))
            if evaluated_issues < min_issues_before_prune:
                continue
            remaining_issues = total_issues - (index + 1)
            optimistic_signal_totals = dict(accumulated_signal_totals)
            optimistic_signal_totals["top3_hit_issues"] += remaining_issues
            optimistic_signal_totals["top4_hit_issues"] += remaining_issues
            optimistic_signal_totals["front_4plus_hit_issues"] += remaining_issues
            optimistic_signal_totals["front_5_hit_issues"] += remaining_issues
            optimistic_signal_totals["five_plus_zero_hit_issues"] += remaining_issues
            optimistic_signal_totals["five_plus_one_hit_issues"] += remaining_issues
            optimistic_signal_totals["five_plus_two_hit_issues"] += remaining_issues
            optimistic_signal_totals["four_plus_two_hit_issues"] += remaining_issues
            optimistic_signal_totals["back_2plus_hit_issues"] += remaining_issues
            optimistic_signal_totals["front_best_match_total"] += remaining_issues * 5
            optimistic_signal_totals["back_best_match_total"] += remaining_issues * 2
            optimistic_signal_totals["issue_power_total"] += remaining_issues * 1.0
            max_possible_score = _tuning_score_from_counts(
                won_schemes=accumulated_won_schemes + remaining_issues * scheme_count,
                hit_issues=accumulated_hit_issues + remaining_issues,
                total_issues=total_issues,
                scheme_count=scheme_count,
                coverage_metrics=BacktestCoverageMetrics(
                    front_pairwise_overlap_avg=0.0,
                    back_pairwise_overlap_avg=0.0,
                    back_pair_reuse_rate=0.0,
                    fresh_back_number_rate=1.0,
                ),
                strategy_mode=strategy_mode,
                signal_totals=optimistic_signal_totals,
            )
            if max_possible_score < score_to_beat:
                stats = build_backtest_stats(issue_results)  # type: ignore[arg-type]
                return round(max_possible_score, 4), stats, True
    stats = build_backtest_stats(issue_results)  # type: ignore[arg-type]
    score = round(
        _tuning_score_from_counts(
            won_schemes=stats.won_schemes,
            hit_issues=sum(1 for item in issue_results if item["won_count"] > 0),
            total_issues=stats.total_issues,
            scheme_count=scheme_count,
            coverage_metrics=stats.coverage_metrics,
            strategy_mode=strategy_mode,
            issue_results=issue_results,
        ),
        4,
    )
    return score, stats, False


def _evaluate_walk_forward_candidate(
    history_asc: list,
    windows: list[tuple[list, list]],
    *,
    scheme_count: int,
    strategy_mode: str,
    ticket_mode: str,
    score_weights: dict[str, float],
    combo_weights: dict[str, float],
    issue_evaluation_cache: dict[tuple, dict] | None = None,
    window_history_context_caches: list[dict[str, tuple[list, PrecomputedHistoryFeatures]]] | None = None,
    cancel_check: CancelCheck | None = None,
) -> tuple[
    float,
    float,
    float,
    float | None,
    BacktestCoverageScoreComponents | None,
    int,
    list[BacktestWalkForwardWindow],
    float,
    int,
    int,
    BacktestResponse | None,
]:
    if not windows:
        return 0.0, 0.0, 0.0, None, None, 0, [], 0.0, 0, 0, None
    total_issues = 0
    details: list[BacktestWalkForwardWindow] = []
    all_issue_results: list[dict] = []
    for window_index, (train_draws, test_draws) in enumerate(windows, start=1):
        if cancel_check:
            cancel_check()
        if window_history_context_caches and window_index - 1 < len(window_history_context_caches):
            test_history_context_cache = window_history_context_caches[window_index - 1]
        else:
            test_history_context_cache = _build_history_context_cache(history_asc, test_draws)
        score, stats, _ = _evaluate_weight_config(
            history_asc,
            test_draws,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ticket_mode=ticket_mode,
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context_cache=test_history_context_cache,
            issue_evaluation_cache=issue_evaluation_cache,
            search_profile="tuning",
            cancel_check=cancel_check,
        )
        total_issues += stats.total_issues
        all_issue_results.extend([item.model_dump() for item in stats.issues])
        if train_draws and test_draws:
            details.append(
                BacktestWalkForwardWindow(
                    label=f"W{window_index}",
                    train_start_issue=train_draws[0].issue,
                    train_end_issue=train_draws[-1].issue,
                    test_start_issue=test_draws[0].issue,
                    test_end_issue=test_draws[-1].issue,
                    test_issues=stats.total_issues,
                    score=score,
                    overall_win_rate=stats.overall_win_rate,
                    issue_hit_rate=stats.issue_hit_rate,
                )
            )
    if total_issues <= 0:
        return 0.0, 0.0, 0.0, None, None, 0, details, 0.0, 0, 0, None
    aggregate_stats = build_backtest_stats(all_issue_results)  # type: ignore[arg-type]
    overall_win_rate = aggregate_stats.overall_win_rate
    issue_hit_rate = aggregate_stats.issue_hit_rate
    coverage_metrics = aggregate_stats.coverage_metrics
    score, _, coverage_score, coverage_components = _tuning_score_breakdown(
        won_schemes=aggregate_stats.won_schemes,
        hit_issues=sum(1 for item in aggregate_stats.issues if item.won_count > 0),
        total_issues=aggregate_stats.total_issues,
        scheme_count=scheme_count,
        coverage_metrics=coverage_metrics,
        strategy_mode=strategy_mode,
        issue_results=aggregate_stats.issues,
    )
    return (
        round(score, 4),
        overall_win_rate,
        issue_hit_rate,
        coverage_score,
        coverage_components,
        len(windows),
        details,
        _max_drawdown(all_issue_results),
        _max_miss_streak(all_issue_results),
        aggregate_stats.total_issues,
        aggregate_stats,
    )


def _best_result_for_schemes(
    target,
    schemes: list[tuple[list[int], list[int]]],
    *,
    ticket_mode: str,
) -> dict[str, object]:
    evaluations: list[dict] = []
    for front_numbers, back_numbers in schemes:
        evaluation = evaluate_scheme_against_draw(
            target,
            front_numbers=front_numbers,
            back_numbers=back_numbers,
            is_additional=_ticket_is_additional(ticket_mode),
        )
        evaluations.append(
            {
                "status": evaluation.status,
                "front_match_count": evaluation.front_match_count,
                "back_match_count": evaluation.back_match_count,
                "prize_level": evaluation.prize_level,
                "prize_amount": evaluation.prize_amount,
            }
        )
    return _summarize_scheme_evaluations(evaluations)


def _evaluate_backtest_issue(
    index: int,
    *,
    target,
    prior_history_desc: list,
    history_context: PrecomputedHistoryFeatures,
    scheme_count: int,
    strategy_mode: str,
    ticket_mode: str,
    backtest_ai_config: AIConfigRequest | None,
    score_weights: dict[str, float],
    combo_weights: dict[str, float],
    tuning_profile: str | None,
) -> dict:
    runtime_metadata: dict[str, object] = {}
    seed_timestamp = _historical_seed_timestamp(target.draw_date)
    divination = generate_divination(
        prior_history_desc,
        issue=target.issue,
        timestamp=seed_timestamp,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ai_config=backtest_ai_config,
        target_draw_date=target.draw_date,
        score_weights=score_weights,
        combo_weights=combo_weights,
        history_context=history_context,
        search_profile="full",
    )
    divination = _apply_runtime_divination_adjustments(
        divination=divination,
        prior_history_desc=prior_history_desc,
        issue=target.issue,
        target_draw_date=target.draw_date,
        seed_timestamp=seed_timestamp,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ai_config=backtest_ai_config,
        score_weights=score_weights,
        combo_weights=combo_weights,
        history_context=history_context,
        metadata=runtime_metadata,
    )
    dynamic_threshold = _dynamic_confidence_threshold(
        strategy_mode=strategy_mode,
        scheme_count=scheme_count,
        front_candidates=divination.front_candidates,
        back_candidates=divination.back_candidates,
    )
    issue_confidence = _issue_confidence(divination.final_schemes)
    front_confidence = _zone_scheme_confidence(divination.final_schemes, divination.front_candidates, zone="front")
    back_confidence = _zone_scheme_confidence(divination.final_schemes, divination.back_candidates, zone="back")
    selected_scheme_count = min(scheme_count, len(divination.final_schemes))
    selected_schemes = divination.final_schemes[:selected_scheme_count]
    scheme_evaluations: list[dict] = []
    for scheme in selected_schemes:
        evaluation = evaluate_scheme_against_draw(
            target,
            front_numbers=scheme.front_numbers,
            back_numbers=scheme.back_numbers,
            is_additional=_ticket_is_additional(ticket_mode),
        )
        scheme_evaluations.append(
            {
                "label": scheme.label,
                "status": evaluation.status,
                "front_match_count": evaluation.front_match_count,
                "back_match_count": evaluation.back_match_count,
                "prize_level": evaluation.prize_level,
                "prize_amount": evaluation.prize_amount,
            }
        )
    evaluation_summary = _summarize_scheme_evaluations(scheme_evaluations)
    coverage_metrics = _scheme_coverage_metrics(selected_schemes)
    quality_signals = _issue_quality_signals_from_evaluations(scheme_evaluations)
    window_schemes = _window_model_schemes(
        prior_history_desc,
        scheme_count,
        history_context=history_context,
    )
    window_summary = _best_result_for_schemes(
        target,
        window_schemes,
        ticket_mode=ticket_mode,
    )
    cost = round(selected_scheme_count * _ticket_unit_price(ticket_mode), 2)
    random_issue_results: list[dict] = []
    for run_index in range(RANDOM_BASELINE_RUNS):
        random_schemes = [
            _random_scheme(target.issue, scheme_index, run_index=run_index)
            for scheme_index in range(scheme_count)
        ]
        random_summary = _best_result_for_schemes(
            target,
            random_schemes,
            ticket_mode=ticket_mode,
        )
        random_issue_results.append(
            {
                "issue": f"{target.issue}-r{run_index + 1}",
                "draw_date": target.draw_date,
                "scheme_count": scheme_count,
                "ticket_mode": ticket_mode,
                "won_count": random_summary["won_count"],
                "best_prize_level": random_summary["best_prize_level"],
                "best_prize_amount": random_summary["best_prize_amount"],
                "total_prize_amount": random_summary["total_prize_amount"],
                "winning_scheme_labels": [],
                "prize_level_hits": random_summary["prize_level_hits"],
                "prize_level_amounts": random_summary["prize_level_amounts"],
                "cost": round(scheme_count * _ticket_unit_price(ticket_mode), 2),
            }
        )
    return {
        "index": index,
        "issue": target.issue,
        "draw_date": target.draw_date,
        "ai_engine": divination.ai_analysis.engine,
        "tuning_profile": tuning_profile,
        "issue_confidence": issue_confidence,
        "dynamic_threshold": dynamic_threshold,
        "front_confidence": front_confidence,
        "back_confidence": back_confidence,
        "front_candidates": divination.front_candidates,
        "back_candidates": divination.back_candidates,
        "selected_schemes": selected_schemes,
        "scheme_evaluations": scheme_evaluations,
        "evaluation_summary": evaluation_summary,
        "coverage_metrics": coverage_metrics,
        "quality_signals": quality_signals,
        "deep_search_triggered": bool(runtime_metadata.get("deep_search_triggered", False)),
        "deep_search_reason": runtime_metadata.get("deep_search_reason"),
        "window_summary": window_summary,
        "random_issue_results": random_issue_results,
        "cost": cost,
    }


def _build_tuning_summary(
    history_asc: list,
    *,
    recent_issues: int,
    scheme_count: int,
    strategy_mode: str,
    ticket_mode: str,
    applied_profile_override: str | None = None,
    cancel_check: CancelCheck | None = None,
) -> BacktestTuningSummary:
    cache_key = _tuning_summary_cache_key(
        history_asc,
        recent_issues=recent_issues,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ticket_mode=ticket_mode,
        applied_profile_override=applied_profile_override,
    )
    cached_summary = _get_cached_tuning_summary(cache_key)
    if cached_summary is not None:
        return cached_summary

    eval_end = max(0, len(history_asc) - recent_issues)
    if eval_end <= 30:
        summary = _override_only_tuning_summary(
            applied_profile_override,
            sample_issues=0,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
        )
        _store_tuning_summary(cache_key, summary)
        return _clone_tuning_summary(summary)

    target_draws = _select_segmented_tuning_draws(history_asc, eval_end=eval_end, recent_issues=recent_issues)
    if len(target_draws) < 20:
        summary = _override_only_tuning_summary(
            applied_profile_override,
            sample_issues=len(target_draws),
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
        )
        _store_tuning_summary(cache_key, summary)
        return _clone_tuning_summary(summary)

    fast_tuning = _should_use_fast_tuning(recent_issues=recent_issues, target_issue_count=len(target_draws))
    train_draws, validation_draws = _split_tuning_train_validation(target_draws)
    if fast_tuning:
        validation_draws = []
    walk_forward_windows = [] if fast_tuning else _build_walk_forward_windows(target_draws)
    coarse_draws = _select_coarse_tuning_draws(
        train_draws,
        quota_total=FAST_TUNING_COARSE_QUOTA if fast_tuning else 24,
    )
    coarse_history_context_cache = _build_history_context_cache(history_asc, coarse_draws)
    full_history_context_cache = _build_history_context_cache(history_asc, train_draws)
    validation_history_context_cache = (
        _build_history_context_cache(history_asc, validation_draws) if validation_draws else None
    )
    walk_forward_history_context_caches = [
        _build_history_context_cache(history_asc, test_draws)
        for _, test_draws in walk_forward_windows
    ]
    issue_evaluation_cache: dict[tuple, dict] = {}
    coarse_rankings: list[tuple[float, str, str, dict[str, float], dict[str, float]]] = []
    coarse_candidate_records: list[dict[str, object]] = []
    tuning_profiles = _iter_tuning_profiles(
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        fast_tuning=fast_tuning,
    )

    for candidate_name, candidate_display_name, score_weights, combo_weights in tuning_profiles:
        if cancel_check:
            cancel_check()
        coarse_score, coarse_stats, _ = _evaluate_weight_config(
            history_asc,
            coarse_draws,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ticket_mode=ticket_mode,
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context_cache=coarse_history_context_cache,
            issue_evaluation_cache=issue_evaluation_cache,
            search_profile="coarse",
            cancel_check=cancel_check,
        )
        coarse_rankings.append(
            (coarse_score, candidate_name, candidate_display_name, score_weights.copy(), combo_weights.copy())
        )
        coarse_candidate_records.append(
            {
                "name": candidate_name,
                "display_name": candidate_display_name,
                "summary": _candidate_outcome_summary(coarse_stats),
                "stats": coarse_stats,
                "stage_score": coarse_score,
                "train_score": coarse_score,
                "score_weights": score_weights.copy(),
                "combo_weights": combo_weights.copy(),
            }
        )

    coarse_rankings.sort(key=lambda item: (-item[0], item[1]))
    keep_count = _coarse_seed_keep_count(len(coarse_rankings), fast_mode=fast_tuning)
    seed_candidates = [(item[1], item[2], item[3], item[4]) for item in coarse_rankings[:keep_count]]
    coarse_record_by_name = {
        str(item["name"]): item for item in coarse_candidate_records if item.get("name")
    }
    guarded_overall_coarse_candidate = (
        _pick_guarded_overall_win_candidate(coarse_candidate_records, baseline_name=HIGH_TIER_FALLBACK_PROFILE)
        if strategy_mode == "multi_cover" and scheme_count >= 5
        else None
    )
    for extra_name in (
        HIGH_TIER_FALLBACK_PROFILE,
        _pick_best_overall_win_record_name(coarse_candidate_records),
        str(guarded_overall_coarse_candidate["name"]) if guarded_overall_coarse_candidate else None,
    ):
        if not extra_name or any(item[0] == extra_name for item in seed_candidates):
            continue
        extra_record = coarse_record_by_name.get(extra_name)
        if not extra_record:
            continue
        seed_candidates.append(
            (
                str(extra_record["name"]),
                str(extra_record["display_name"]),
                dict(extra_record["score_weights"]),
                dict(extra_record["combo_weights"]),
            )
        )

    candidates: list[BacktestTuningCandidate] = []
    candidate_profiles: list[tuple[BacktestTuningCandidate, dict[str, float], dict[str, float]]] = []
    train_candidate_records: list[dict[str, object]] = []
    best_profile = seed_candidates[0] if seed_candidates else (
        SCORE_WEIGHT_PROFILES[0][0],
        _score_profile_display_name(SCORE_WEIGHT_PROFILES[0][0], SCORE_WEIGHT_PROFILES[0][1]),
        DEFAULT_SCORE_WEIGHTS.copy(),
        DEFAULT_COMBO_WEIGHTS.copy(),
    )
    best_score = -1.0

    for candidate_name, candidate_display_name, score_weights, combo_weights in seed_candidates:
        if cancel_check:
            cancel_check()
        score, stats, pruned = _evaluate_weight_config(
            history_asc,
            train_draws,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ticket_mode=ticket_mode,
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context_cache=full_history_context_cache,
            issue_evaluation_cache=issue_evaluation_cache,
            search_profile="tuning",
            score_to_beat=(_tuning_prune_threshold(best_score, total_issues=len(train_draws)) if best_score > 0 else None),
            cancel_check=cancel_check,
        )
        if pruned:
            continue
        _, performance_score, coverage_score, coverage_components = _tuning_score_breakdown(
            won_schemes=stats.won_schemes,
            hit_issues=sum(1 for item in stats.issues if item.won_count > 0),
            total_issues=stats.total_issues,
            scheme_count=scheme_count,
            coverage_metrics=stats.coverage_metrics,
            strategy_mode=strategy_mode,
            issue_results=stats.issues,
        )
        candidate = BacktestTuningCandidate(
            name=candidate_name,
            display_name=candidate_display_name,
            score=score,
            performance_score=performance_score,
            coverage_score=coverage_score,
            coverage_components=coverage_components,
            overall_win_rate=stats.overall_win_rate,
            issue_hit_rate=stats.issue_hit_rate,
            sample_issues=stats.total_issues,
        )
        candidates.append(candidate)
        candidate_profiles.append((candidate, score_weights.copy(), combo_weights.copy()))
        train_candidate_records.append(
            {
                "name": candidate_name,
                "display_name": candidate_display_name,
                "candidate": candidate,
                "summary": _candidate_outcome_summary(stats),
                "stats": stats,
                "stage_score": score,
                "train_score": score,
                "score_weights": score_weights.copy(),
                "combo_weights": combo_weights.copy(),
            }
        )
        if score > best_score:
            best_score = score
            best_profile = (candidate_name, candidate_display_name, score_weights.copy(), combo_weights.copy())

    seed_best_score = best_score
    local_search_count = 0 if fast_tuning else _local_search_candidate_count(candidates, best_score)
    if local_search_count > 0:
        base_score_weights = best_profile[2]
        base_combo_weights = best_profile[3]
        local_search_candidates = [
            (
                f"{best_profile[0]}+local_a",
                "局部搜索 A",
                _normalize_score_weights(
                    {
                        "tail": base_score_weights["tail"],
                        "omission": base_score_weights["omission"] + 0.04,
                        "frequency": base_score_weights["frequency"] - 0.02,
                        "recent_hits": base_score_weights["recent_hits"] - 0.02,
                    }
                ),
                _normalize_combo_weights(
                    {
                        **base_combo_weights,
                        "candidate": base_combo_weights["candidate"] - 0.06,
                        "pair_front": base_combo_weights["pair_front"] - 0.02,
                        "multi_cover_novelty": base_combo_weights["multi_cover_novelty"] + 0.04,
                        "single_hit_novelty": base_combo_weights["single_hit_novelty"] + 0.03,
                    }
                ),
            ),
            (
                f"{best_profile[0]}+local_b",
                "局部搜索 B",
                _normalize_score_weights(
                    {
                        "tail": base_score_weights["tail"] - 0.02,
                        "omission": base_score_weights["omission"] - 0.03,
                        "frequency": base_score_weights["frequency"] + 0.03,
                        "recent_hits": base_score_weights["recent_hits"] + 0.02,
                    }
                ),
                _normalize_combo_weights(
                    {
                        **base_combo_weights,
                        "candidate": base_combo_weights["candidate"] + 0.05,
                        "pair_front": base_combo_weights["pair_front"] + 0.03,
                        "multi_cover_novelty": base_combo_weights["multi_cover_novelty"] - 0.03,
                        "single_hit_novelty": base_combo_weights["single_hit_novelty"] - 0.02,
                    }
                ),
            ),
            (
                f"{best_profile[0]}+local_c",
                "局部搜索 C",
                _normalize_score_weights(
                    {
                        "tail": base_score_weights["tail"] + 0.03,
                        "omission": base_score_weights["omission"] - 0.01,
                        "frequency": base_score_weights["frequency"] - 0.01,
                        "recent_hits": base_score_weights["recent_hits"] - 0.01,
                    }
                ),
                _normalize_combo_weights(
                    {
                        **base_combo_weights,
                        "candidate": base_combo_weights["candidate"] - 0.02,
                        "pair_front": base_combo_weights["pair_front"],
                        "multi_cover_novelty": base_combo_weights["multi_cover_novelty"] + 0.02,
                        "single_hit_novelty": base_combo_weights["single_hit_novelty"],
                    }
                ),
            ),
        ]

        for attempt_index, (name, display_name, score_weights, combo_weights) in enumerate(
            local_search_candidates[:local_search_count]
        ):
            if cancel_check:
                cancel_check()
            prior_best_score = best_score
            score, stats, pruned = _evaluate_weight_config(
                history_asc,
                train_draws,
                scheme_count=scheme_count,
                strategy_mode=strategy_mode,
                ticket_mode=ticket_mode,
                score_weights=score_weights,
                combo_weights=combo_weights,
                history_context_cache=full_history_context_cache,
                issue_evaluation_cache=issue_evaluation_cache,
                search_profile="tuning",
                score_to_beat=(_tuning_prune_threshold(best_score, total_issues=len(train_draws)) if best_score > 0 else None),
                cancel_check=cancel_check,
            )
            if pruned:
                continue
            _, performance_score, coverage_score, coverage_components = _tuning_score_breakdown(
                won_schemes=stats.won_schemes,
                hit_issues=sum(1 for item in stats.issues if item.won_count > 0),
                total_issues=stats.total_issues,
                scheme_count=scheme_count,
                coverage_metrics=stats.coverage_metrics,
                strategy_mode=strategy_mode,
                issue_results=stats.issues,
            )
            candidate = BacktestTuningCandidate(
                name=name,
                display_name=display_name,
                score=score,
                performance_score=performance_score,
                coverage_score=coverage_score,
                coverage_components=coverage_components,
                overall_win_rate=stats.overall_win_rate,
                issue_hit_rate=stats.issue_hit_rate,
                sample_issues=stats.total_issues,
            )
            candidates.append(candidate)
            candidate_profiles.append((candidate, score_weights.copy(), combo_weights.copy()))
            train_candidate_records.append(
                {
                    "name": name,
                    "display_name": display_name,
                    "candidate": candidate,
                    "summary": _candidate_outcome_summary(stats),
                    "stats": stats,
                    "stage_score": score,
                    "train_score": score,
                    "score_weights": score_weights.copy(),
                    "combo_weights": combo_weights.copy(),
                }
            )
            if score > best_score:
                best_score = score
                best_profile = (name, display_name, score_weights.copy(), combo_weights.copy())
            if attempt_index + 1 < local_search_count and not _should_continue_local_search(
                base_score=seed_best_score,
                prior_best_score=prior_best_score,
                current_best_score=best_score,
                attempt_index=attempt_index,
            ):
                break

    selection_basis = "train_only"
    selected_candidate_name = best_profile[0]
    selected_candidate_display_name = best_profile[1]
    selected_score_weights = best_profile[2].copy()
    selected_combo_weights = best_profile[3].copy()
    selected_validation_score: float | None = None
    selected_validation_overall_win_rate: float | None = None
    selected_validation_issue_hit_rate: float | None = None
    selected_validation_stability_adjusted_score: float | None = None
    selected_validation_stability_breakdown: BacktestStabilityBreakdown | None = None
    selected_validation_max_drawdown: float | None = None
    selected_validation_max_miss_streak: int | None = None
    selected_walk_forward_score: float | None = None
    selected_walk_forward_stability_adjusted_score: float | None = None
    selected_walk_forward_stability_breakdown: BacktestStabilityBreakdown | None = None
    selected_walk_forward_overall_win_rate: float | None = None
    selected_walk_forward_issue_hit_rate: float | None = None
    selected_walk_forward_windows = 0
    selected_walk_forward_stability: str | None = None
    selected_walk_forward_score_range: float | None = None
    selected_walk_forward_max_drawdown: float | None = None
    selected_walk_forward_max_miss_streak: int | None = None
    walk_forward_details: list[BacktestTuningWalkForwardDetail] = []
    selected_reason = "按训练样本得分选中"
    selection_warning: str | None = None
    compare_profile: str | None = None
    compare_display_name: str | None = None
    compare_reason: str | None = None
    runner_up_display_name: str | None = None
    selection_margin: float | None = None
    runner_up_profile_name: str | None = None
    runner_up_walk_forward_stability: str | None = None
    runner_up_walk_forward_score_range: float | None = None
    best_overall_train_profile_name = _pick_best_overall_win_record_name(train_candidate_records)
    guarded_overall_train_candidate = (
        _pick_guarded_overall_win_candidate(train_candidate_records, baseline_name=HIGH_TIER_FALLBACK_PROFILE)
        if strategy_mode == "multi_cover" and scheme_count >= 5
        else None
    )
    guarded_train_candidate = (
        _pick_guarded_high_tier_candidate(train_candidate_records, baseline_name=HIGH_TIER_FALLBACK_PROFILE)
        if strategy_mode == "multi_cover" and scheme_count >= 5
        else None
    )
    guarded_overall_validation_candidate: dict[str, object] | None = None
    guarded_validation_candidate: dict[str, object] | None = None
    best_overall_validation_profile_name: str | None = None

    if validation_draws and candidate_profiles:
        selection_basis = "train_validation_split"
        validation_rankings: list[tuple[float, float, str, str, dict[str, float], dict[str, float], BacktestResponse]] = []
        validation_candidate_records: list[dict[str, object]] = []
        for candidate, score_weights, combo_weights in candidate_profiles:
            if cancel_check:
                cancel_check()
            validation_score, validation_stats, _ = _evaluate_weight_config(
                history_asc,
                validation_draws,
                scheme_count=scheme_count,
                strategy_mode=strategy_mode,
                ticket_mode=ticket_mode,
                score_weights=score_weights,
                combo_weights=combo_weights,
                history_context_cache=validation_history_context_cache,
                issue_evaluation_cache=issue_evaluation_cache,
                search_profile="tuning",
                cancel_check=cancel_check,
            )
            _, validation_performance_score, validation_coverage_score, validation_coverage_components = _tuning_score_breakdown(
                won_schemes=validation_stats.won_schemes,
                hit_issues=sum(1 for item in validation_stats.issues if item.won_count > 0),
                total_issues=validation_stats.total_issues,
                scheme_count=scheme_count,
                coverage_metrics=validation_stats.coverage_metrics,
                strategy_mode=strategy_mode,
                issue_results=validation_stats.issues,
            )
            candidate.validation_score = validation_score
            candidate.validation_performance_score = validation_performance_score
            candidate.validation_coverage_score = validation_coverage_score
            candidate.validation_coverage_components = validation_coverage_components
            candidate.validation_overall_win_rate = validation_stats.overall_win_rate
            candidate.validation_issue_hit_rate = validation_stats.issue_hit_rate
            candidate.validation_stability_adjusted_score = validation_score
            candidate.validation_stability_breakdown = BacktestStabilityBreakdown(
                base_score=round(validation_score, 4),
                adjusted_score=round(validation_score, 4),
            )
            candidate.validation_max_drawdown = _max_drawdown([item.model_dump() for item in validation_stats.issues])
            candidate.validation_max_miss_streak = _max_miss_streak([item.model_dump() for item in validation_stats.issues])
            validation_rankings.append(
                (
                    validation_score,
                    candidate.score,
                    candidate.name,
                    candidate.display_name,
                    score_weights.copy(),
                    combo_weights.copy(),
                    validation_stats,
                )
            )
            validation_candidate_records.append(
                {
                    "name": candidate.name,
                    "display_name": candidate.display_name,
                    "candidate": candidate,
                    "summary": _candidate_outcome_summary(validation_stats),
                    "stats": validation_stats,
                    "stage_score": validation_score,
                    "train_score": candidate.score,
                    "score_weights": score_weights.copy(),
                    "combo_weights": combo_weights.copy(),
                }
            )
        best_overall_validation_profile_name = _pick_best_overall_win_record_name(validation_candidate_records)
        validation_rankings.sort(key=lambda item: (-item[0], -item[1], item[2]))
        best_validation = validation_rankings[0]
        runner_up_validation = validation_rankings[1] if len(validation_rankings) > 1 else None
        selected_candidate_name = best_validation[2]
        selected_candidate_display_name = best_validation[3]
        selected_score_weights = best_validation[4].copy()
        selected_combo_weights = best_validation[5].copy()
        selected_validation_score = best_validation[0]
        selected_validation_stability_adjusted_score = best_validation[0]
        selected_validation_stability_breakdown = BacktestStabilityBreakdown(
            base_score=round(best_validation[0], 4),
            adjusted_score=round(best_validation[0], 4),
        )
        selected_validation_overall_win_rate = best_validation[6].overall_win_rate
        selected_validation_issue_hit_rate = best_validation[6].issue_hit_rate
        selected_validation_max_drawdown = _max_drawdown([item.model_dump() for item in best_validation[6].issues])
        selected_validation_max_miss_streak = _max_miss_streak([item.model_dump() for item in best_validation[6].issues])
        if runner_up_validation:
            runner_up_profile_name = runner_up_validation[2]
            runner_up_display_name = runner_up_validation[3]
            selection_margin = round(best_validation[0] - runner_up_validation[0], 4)
            selected_reason = f"按单次验证集分数选中，领先 {runner_up_display_name} {selection_margin:.4f}"
        else:
            selected_reason = "按单次验证集分数选中"

        if strategy_mode == "multi_cover" and scheme_count >= 5:
            guarded_overall_validation_candidate = _pick_guarded_overall_win_candidate(
                validation_candidate_records,
                baseline_name=HIGH_TIER_FALLBACK_PROFILE,
            )
            if guarded_overall_validation_candidate and not walk_forward_windows:
                selected_candidate_name = str(guarded_overall_validation_candidate["name"])
                selected_candidate_display_name = str(guarded_overall_validation_candidate["display_name"])
                selected_score_weights = dict(guarded_overall_validation_candidate["score_weights"])
                selected_combo_weights = dict(guarded_overall_validation_candidate["combo_weights"])
                guarded_validation_stats = guarded_overall_validation_candidate.get("stats")
                if isinstance(guarded_validation_stats, BacktestResponse):
                    selected_validation_score = float(guarded_overall_validation_candidate["stage_score"])
                    selected_validation_stability_adjusted_score = selected_validation_score
                    selected_validation_stability_breakdown = BacktestStabilityBreakdown(
                        base_score=round(selected_validation_score, 4),
                        adjusted_score=round(selected_validation_score, 4),
                    )
                    selected_validation_overall_win_rate = guarded_validation_stats.overall_win_rate
                    selected_validation_issue_hit_rate = guarded_validation_stats.issue_hit_rate
                    selected_validation_max_drawdown = _max_drawdown([item.model_dump() for item in guarded_validation_stats.issues])
                    selected_validation_max_miss_streak = _max_miss_streak([item.model_dump() for item in guarded_validation_stats.issues])
                selection_basis = "guarded_overall_validation_split"
                selected_reason = "在低奖不回退约束下，验证集优先选择综合中奖率达到 10% 的方案"
                selection_margin = None
            guarded_validation_candidate = _pick_guarded_high_tier_candidate(
                validation_candidate_records,
                baseline_name=HIGH_TIER_FALLBACK_PROFILE,
            )
            if guarded_validation_candidate and not walk_forward_windows and not guarded_overall_validation_candidate:
                selected_candidate_name = str(guarded_validation_candidate["name"])
                selected_candidate_display_name = str(guarded_validation_candidate["display_name"])
                selected_score_weights = dict(guarded_validation_candidate["score_weights"])
                selected_combo_weights = dict(guarded_validation_candidate["combo_weights"])
                guarded_validation_stats = guarded_validation_candidate.get("stats")
                if isinstance(guarded_validation_stats, BacktestResponse):
                    selected_validation_score = float(guarded_validation_candidate["stage_score"])
                    selected_validation_stability_adjusted_score = selected_validation_score
                    selected_validation_stability_breakdown = BacktestStabilityBreakdown(
                        base_score=round(selected_validation_score, 4),
                        adjusted_score=round(selected_validation_score, 4),
                    )
                    selected_validation_overall_win_rate = guarded_validation_stats.overall_win_rate
                    selected_validation_issue_hit_rate = guarded_validation_stats.issue_hit_rate
                    selected_validation_max_drawdown = _max_drawdown([item.model_dump() for item in guarded_validation_stats.issues])
                    selected_validation_max_miss_streak = _max_miss_streak([item.model_dump() for item in guarded_validation_stats.issues])
                selection_basis = "guarded_validation_split"
                selected_reason = "在低奖不回退约束下，验证集优先选择高奖级代理信号更强的方案"
                selection_margin = None

    if walk_forward_windows and candidate_profiles:
        selection_basis = "walk_forward_validation"
        candidate_by_name = {candidate.name: candidate for candidate, _, _ in candidate_profiles}
        profile_lookup = {
            candidate.name: (score_weights.copy(), combo_weights.copy())
            for candidate, score_weights, combo_weights in candidate_profiles
        }
        ranked_candidates = sorted(
            candidates,
            key=lambda item: (
                -(item.validation_score if item.validation_score is not None else item.score),
                -item.score,
                item.name,
            ),
        )
        walk_forward_candidate_names: list[str] = []
        for candidate in ranked_candidates:
            if candidate.name in walk_forward_candidate_names:
                continue
            walk_forward_candidate_names.append(candidate.name)
        for extra_name in (
            HIGH_TIER_FALLBACK_PROFILE,
            best_overall_train_profile_name,
            best_overall_validation_profile_name,
            str(guarded_validation_candidate["name"]) if guarded_validation_candidate else None,
            str(guarded_overall_validation_candidate["name"]) if guarded_overall_validation_candidate else None,
            selected_candidate_name,
        ):
            if not extra_name or extra_name in walk_forward_candidate_names:
                continue
            if extra_name in candidate_by_name:
                walk_forward_candidate_names.append(extra_name)
        ranked_for_walk_forward = [candidate_by_name[name] for name in walk_forward_candidate_names if name in candidate_by_name]
        walk_forward_rankings: list[
            tuple[float, float, float, float, str, str, dict[str, float], dict[str, float], int]
        ] = []
        walk_forward_candidate_records: list[dict[str, object]] = []
        for candidate in ranked_for_walk_forward:
            if cancel_check:
                cancel_check()
            profile_weights = profile_lookup.get(candidate.name)
            if not profile_weights:
                continue
            score_weights, combo_weights = profile_weights
            (
                walk_score,
                walk_overall,
                walk_issue,
                walk_coverage_score,
                walk_coverage_components,
                walk_windows,
                walk_details,
                walk_max_drawdown,
                walk_max_miss_streak,
                walk_total_issues,
                walk_stats,
            ) = _evaluate_walk_forward_candidate(
                history_asc,
                walk_forward_windows,
                scheme_count=scheme_count,
                strategy_mode=strategy_mode,
                ticket_mode=ticket_mode,
                score_weights=score_weights,
                combo_weights=combo_weights,
                issue_evaluation_cache=issue_evaluation_cache,
                window_history_context_caches=walk_forward_history_context_caches,
                cancel_check=cancel_check,
            )
            candidate_item = candidate_by_name.get(candidate.name)
            if candidate_item:
                candidate_item.walk_forward_score = walk_score
                if isinstance(walk_stats, BacktestResponse):
                    walk_performance_score = _performance_score_from_counts(
                        won_schemes=walk_stats.won_schemes,
                        hit_issues=sum(1 for item in walk_stats.issues if item.won_count > 0),
                        total_issues=walk_stats.total_issues,
                        scheme_count=scheme_count,
                        signal_totals=_performance_signal_totals(walk_stats.issues),
                    )
                else:
                    stats_total_issues = sum(window.test_issues for window in walk_details)
                    stats_total_won_schemes = int(round(walk_overall * stats_total_issues * scheme_count))
                    stats_total_hit_issues = int(round(walk_issue * stats_total_issues))
                    walk_performance_score = _performance_score_from_counts(
                        won_schemes=stats_total_won_schemes,
                        hit_issues=stats_total_hit_issues,
                        total_issues=stats_total_issues,
                        scheme_count=scheme_count,
                    )
                candidate_item.walk_forward_performance_score = walk_performance_score
                candidate_item.walk_forward_coverage_score = walk_coverage_score
                candidate_item.walk_forward_coverage_components = walk_coverage_components
                candidate_item.walk_forward_overall_win_rate = walk_overall
                candidate_item.walk_forward_issue_hit_rate = walk_issue
                candidate_item.walk_forward_windows = walk_windows
            stability, score_range = _summarize_walk_forward_stability(walk_details)
            walk_adjusted_score, walk_stability_breakdown = _walk_forward_adjusted_score(
                walk_score,
                score_range=score_range,
                max_drawdown=walk_max_drawdown,
                max_miss_streak=walk_max_miss_streak,
                issue_count=walk_total_issues,
                scheme_count=scheme_count,
                window_count=walk_windows,
                ticket_mode=ticket_mode,
            )
            if candidate_item:
                candidate_item.walk_forward_stability = stability
                candidate_item.walk_forward_score_range = score_range
                candidate_item.walk_forward_stability_adjusted_score = walk_adjusted_score
                candidate_item.walk_forward_stability_breakdown = walk_stability_breakdown
                candidate_item.walk_forward_max_drawdown = walk_max_drawdown
                candidate_item.walk_forward_max_miss_streak = walk_max_miss_streak
            walk_forward_details.append(
                BacktestTuningWalkForwardDetail(
                    name=candidate.name,
                    display_name=candidate.display_name,
                    stability=stability,
                    score_range=score_range,
                    windows=walk_details,
                )
            )
            walk_forward_rankings.append(
                (
                    walk_adjusted_score,
                    walk_score,
                    candidate.validation_score if candidate.validation_score is not None else candidate.score,
                    candidate.score,
                    candidate.name,
                    candidate.display_name,
                    score_weights.copy(),
                    combo_weights.copy(),
                    walk_windows,
                )
            )
            if isinstance(walk_stats, BacktestResponse):
                walk_forward_candidate_records.append(
                    {
                        "name": candidate.name,
                        "display_name": candidate.display_name,
                        "candidate": candidate,
                        "summary": _candidate_outcome_summary(walk_stats),
                        "stats": walk_stats,
                        "stage_score": walk_adjusted_score,
                        "raw_stage_score": walk_score,
                        "train_score": candidate.score,
                        "score_weights": score_weights.copy(),
                        "combo_weights": combo_weights.copy(),
                    }
                )
        if walk_forward_rankings:
            walk_forward_rankings.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[3], item[4]))
            best_walk_forward = walk_forward_rankings[0]
            runner_up_walk_forward = walk_forward_rankings[1] if len(walk_forward_rankings) > 1 else None
            selected_candidate_name = best_walk_forward[4]
            selected_candidate_display_name = best_walk_forward[5]
            selected_score_weights = best_walk_forward[6].copy()
            selected_combo_weights = best_walk_forward[7].copy()
            selected_walk_forward_stability_adjusted_score = best_walk_forward[0]
            selected_walk_forward_score = best_walk_forward[1]
            selected_walk_forward_windows = best_walk_forward[8]
            selected_candidate = candidate_by_name.get(selected_candidate_name)
            if selected_candidate:
                selected_walk_forward_overall_win_rate = selected_candidate.walk_forward_overall_win_rate
                selected_walk_forward_issue_hit_rate = selected_candidate.walk_forward_issue_hit_rate
                selected_walk_forward_stability = selected_candidate.walk_forward_stability
                selected_walk_forward_score_range = selected_candidate.walk_forward_score_range
                selected_validation_stability_adjusted_score = selected_candidate.validation_stability_adjusted_score
                selected_walk_forward_stability_breakdown = selected_candidate.walk_forward_stability_breakdown
                selected_walk_forward_max_drawdown = selected_candidate.walk_forward_max_drawdown
                selected_walk_forward_max_miss_streak = selected_candidate.walk_forward_max_miss_streak
            if runner_up_walk_forward:
                runner_up_profile_name = runner_up_walk_forward[4]
                runner_up_display_name = runner_up_walk_forward[5]
                selection_margin = round(best_walk_forward[0] - runner_up_walk_forward[0], 4)
                runner_up_candidate = candidate_by_name.get(runner_up_walk_forward[4])
                if runner_up_candidate:
                    runner_up_walk_forward_stability = runner_up_candidate.walk_forward_stability
                    runner_up_walk_forward_score_range = runner_up_candidate.walk_forward_score_range
                selected_reason = (
                    f"按 Walk-forward 稳定性修正后分数选中，领先 {runner_up_display_name} {selection_margin:.4f}"
                )
            else:
                selected_reason = "按 Walk-forward 稳定性修正后分数选中"
            if strategy_mode == "multi_cover" and scheme_count >= 5:
                guarded_overall_walk_candidate = _pick_guarded_overall_win_candidate(
                    walk_forward_candidate_records,
                    baseline_name=HIGH_TIER_FALLBACK_PROFILE,
                )
                if guarded_overall_walk_candidate:
                    selected_candidate_name = str(guarded_overall_walk_candidate["name"])
                    selected_candidate_display_name = str(guarded_overall_walk_candidate["display_name"])
                    selected_score_weights = dict(guarded_overall_walk_candidate["score_weights"])
                    selected_combo_weights = dict(guarded_overall_walk_candidate["combo_weights"])
                    guarded_walk_stats = guarded_overall_walk_candidate.get("stats")
                    selected_walk_forward_stability_adjusted_score = float(guarded_overall_walk_candidate["stage_score"])
                    selected_walk_forward_score = float(guarded_overall_walk_candidate.get("raw_stage_score") or selected_walk_forward_stability_adjusted_score)
                    selection_basis = "guarded_overall_walk_forward_validation"
                    selected_reason = "在低奖不回退约束下，Walk-forward 优先选择综合中奖率达到 10% 的方案"
                    selection_margin = None
                    guarded_candidate_item = candidate_by_name.get(selected_candidate_name)
                    if guarded_candidate_item:
                        selected_validation_score = guarded_candidate_item.validation_score
                        selected_validation_stability_adjusted_score = guarded_candidate_item.validation_stability_adjusted_score
                        selected_validation_stability_breakdown = guarded_candidate_item.validation_stability_breakdown
                        selected_validation_overall_win_rate = guarded_candidate_item.validation_overall_win_rate
                        selected_validation_issue_hit_rate = guarded_candidate_item.validation_issue_hit_rate
                        selected_validation_max_drawdown = guarded_candidate_item.validation_max_drawdown
                        selected_validation_max_miss_streak = guarded_candidate_item.validation_max_miss_streak
                        selected_walk_forward_windows = guarded_candidate_item.walk_forward_windows
                        selected_walk_forward_stability = guarded_candidate_item.walk_forward_stability
                        selected_walk_forward_score_range = guarded_candidate_item.walk_forward_score_range
                        selected_walk_forward_stability_breakdown = guarded_candidate_item.walk_forward_stability_breakdown
                        selected_walk_forward_max_drawdown = guarded_candidate_item.walk_forward_max_drawdown
                        selected_walk_forward_max_miss_streak = guarded_candidate_item.walk_forward_max_miss_streak
                    if isinstance(guarded_walk_stats, BacktestResponse):
                        selected_walk_forward_overall_win_rate = guarded_walk_stats.overall_win_rate
                        selected_walk_forward_issue_hit_rate = guarded_walk_stats.issue_hit_rate
                guarded_walk_candidate = _pick_guarded_high_tier_candidate(
                    walk_forward_candidate_records,
                    baseline_name=HIGH_TIER_FALLBACK_PROFILE,
                )
                if guarded_walk_candidate and not guarded_overall_walk_candidate:
                    selected_candidate_name = str(guarded_walk_candidate["name"])
                    selected_candidate_display_name = str(guarded_walk_candidate["display_name"])
                    selected_score_weights = dict(guarded_walk_candidate["score_weights"])
                    selected_combo_weights = dict(guarded_walk_candidate["combo_weights"])
                    guarded_walk_stats = guarded_walk_candidate.get("stats")
                    selected_walk_forward_stability_adjusted_score = float(guarded_walk_candidate["stage_score"])
                    selected_walk_forward_score = float(guarded_walk_candidate.get("raw_stage_score") or selected_walk_forward_stability_adjusted_score)
                    selection_basis = "guarded_walk_forward_validation"
                    selected_reason = "在低奖不回退约束下，Walk-forward 优先选择高奖级代理信号更强的方案"
                    selection_margin = None
                    guarded_candidate_item = candidate_by_name.get(selected_candidate_name)
                    if guarded_candidate_item:
                        selected_validation_score = guarded_candidate_item.validation_score
                        selected_validation_stability_adjusted_score = guarded_candidate_item.validation_stability_adjusted_score
                        selected_validation_stability_breakdown = guarded_candidate_item.validation_stability_breakdown
                        selected_validation_overall_win_rate = guarded_candidate_item.validation_overall_win_rate
                        selected_validation_issue_hit_rate = guarded_candidate_item.validation_issue_hit_rate
                        selected_validation_max_drawdown = guarded_candidate_item.validation_max_drawdown
                        selected_validation_max_miss_streak = guarded_candidate_item.validation_max_miss_streak
                        selected_walk_forward_windows = guarded_candidate_item.walk_forward_windows
                        selected_walk_forward_stability = guarded_candidate_item.walk_forward_stability
                        selected_walk_forward_score_range = guarded_candidate_item.walk_forward_score_range
                        selected_walk_forward_stability_breakdown = guarded_candidate_item.walk_forward_stability_breakdown
                        selected_walk_forward_max_drawdown = guarded_candidate_item.walk_forward_max_drawdown
                        selected_walk_forward_max_miss_streak = guarded_candidate_item.walk_forward_max_miss_streak
                    if isinstance(guarded_walk_stats, BacktestResponse):
                        selected_walk_forward_overall_win_rate = guarded_walk_stats.overall_win_rate
                        selected_walk_forward_issue_hit_rate = guarded_walk_stats.issue_hit_rate
    elif candidates and len(candidates) > 1:
        train_rankings = sorted(candidates, key=lambda item: (-item.score, item.name))
        runner_up_display_name = train_rankings[1].display_name
        selection_margin = round(train_rankings[0].score - train_rankings[1].score, 4)
        selected_reason = f"按训练样本得分选中，领先 {runner_up_display_name} {selection_margin:.4f}"

    if not validation_draws and not walk_forward_windows:
        if guarded_overall_train_candidate:
            selected_candidate_name = str(guarded_overall_train_candidate["name"])
            selected_candidate_display_name = str(guarded_overall_train_candidate["display_name"])
            selected_score_weights = dict(guarded_overall_train_candidate["score_weights"])
            selected_combo_weights = dict(guarded_overall_train_candidate["combo_weights"])
            selection_basis = "guarded_overall_train_only"
            selected_reason = "在低奖不回退约束下，训练样本优先选择综合中奖率达到 10% 的方案"
            selection_margin = None
        elif guarded_train_candidate:
            selected_candidate_name = str(guarded_train_candidate["name"])
            selected_candidate_display_name = str(guarded_train_candidate["display_name"])
            selected_score_weights = dict(guarded_train_candidate["score_weights"])
            selected_combo_weights = dict(guarded_train_candidate["combo_weights"])
            selection_basis = "guarded_train_only"
            selected_reason = "在低奖不回退约束下，训练样本优先选择高奖级代理信号更强的方案"
            selection_margin = None

    selection_warning = _build_selection_warning(
        selection_basis=selection_basis,
        selection_margin=selection_margin,
        selected_display_name=selected_candidate_display_name,
        selected_stability=selected_walk_forward_stability,
        selected_score_range=selected_walk_forward_score_range,
        runner_up_display_name=runner_up_display_name,
        runner_up_stability=runner_up_walk_forward_stability,
        runner_up_score_range=runner_up_walk_forward_score_range,
    )
    if selection_warning and runner_up_profile_name and runner_up_display_name:
        compare_profile = runner_up_profile_name
        compare_display_name = runner_up_display_name
        compare_reason = "更稳的次优方案，可切换查看其验证与 Walk-forward 表现"

    applied_profile = selected_candidate_name
    applied_display_name = selected_candidate_display_name
    applied_reason = "本次回测使用自动调参选中的方案"
    applied_is_override = False
    applied_score_weights = selected_score_weights.copy()
    applied_combo_weights = selected_combo_weights.copy()
    profile_lookup = _predefined_tuning_profile_lookup()
    profile_lookup.update({
        candidate.name: (candidate.display_name, score_weights.copy(), combo_weights.copy())
        for candidate, score_weights, combo_weights in candidate_profiles
    })
    if applied_profile_override:
        override_profile = profile_lookup.get(applied_profile_override)
        if override_profile:
            applied_profile = applied_profile_override
            applied_display_name = override_profile[0]
            applied_reason = "本次回测使用手动指定的调参方案"
            applied_is_override = applied_profile != selected_candidate_name
            applied_score_weights = override_profile[1].copy()
            applied_combo_weights = override_profile[2].copy()

    summary = BacktestTuningSummary(
        enabled=True,
        selected_profile=selected_candidate_name,
        selected_display_name=selected_candidate_display_name,
        selected_reason=selected_reason,
        applied_profile=applied_profile,
        applied_display_name=applied_display_name,
        applied_reason=applied_reason,
        applied_is_override=applied_is_override,
        selection_warning=selection_warning,
        compare_profile=compare_profile,
        compare_display_name=compare_display_name,
        compare_reason=compare_reason,
        runner_up_display_name=runner_up_display_name,
        selection_margin=selection_margin,
        sample_issues=len(target_draws),
        training_sample_issues=len(train_draws),
        validation_sample_issues=len(validation_draws),
        selection_basis=selection_basis,
        validation_score=selected_validation_score,
        validation_overall_win_rate=selected_validation_overall_win_rate,
        validation_issue_hit_rate=selected_validation_issue_hit_rate,
        validation_stability_adjusted_score=selected_validation_stability_adjusted_score,
        validation_stability_breakdown=selected_validation_stability_breakdown,
        validation_max_drawdown=selected_validation_max_drawdown,
        validation_max_miss_streak=selected_validation_max_miss_streak,
        walk_forward_window_count=selected_walk_forward_windows,
        walk_forward_score=selected_walk_forward_score,
        walk_forward_stability_adjusted_score=selected_walk_forward_stability_adjusted_score,
        walk_forward_stability_breakdown=selected_walk_forward_stability_breakdown,
        walk_forward_overall_win_rate=selected_walk_forward_overall_win_rate,
        walk_forward_issue_hit_rate=selected_walk_forward_issue_hit_rate,
        walk_forward_stability=selected_walk_forward_stability,
        walk_forward_score_range=selected_walk_forward_score_range,
        walk_forward_max_drawdown=selected_walk_forward_max_drawdown,
        walk_forward_max_miss_streak=selected_walk_forward_max_miss_streak,
        walk_forward_details=walk_forward_details,
        profiles=sorted(
            candidates,
            key=lambda item: (
                -(1 if item.walk_forward_score is not None else 0),
                -(item.walk_forward_stability_adjusted_score if item.walk_forward_stability_adjusted_score is not None else (
                    item.walk_forward_score if item.walk_forward_score is not None else (
                    item.validation_score if item.validation_score is not None else item.score
                ))),
                -(item.validation_score if item.validation_score is not None else item.score),
                -item.score,
                item.name,
            ),
        ),
        weights=_pack_tuning_weights(applied_score_weights, applied_combo_weights),
    )
    _store_tuning_summary(cache_key, summary)
    return _clone_tuning_summary(summary)

def _build_mode_summary(response: BacktestResponse) -> BacktestModeSummary:
    return BacktestModeSummary(
        strategy_mode=response.strategy_mode,
        total_issues=response.total_issues,
        total_generated_schemes=response.total_generated_schemes,
        won_schemes=response.won_schemes,
        total_prize_amount=response.total_prize_amount,
        total_cost=response.total_cost,
        net_profit=response.net_profit,
        overall_win_rate=response.overall_win_rate,
        issue_hit_rate=response.issue_hit_rate,
        ai_engine=response.ai_engine,
        coverage_metrics=response.coverage_metrics,
    )


def _build_issue_comparison(primary: BacktestResponse, secondary: BacktestResponse) -> list[BacktestIssueComparison]:
    secondary_map = {item.issue: item for item in secondary.issues}
    rows: list[BacktestIssueComparison] = []
    for item in primary.issues:
        other = secondary_map.get(item.issue)
        if not other:
            continue
        primary_amount = item.total_prize_amount or item.best_prize_amount or 0.0
        secondary_amount = other.total_prize_amount or other.best_prize_amount or 0.0
        rows.append(
            BacktestIssueComparison(
                issue=item.issue,
                draw_date=item.draw_date,
                primary=BacktestIssueModeComparison(
                    strategy_mode=primary.strategy_mode,
                    won_count=item.won_count,
                    best_prize_level=item.best_prize_level,
                    best_prize_amount=item.best_prize_amount,
                    cost=item.cost,
                ),
                secondary=BacktestIssueModeComparison(
                    strategy_mode=secondary.strategy_mode,
                    won_count=other.won_count,
                    best_prize_level=other.best_prize_level,
                    best_prize_amount=other.best_prize_amount,
                    cost=other.cost,
                ),
                won_count_delta=item.won_count - other.won_count,
                prize_amount_delta=round(primary_amount - secondary_amount, 2),
            )
        )
    rows.sort(
        key=lambda row: (
            -abs(row.prize_amount_delta),
            -abs(row.won_count_delta),
            row.issue,
        )
    )
    return rows


def _run_backtest_core(
    history_asc: list,
    *,
    recent_issues: int,
    scheme_count: int,
    strategy_mode: str,
    ticket_mode: str,
    ai_replay_mode: str,
    ai_config: AIConfigRequest | None,
    tuning_profile_override: str | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> BacktestResponse:
    backtest_ai_config = _resolve_backtest_ai_config(ai_replay_mode, ai_config)
    if len(history_asc) <= 1:
        response = build_backtest_stats([])
        response.requested_issues = recent_issues
        response.skipped_issues = 0
        response.confidence_threshold = _backtest_confidence_threshold(strategy_mode, scheme_count)
        response.scheme_count = scheme_count
        response.strategy_mode = strategy_mode  # type: ignore[assignment]
        response.ticket_mode = ticket_mode  # type: ignore[assignment]
        response.ai_replay_mode = ai_replay_mode  # type: ignore[assignment]
        response.theoretical_single_win_rate = round(_theoretical_single_win_rate(), 6)
        response.benchmarks = []
        response.window_summaries = []
        response.tuning_summary = BacktestTuningSummary(
            enabled=False,
            sample_issues=0,
            weights=_pack_tuning_weights(DEFAULT_SCORE_WEIGHTS.copy(), DEFAULT_COMBO_WEIGHTS.copy()),
        )
        response.mode_comparison = []
        response.issue_comparison = []
        return response

    target_draws = history_asc[-recent_issues:]
    issue_results: list[dict] = []
    random_issue_results: list[dict] = []
    window_model_issue_results: list[dict] = []
    issue_trials: list[dict] = []
    raw_diagnostic_rows: list[dict] = []
    calibration_history: list[dict] = []
    ai_engine: str | None = None
    confidence_threshold = _backtest_confidence_threshold(strategy_mode, scheme_count)
    skipped_issues = 0
    dynamic_threshold_total = 0.0
    dynamic_threshold_count = 0
    calibrated_threshold_total = 0.0
    history_context_cache = _build_history_context_cache(history_asc, target_draws)
    if progress_callback:
        progress_callback(
            stage="tuning",
            progress=0.02,
            message="正在分析调参与权重",
            processed_issues=0,
            total_issues=len(target_draws),
        )
    tuning_summary = _build_tuning_summary(
        history_asc,
        recent_issues=recent_issues,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ticket_mode=ticket_mode,
        applied_profile_override=tuning_profile_override,
        cancel_check=cancel_check,
    )
    score_weights, combo_weights = _resolve_tuning_weights(tuning_summary)
    if ai_replay_mode == "external_rerank":
        logger.info(
            "[Backtest] external AI rerank enabled: model=%s issues=%d",
            backtest_ai_config.model if backtest_ai_config else None,
            len(target_draws),
        )
    else:
        logger.info("[Backtest] using local-only replay for %d issues", len(target_draws))

    prepared_targets: list[tuple[int, object, list, PrecomputedHistoryFeatures]] = []
    for index, target in enumerate(target_draws):
        if cancel_check:
            cancel_check()
        history_item = history_context_cache.get(target.issue)
        if not history_item:
            continue
        prior_history_desc, history_context = history_item
        if history_context.history_size < 30:
            continue
        prepared_targets.append((index, target, prior_history_desc, history_context))

    total_targets = len(prepared_targets)
    processed_targets = 0
    tuning_profile_name = tuning_summary.applied_display_name or tuning_summary.selected_display_name
    worker_count = _backtest_parallel_workers(total_targets, ai_replay_mode=ai_replay_mode)
    logger.info(
        "[Backtest] prepared %d runnable issues out of %d, workers=%d",
        total_targets,
        len(target_draws),
        worker_count,
    )
    raw_issue_payloads: list[dict] = []

    def _update_running_progress() -> None:
        if not progress_callback:
            return
        progress_callback(
            stage="running",
            progress=0.08 + (processed_targets / max(1, total_targets)) * 0.84,
            message=f"正在回放第 {processed_targets}/{total_targets} 期",
            processed_issues=processed_targets,
            total_issues=total_targets,
        )

    if worker_count <= 1:
        for index, target, prior_history_desc, history_context in prepared_targets:
            if cancel_check:
                cancel_check()
            raw_issue_payloads.append(
                _evaluate_backtest_issue(
                    index,
                    target=target,
                    prior_history_desc=prior_history_desc,
                    history_context=history_context,
                    scheme_count=scheme_count,
                    strategy_mode=strategy_mode,
                    ticket_mode=ticket_mode,
                    backtest_ai_config=backtest_ai_config,
                    score_weights=score_weights,
                    combo_weights=combo_weights,
                    tuning_profile=tuning_profile_name,
                )
            )
            processed_targets += 1
            _update_running_progress()
    else:
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="backtest") as executor:
            future_map = {
                executor.submit(
                    _evaluate_backtest_issue,
                    index,
                    target=target,
                    prior_history_desc=prior_history_desc,
                    history_context=history_context,
                    scheme_count=scheme_count,
                    strategy_mode=strategy_mode,
                    ticket_mode=ticket_mode,
                    backtest_ai_config=backtest_ai_config,
                    score_weights=score_weights,
                    combo_weights=combo_weights,
                    tuning_profile=tuning_profile_name,
                ): target.issue
                for index, target, prior_history_desc, history_context in prepared_targets
            }
            for future in as_completed(future_map):
                if cancel_check:
                    cancel_check()
                raw_issue_payloads.append(future.result())
                processed_targets += 1
                _update_running_progress()

    raw_issue_payloads.sort(key=lambda item: int(item["index"]))
    count_policy = "must_issue_value_ladder" if strategy_mode != "single_hit" else "zone_ladder"
    for raw in raw_issue_payloads:
        if ai_engine is None and raw.get("ai_engine"):
            ai_engine = str(raw["ai_engine"])
        dynamic_threshold = float(raw["dynamic_threshold"])
        dynamic_threshold_total += dynamic_threshold
        dynamic_threshold_count += 1
        issue_confidence = float(raw["issue_confidence"])
        calibrated_confidence = _calibrate_issue_confidence(
            issue_confidence,
            calibration_history,
            strategy_mode=strategy_mode,
        )
        calibrated_threshold = _calibrate_issue_confidence(
            dynamic_threshold,
            calibration_history,
            strategy_mode=strategy_mode,
        )
        calibrated_threshold_total += calibrated_threshold
        front_confidence = float(raw["front_confidence"])
        back_confidence = float(raw["back_confidence"])
        front_calibrated_confidence = _calibrate_zone_confidence(
            front_confidence,
            calibration_history,
            strategy_mode=strategy_mode,
            zone="front",
        )
        back_calibrated_confidence = _calibrate_zone_confidence(
            back_confidence,
            calibration_history,
            strategy_mode=strategy_mode,
            zone="back",
        )
        front_gate = _zone_confidence_gate(
            strategy_mode=strategy_mode,
            zone="front",
            candidates=raw["front_candidates"],
        )
        back_gate = _zone_confidence_gate(
            strategy_mode=strategy_mode,
            zone="back",
            candidates=raw["back_candidates"],
        )
        chosen_scheme_count = _scheme_count_for_issue(
            issue_confidence=calibrated_confidence,
            threshold=calibrated_threshold,
            max_scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            raw_issue_confidence=issue_confidence,
            front_confidence=front_calibrated_confidence,
            front_gate=front_gate,
            back_confidence=back_calibrated_confidence,
            back_gate=back_gate,
            count_policy=count_policy,
        )
        decision_tier = _decision_tier_label(
            chosen_scheme_count,
            max_scheme_count=scheme_count,
            strategy_mode=strategy_mode,
        )
        should_observe = chosen_scheme_count <= 0
        decision_reasons: list[str] = []
        if chosen_scheme_count <= 0:
            decision_reasons.append("校准后置信度或分区质量未通过实战门槛，当前建议观望。")
        else:
            decision_reasons.append(
                f"校准后置信度 {calibrated_confidence:.4f}，实战阈值 {calibrated_threshold:.4f}，当前采用 {count_policy} 分层策略。"
            )
        if front_calibrated_confidence < front_gate:
            decision_reasons.append(
                f"前区校准置信 {front_calibrated_confidence:.4f} 低于门槛 {front_gate:.4f}，已收缩出手层级。"
            )
        if back_calibrated_confidence < back_gate:
            decision_reasons.append(
                f"后区校准置信 {back_calibrated_confidence:.4f} 低于门槛 {back_gate:.4f}，已进一步收缩出手层级。"
            )
        if chosen_scheme_count > 1:
            decision_reasons.append(
                f"当前层级为{_decision_tier_display_name(decision_tier or 'expand')}，保留 {chosen_scheme_count} 组方案。"
            )
        elif chosen_scheme_count == 1:
            decision_reasons.append(
                f"当前层级为{_decision_tier_display_name(decision_tier or 'probe')}，仅保留 1 组高优先级方案。"
            )
        decision_reason = " ".join(decision_reasons)
        raw_selected_schemes = raw["selected_schemes"]
        raw_scheme_evaluations = raw["scheme_evaluations"]
        original_selected_schemes = raw_selected_schemes
        original_scheme_evaluations = raw_scheme_evaluations
        full_hit = any(item["status"] == "won" for item in raw_scheme_evaluations)
        fallback_calibration_history = list(calibration_history)
        if count_policy == "must_issue_value_ladder" and strategy_mode != "single_hit" and chosen_scheme_count == 1:
            fallback_index = _must_issue_fallback_index(
                [scheme.label for scheme in raw_selected_schemes],
                issue=raw["issue"],
                calibration_history=fallback_calibration_history,
            )
            fallback_index = _must_issue_high_tier_fallback_index(
                [scheme.label for scheme in raw_selected_schemes],
                issue_confidence=issue_confidence,
                front_confidence=front_confidence,
                back_confidence=back_confidence,
                decision_tier=decision_tier,
                fallback_index=fallback_index,
            )
            if 0 <= fallback_index < len(raw_scheme_evaluations):
                fallback_scheme = raw_selected_schemes[fallback_index]
                raw_selected_schemes = [
                    fallback_scheme,
                    *raw_selected_schemes[:fallback_index],
                    *raw_selected_schemes[fallback_index + 1:],
                ]
                raw_scheme_evaluations = [
                    raw_scheme_evaluations[fallback_index],
                    *raw_scheme_evaluations[:fallback_index],
                    *raw_scheme_evaluations[fallback_index + 1:],
                ]
                decision_reasons.append(f"低置信必出期已按历史标签分桶优先采用{fallback_scheme.label}方案。")
                decision_reason = " ".join(decision_reasons)
            expanded_count = _low_tier_expand_count(
                count_policy=count_policy,
                strategy_mode=strategy_mode,
                chosen_scheme_count=chosen_scheme_count,
                available=len(raw_selected_schemes),
                target=scheme_count,
            )
            if expanded_count > chosen_scheme_count:
                decision_reasons.append(
                    f"为提升五至七等奖中奖注数，已将本期方案从 1 注扩展至 {expanded_count} 注。"
                )
                decision_reason = " ".join(decision_reasons)
                chosen_scheme_count = expanded_count
        label_hits = {
            scheme.label: 1 if evaluation.get("status") == "won" else 0
            for scheme, evaluation in zip(original_selected_schemes, original_scheme_evaluations)
        }
        calibration_history.append(
            {
                "raw_confidence": issue_confidence,
                "hit": 1 if full_hit else 0,
                "raw_front_confidence": front_confidence,
                "front_hit": _zone_hit_from_evaluations(original_scheme_evaluations, zone="front"),
                "raw_back_confidence": back_confidence,
                "back_hit": _zone_hit_from_evaluations(original_scheme_evaluations, zone="back"),
                "issue_mod_7": int(raw["issue"]) % 7,
                "label_hits": label_hits,
            }
        )
        selected_schemes = raw_selected_schemes[:chosen_scheme_count] if chosen_scheme_count > 0 else []
        scheme_evaluations = raw_scheme_evaluations[:chosen_scheme_count] if chosen_scheme_count > 0 else []
        evaluation_summary = _summarize_scheme_evaluations(scheme_evaluations)
        quality_signals = _issue_quality_signals_from_evaluations(scheme_evaluations)
        coverage_metrics = _scheme_coverage_metrics(selected_schemes)
        issue_trials.append(
            {
                "issue": raw["issue"],
                "draw_date": raw["draw_date"],
                "tuning_profile": raw["tuning_profile"],
                "issue_confidence": issue_confidence,
                "calibrated_confidence": calibrated_confidence,
                "applied_threshold": calibrated_threshold,
                "front_confidence": round(front_confidence, 4),
                "front_calibrated_confidence": front_calibrated_confidence,
                "front_gate": round(front_gate, 4),
                "back_confidence": round(back_confidence, 4),
                "back_calibrated_confidence": back_calibrated_confidence,
                "back_gate": round(back_gate, 4),
                "count_policy": count_policy,
                "decision_tier": decision_tier,
                "deep_search_triggered": raw["deep_search_triggered"],
                "deep_search_reason": raw["deep_search_reason"],
                "decision_reason": decision_reason,
                "schemes": raw_selected_schemes,
                "evaluations": raw_scheme_evaluations,
                "front_candidates": raw["front_candidates"],
                "back_candidates": raw["back_candidates"],
                "calibration_history": fallback_calibration_history,
            }
        )
        raw_diagnostic_rows.append(
            {
                "issue": raw["issue"],
                "draw_date": raw["draw_date"],
                "chosen_scheme_count": chosen_scheme_count,
                "issue_confidence": issue_confidence,
                "calibrated_confidence": calibrated_confidence,
                "dynamic_threshold": raw["dynamic_threshold"],
                "applied_threshold": calibrated_threshold,
                "front_confidence": round(front_confidence, 4),
                "front_calibrated_confidence": front_calibrated_confidence,
                "front_gate": round(front_gate, 4),
                "back_confidence": round(back_confidence, 4),
                "back_calibrated_confidence": back_calibrated_confidence,
                "back_gate": round(back_gate, 4),
                "decision_tier": decision_tier,
                "schemes": [
                    {
                        "label": scheme.label,
                        "confidence": scheme.confidence,
                        "front_numbers": scheme.front_numbers,
                        "back_numbers": scheme.back_numbers,
                        **evaluation,
                    }
                    for scheme, evaluation in zip(raw_selected_schemes, raw_scheme_evaluations)
                ],
                "front_candidates": [item.model_dump(mode="json") for item in raw["front_candidates"]],
                "back_candidates": [item.model_dump(mode="json") for item in raw["back_candidates"]],
            }
        )
        issue_results.append(
            {
                "issue": raw["issue"],
                "draw_date": raw["draw_date"],
                "scheme_count": len(selected_schemes),
                "ticket_mode": ticket_mode,
                "tuning_profile": raw["tuning_profile"],
                "issue_confidence": issue_confidence,
                "calibrated_confidence": calibrated_confidence,
                "applied_threshold": calibrated_threshold,
                "should_observe": should_observe,
                "front_confidence": round(front_confidence, 4),
                "front_calibrated_confidence": front_calibrated_confidence,
                "front_gate": round(front_gate, 4),
                "back_confidence": round(back_confidence, 4),
                "back_calibrated_confidence": back_calibrated_confidence,
                "back_gate": round(back_gate, 4),
                "count_policy": count_policy,
                "decision_tier": decision_tier,
                "deep_search_triggered": raw["deep_search_triggered"],
                "deep_search_reason": raw["deep_search_reason"],
                "decision_reason": decision_reason,
                "won_count": evaluation_summary["won_count"],
                "best_prize_level": evaluation_summary["best_prize_level"],
                "best_prize_amount": evaluation_summary["best_prize_amount"],
                "total_prize_amount": evaluation_summary["total_prize_amount"],
                "winning_scheme_labels": evaluation_summary["winning_scheme_labels"],
                "prize_level_hits": evaluation_summary["prize_level_hits"],
                "prize_level_amounts": evaluation_summary["prize_level_amounts"],
                **quality_signals,
                "cost": round(len(selected_schemes) * _ticket_unit_price(ticket_mode), 2),
                "front_pairwise_overlap_avg": coverage_metrics.front_pairwise_overlap_avg,
                "back_pairwise_overlap_avg": coverage_metrics.back_pairwise_overlap_avg,
                "back_pair_reuse_rate": coverage_metrics.back_pair_reuse_rate,
                "fresh_back_number_rate": coverage_metrics.fresh_back_number_rate,
            }
        )
        window_summary = raw["window_summary"]
        window_model_issue_results.append(
            {
                "issue": raw["issue"],
                "draw_date": raw["draw_date"],
                "scheme_count": scheme_count,
                "won_count": window_summary["won_count"],
                "best_prize_level": window_summary["best_prize_level"],
                "best_prize_amount": window_summary["best_prize_amount"],
                "total_prize_amount": window_summary["total_prize_amount"],
                "winning_scheme_labels": [],
                "prize_level_hits": window_summary["prize_level_hits"],
                "prize_level_amounts": window_summary["prize_level_amounts"],
                "ticket_mode": ticket_mode,
                "cost": raw["cost"],
            }
        )
        random_issue_results.extend(raw["random_issue_results"])

    raw_diag_path = os.environ.get("BACKTEST_RAW_DIAG_PATH")
    if raw_diag_path:
        with open(raw_diag_path, "w", encoding="utf-8") as file:
            json.dump(raw_diagnostic_rows, file, ensure_ascii=False, default=str)

    response = build_backtest_stats(issue_results)  # type: ignore[arg-type]
    response.threshold_scan = _threshold_scan_results(
        issue_trials,
        strategy_mode=strategy_mode,
        max_scheme_count=scheme_count,
        ticket_mode=ticket_mode,
    )
    default_threshold = round(
        (calibrated_threshold_total / dynamic_threshold_count) if dynamic_threshold_count else confidence_threshold,
        4,
    )
    applied_threshold = default_threshold
    applied_skipped_issues = skipped_issues
    current_policy_name = count_policy
    policy_selection_reason = f"回测按 {count_policy} 分层策略实际出号统计，低置信期可观望或减少组合数。"
    default_selection_score, _, _, default_max_drawdown, default_max_miss_streak, default_stability_breakdown = _selection_metrics_from_issue_results(
        issue_results,
        strategy_mode=strategy_mode,
        scheme_count=max(1, scheme_count),
    )
    threshold_selection_reason = (
        f"回测按 {count_policy} 分层策略最多保留 {scheme_count} 组；阈值扫描仅作辅助参考，当前方案最大回撤 {default_max_drawdown:.2f}，最长空窗 {default_max_miss_streak} 期。"
    )
    response.recent_issues = recent_issues
    response.requested_issues = recent_issues
    response.skipped_issues = applied_skipped_issues
    response.confidence_threshold = applied_threshold
    response.scheme_count = scheme_count
    response.ai_engine = ai_engine
    response.strategy_mode = strategy_mode  # type: ignore[assignment]
    response.ticket_mode = ticket_mode  # type: ignore[assignment]
    response.ai_replay_mode = ai_replay_mode  # type: ignore[assignment]
    response.count_policy = current_policy_name
    response.threshold_selection_reason = threshold_selection_reason
    response.policy_selection_reason = policy_selection_reason
    response.stability_breakdown = response.stability_breakdown or default_stability_breakdown
    response.max_drawdown = _max_drawdown([item.model_dump() for item in response.issues])
    response.max_miss_streak = _max_miss_streak([item.model_dump() for item in response.issues])
    response.theoretical_single_win_rate = round(_theoretical_single_win_rate(), 6)
    response.window_summaries = _build_window_summaries(
        [
            {
                "issue": item.issue,
                "draw_date": item.draw_date,
                "scheme_count": item.scheme_count,
                "won_count": item.won_count,
                "best_prize_level": item.best_prize_level,
                "best_prize_amount": item.best_prize_amount,
                "total_prize_amount": item.total_prize_amount,
                "winning_scheme_labels": item.winning_scheme_labels,
                "prize_level_hits": item.prize_level_hits,
                "prize_level_amounts": item.prize_level_amounts,
                "cost": item.cost,
                "front_pairwise_overlap_avg": item.front_pairwise_overlap_avg,
                "back_pairwise_overlap_avg": item.back_pairwise_overlap_avg,
                "back_pair_reuse_rate": item.back_pair_reuse_rate,
                "fresh_back_number_rate": item.fresh_back_number_rate,
            }
            for item in response.issues
        ]
    )
    response.tuning_summary = tuning_summary
    response.benchmarks = [
        _build_benchmark(
            "random_uniform_avg",
            "随机均匀选号均值",
            random_issue_results,
            sample_runs=RANDOM_BASELINE_RUNS,
        ),
        _build_benchmark(
            "window_frequency_model",
            "窗口频率模型",
            window_model_issue_results,
        ),
    ]
    response.mode_comparison = []
    response.issue_comparison = []
    if progress_callback:
        progress_callback(
            stage="finalizing",
            progress=0.96,
            message="正在汇总结果",
            processed_issues=response.total_issues,
            total_issues=max(response.total_issues, total_targets),
        )
    return response


def run_backtest(
    recent_issues: int = 30,
    scheme_count: int = 3,
    strategy_mode: str = "multi_cover",
    ticket_mode: str = "basic",
    ai_replay_mode: str = "local_only",
    compare_modes: bool = False,
    ai_config: AIConfigRequest | None = None,
    tuning_profile_override: str | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> BacktestResponse:
    history_asc = get_all_history_asc()
    response = _run_backtest_core(
        history_asc,
        recent_issues=recent_issues,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ticket_mode=ticket_mode,
        ai_replay_mode=ai_replay_mode,
        ai_config=ai_config,
        tuning_profile_override=tuning_profile_override,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    if response.tuning_summary and response.tuning_summary.applied_is_override:
        auto_response = _run_backtest_core(
            history_asc,
            recent_issues=recent_issues,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ticket_mode=ticket_mode,
            ai_replay_mode=ai_replay_mode,
            ai_config=ai_config,
            tuning_profile_override=None,
            progress_callback=(
                (lambda **kwargs: progress_callback(
                    stage="compare_profiles",
                    progress=0.92 + kwargs.get("progress", 0.0) * 0.04,
                    message="正在对比自动方案与当前方案",
                    processed_issues=kwargs.get("processed_issues", 0),
                    total_issues=kwargs.get("total_issues", 0),
                )) if progress_callback else None
            ),
            cancel_check=cancel_check,
        )
        prize_delta = round(response.total_prize_amount - auto_response.total_prize_amount, 2)
        issue_hit_rate_delta = round(response.issue_hit_rate - auto_response.issue_hit_rate, 4)
        response_roi = response.net_profit / response.total_cost if response.total_cost else 0.0
        auto_roi = auto_response.net_profit / auto_response.total_cost if auto_response.total_cost else 0.0
        roi_delta = round(response_roi - auto_roi, 4)
        response.tuning_summary.applied_total_prize_delta = prize_delta
        response.tuning_summary.applied_issue_hit_rate_delta = issue_hit_rate_delta
        response.tuning_summary.applied_roi_delta = roi_delta
        response.tuning_summary.applied_delta_summary = _build_applied_delta_summary(
            selected_display_name=response.tuning_summary.selected_display_name or "自动方案",
            applied_display_name=response.tuning_summary.applied_display_name or "当前方案",
            prize_delta=prize_delta,
            issue_hit_rate_delta=issue_hit_rate_delta,
            roi_delta=roi_delta,
        )
        response.tuning_summary.applied_issue_comparison = _build_tuning_issue_comparison(
            response,
            auto_response,
            applied_profile_name=response.tuning_summary.applied_profile or "applied",
            applied_display_name=response.tuning_summary.applied_display_name or "当前方案",
            selected_profile_name=response.tuning_summary.selected_profile or "selected",
            selected_display_name=response.tuning_summary.selected_display_name or "自动方案",
        )
    if not compare_modes:
        return response

    other_mode = "single_hit" if strategy_mode == "multi_cover" else "multi_cover"
    other_response = _run_backtest_core(
        history_asc,
        recent_issues=recent_issues,
        scheme_count=scheme_count,
        strategy_mode=other_mode,
        ticket_mode=ticket_mode,
        ai_replay_mode=ai_replay_mode,
        ai_config=ai_config,
        tuning_profile_override=tuning_profile_override,
        progress_callback=(
            (lambda **kwargs: progress_callback(
                stage="compare_modes",
                progress=0.96 + kwargs.get("progress", 0.0) * 0.03,
                message="正在生成模式对比",
                processed_issues=kwargs.get("processed_issues", 0),
                total_issues=kwargs.get("total_issues", 0),
            )) if progress_callback else None
        ),
        cancel_check=cancel_check,
    )
    response.mode_comparison = [
        _build_mode_summary(response),
        _build_mode_summary(other_response),
    ]
    response.issue_comparison = _build_issue_comparison(response, other_response)
    return response
