from __future__ import annotations

from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
import json
import logging
import os
import random
from threading import Lock
from time import monotonic
from uuid import uuid4
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
    FullHistoryCacheProfileStatus,
    FullHistoryCacheRebuildJob,
    FullHistoryCacheStatus,
)
from app.services.meihua import (
    DEFAULT_COMBO_WEIGHTS,
    DEFAULT_SCORE_WEIGHTS,
    PrecomputedHistoryFeatures,
    build_history_feature_context,
    generate_divination,
)
from app.services.repository import PRIZE_LEVEL_ORDER, build_backtest_stats, evaluate_scheme_against_draw, get_all_history_asc, get_meta

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
FULL_HISTORY_CACHE_ALGORITHM_VERSION = "full-history-cache-v2026-06-01-02"
FULL_HISTORY_CACHE_MANIFEST_PREFIX = "full_history_cache"
FULL_HISTORY_CACHE_MAX_JOBS = 12
FULL_HISTORY_CACHE_MAX_PARALLEL_JOBS = min(4, max(2, (os.cpu_count() or 4) // 2))
FULL_HISTORY_CACHE_PROFILE_MAX_WORKERS = 2
FULL_HISTORY_CACHE_STATUS_MAX_WORKERS = 4
FULL_HISTORY_CACHE_STATUS_TTL_SECONDS = 0.75
FULL_HISTORY_CACHE_EXTENDED_PROFILE_MAX_SCHEME_COUNT = 3
FULL_HISTORY_CACHE_ISSUE_CHUNK_SIZE = 256
FAST_TUNING_RECENT_ISSUES_THRESHOLD = 40
FAST_TUNING_TARGET_ISSUES_THRESHOLD = 40
FAST_TUNING_COARSE_QUOTA = 12
TUNING_SUMMARY_CACHE_MAX_ITEMS = 16
BACKTEST_PARALLEL_MIN_ISSUES = 24
BACKTEST_LOCAL_MAX_WORKERS = min(12, max(4, os.cpu_count() or 4))
BACKTEST_EXTERNAL_AI_MAX_WORKERS = 2
LIVE_DIVINATION_PARALLEL_MAX_WORKERS = 3
SMART_BALANCE_CANDIDATE_BACKFILL_MAX_WORKERS = min(6, max(2, (os.cpu_count() or 4) // 2))
SMART_BALANCE_REPORT_LOAD_MAX_WORKERS = min(6, max(2, (os.cpu_count() or 4) // 2))
SMART_BALANCE_REPORT_SIGNATURE_TTL_SECONDS = 0.75
OVERALL_WIN_RATE_TARGET = 0.10
SMART_BALANCE_MODE = "smart_balance"
SMART_BALANCE_WINDOW = 60
SMART_BALANCE_GUARD_WINDOW = 420
BACKTEST_MIN_HISTORY_SIZE = 30
SMART_BALANCE_LIVE_WINDOW = 30
SMART_BALANCE_SWITCH_MARGIN = 0.02
SMART_BALANCE_HIT_WEIGHT = 0.35
SMART_BALANCE_WIN_WEIGHT = 0.08
SMART_BALANCE_AMOUNT_DIVISOR = 900.0
LIVE_PRIORITY_RECENT_WINDOW = 30
LIVE_PRIORITY_MID_WINDOW = 60
LIVE_PRIORITY_RECENT_WEIGHT = 1.35
LIVE_PRIORITY_MID_WEIGHT = 1.12
LIVE_PRIORITY_MISS_STREAK_SOFT_CAP = 3
LIVE_PRIORITY_MISS_STREAK_HARD_CAP = 5
LIVE_PRIORITY_SCORE_BONUS = 0.05
LIVE_PRIORITY_HIT_RATE_WEIGHT = 0.55
LIVE_PRIORITY_WIN_RATE_WEIGHT = 0.18
LIVE_PRIORITY_MISS_STREAK_PENALTY = 0.018
LIVE_PRIORITY_OBSERVE_MARGIN = 0.012
LIVE_PRIORITY_GUARDED_MARGIN = 0.026
LIVE_PRIORITY_PRESS_MARGIN = 0.082
SMART_BALANCE_PRIZE_LEVEL_SCORE_WEIGHTS = {
    "\u4e00\u7b49\u5956": 18.0,
    "\u4e8c\u7b49\u5956": 12.0,
    "\u4e09\u7b49\u5956": 6.8,
    "\u56db\u7b49\u5956": 4.2,
    "\u4e94\u7b49\u5956": 1.8,
    "\u516d\u7b49\u5956": 0.75,
    "\u4e03\u7b49\u5956": 0.22,
}
SMART_BALANCE_PROFILE_CANDIDATES = (
    ("multi_cover", "balanced+balanced_combo"),
    ("multi_cover", "frequency_revert+three_pack_low_tier_cover"),
    ("multi_cover", "recent_bias+three_pack_low_tier_cover"),
    ("multi_cover", "recent_bias+three_pack_hit_guarded"),
    ("multi_cover", "frequency_revert+candidate_focus"),
    ("multi_cover", "frequency_revert+candidate_focus_jackpot_floor_guarded"),
    ("multi_cover", "balanced+front_focus"),
    ("multi_cover", "balanced+front_focus_floor_guarded"),
    ("multi_cover", "recent_bias+front_focus_floor_guarded"),
    ("multi_cover", "frequency_revert+three_pack_hybrid_core"),
    ("multi_cover", "frequency_revert+ultra_core_jackpot"),
    ("multi_cover", "frequency_revert+front_back_split"),
    ("single_hit", "balanced+balanced_combo"),
)
SMART_BALANCE_PROFILE_NAMES = tuple(
    f"{strategy_mode}:{profile_name}" for strategy_mode, profile_name in SMART_BALANCE_PROFILE_CANDIDATES
)
SMART_BALANCE_REPORT_PROFILE_MAP = {
    "default_multi": "multi_cover:balanced+balanced_combo",
    "lowtier_multi": "multi_cover:frequency_revert+three_pack_low_tier_cover",
    "recent_lowtier_multi": "multi_cover:recent_bias+three_pack_low_tier_cover",
    "recent_hit_guarded_multi": "multi_cover:recent_bias+three_pack_hit_guarded",
    "candidate_multi": "multi_cover:frequency_revert+candidate_focus",
    "hybrid_guarded_multi": "multi_cover:frequency_revert+candidate_focus_jackpot_floor_guarded",
    "front_focus_multi": "multi_cover:balanced+front_focus",
    "front_focus_guarded_multi": "multi_cover:balanced+front_focus_floor_guarded",
    "recent_front_focus_guarded_multi": "multi_cover:recent_bias+front_focus_floor_guarded",
    "front_back_multi": "multi_cover:frequency_revert+front_back_split",
    "single_hit_default": "single_hit:balanced+balanced_combo",
}
SMART_BALANCE_REPORT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "reports", "smart_balance_extreme_full_replay.json")
)
SMART_BALANCE_CANDIDATE_REPORT_FILES = {
    "default_multi": "all_history_backtest_3_basic_multicover_compare.json",
    "lowtier_multi": "optimized_full_backtest_3_basic_lowtier.json",
    "candidate_multi": "optimized_full_backtest_3_basic_candidate_focus.json",
    "front_back_multi": "optimized_full_backtest_3_basic_front_back_split.json",
}
_tuning_summary_cache: dict[tuple, BacktestTuningSummary] = {}
_smart_balance_report_cache_signature: tuple[tuple[str, float, int], ...] | None = None
_smart_balance_report_candidate_cache: dict[str, dict[str, dict]] | None = None
_smart_balance_report_signature_cache: dict[tuple[int, str], tuple[float, tuple[tuple[str, float, int], ...]]] = {}
_smart_balance_report_cache_lock = Lock()
_json_dict_file_cache: dict[str, tuple[tuple[float, int], dict | None]] = {}
_json_dict_file_cache_lock = Lock()
_full_history_status_cache: dict[str, tuple[float, FullHistoryCacheStatus]] = {}
_full_history_status_cache_lock = Lock()
_full_history_cache_executor = ThreadPoolExecutor(
    max_workers=FULL_HISTORY_CACHE_MAX_PARALLEL_JOBS,
    thread_name_prefix="full-history-cache",
)
JsonFileSignature = tuple[float, int]
_full_history_cache_jobs: dict[str, "_FullHistoryCacheJobState"] = {}
_full_history_cache_lock = Lock()
SMART_BALANCE_SIGNAL_SCORE_WEIGHTS = {
    "top3_hit": 2.40,
    "five_plus_two_hit": 2.10,
    "five_plus_one_hit": 1.50,
    "top4_hit": 1.10,
    "four_plus_two_hit": 0.75,
    "front_5_hit": 0.65,
    "front_4plus_hit": 0.30,
    "back_2plus_hit": 0.20,
}


@dataclass(frozen=True)
class SmartBalanceLiveProfile:
    profile_name: str
    strategy_mode: str
    display_name: str
    score_weights: dict[str, float]
    combo_weights: dict[str, float]
    selection_reason: str


@dataclass
class _FullHistoryCacheJobState:
    job_id: str
    scheme_count: int
    ticket_mode: str
    status: str = "queued"
    progress: float = 0.0
    message: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class FullHistoryCacheStaleError(ValueError):
    def __init__(self, status: FullHistoryCacheStatus):
        self.status = status
        reasons = "; ".join(status.stale_reasons) if status.stale_reasons else "full-history cache is stale"
        super().__init__(reasons)


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
        "three_pack_hybrid_core",
        {
            "candidate": 0.86,
            "structure": 0.14,
            "pair_front": 0.88,
            "pair_back": 0.12,
            "multi_cover_pair": 0.88,
            "multi_cover_novelty": 0.12,
            "single_hit_pair": 0.97,
            "single_hit_novelty": 0.03,
            "overlap_front": 0.010,
            "overlap_back": 0.16,
            "same_back_pair_penalty": 1.32,
            "back_usage_penalty": 0.06,
            "fresh_back_bonus": 0.28,
            "crowd_penalty": 0.07,
            "jackpot_front_core": 1.0,
            "front_jackpot_pattern": 0.20,
            "front_probe_slots": 1.0,
            "front_probe_anchor_bonus": 0.06,
            "front_probe_support_bonus": 0.025,
            "back_independent_coverage": 1.0,
            "back_jackpot_slots": 2.0,
            "back_pair_floor_bonus": 0.16,
            "back_pair_coverage_bonus": 0.34,
            "front_pool_boost": 3.0,
            "back_pool_boost": 1.0,
            "front_combo_limit_boost": 44.0,
            "back_combo_limit_boost": 3.0,
            "ticket_candidate_budget_boost": 240.0,
        },
    ),
    (
        "three_pack_low_tier_cover",
        {
            "candidate": 0.76,
            "structure": 0.24,
            "pair_front": 0.70,
            "pair_back": 0.30,
            "multi_cover_pair": 0.68,
            "multi_cover_novelty": 0.32,
            "single_hit_pair": 0.90,
            "single_hit_novelty": 0.10,
            "overlap_front": 0.09,
            "overlap_back": 0.34,
            "same_back_pair_penalty": 1.42,
            "back_usage_penalty": 0.18,
            "fresh_back_bonus": 0.40,
            "crowd_penalty": 0.12,
            "front_probe_slots": 1.0,
            "front_probe_anchor_bonus": 0.04,
            "front_probe_support_bonus": 0.018,
            "back_independent_coverage": 1.0,
            "back_jackpot_slots": 1.0,
            "back_pair_floor_bonus": 0.12,
            "back_pair_coverage_bonus": 0.42,
            "front_pool_boost": 2.0,
            "back_pool_boost": 1.0,
            "front_combo_limit_boost": 32.0,
            "back_combo_limit_boost": 4.0,
            "ticket_candidate_budget_boost": 180.0,
        },
    ),
    (
        "three_pack_hit_guarded",
        {
            "candidate": 0.72,
            "structure": 0.28,
            "pair_front": 0.68,
            "pair_back": 0.32,
            "multi_cover_pair": 0.64,
            "multi_cover_novelty": 0.36,
            "single_hit_pair": 0.90,
            "single_hit_novelty": 0.10,
            "overlap_front": 0.03,
            "overlap_back": 0.22,
            "same_back_pair_penalty": 1.05,
            "back_usage_penalty": 0.10,
            "fresh_back_bonus": 0.42,
            "crowd_penalty": 0.10,
            "front_anchor_repeat_mode": 2.0,
            "back_wheel_mode": 1.0,
            "front_pool_boost": 3.0,
            "back_pool_boost": 2.0,
            "front_combo_limit_boost": 36.0,
            "back_combo_limit_boost": 4.0,
            "ticket_candidate_budget_boost": 220.0,
            "floor_harvest_slots": 1.0,
            "back_pair_floor_bonus": 0.18,
            "back_pair_coverage_bonus": 0.42,
            "three_pack_role_mode": 1.0,
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
THREE_PACK_SCORE_PROFILE_NAMES = ("frequency_revert", "balanced", "recent_bias", "cold_bias")
THREE_PACK_FAST_SCORE_PROFILE_NAMES = ("frequency_revert", "balanced", "recent_bias")
THREE_PACK_COMBO_PROFILE_NAMES = (
    "balanced_combo",
    "candidate_focus",
    "front_focus",
    "front_back_split",
    "wide_split_guarded",
    "core_back_wheel_guarded",
    "three_pack_hybrid_core",
    "three_pack_low_tier_cover",
    "three_pack_hit_guarded",
)
THREE_PACK_FAST_COMBO_PROFILE_NAMES = (
    "candidate_focus",
    "front_focus",
    "front_back_split",
    "three_pack_hybrid_core",
    "three_pack_low_tier_cover",
    "three_pack_hit_guarded",
)
THREE_PACK_FALLBACK_PROFILE = "balanced+balanced_combo"
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
    "three_pack_hybrid_core": "三组强核混合",
    "three_pack_low_tier_cover": "三组低奖覆盖",
    "wide_search": "宽域搜索",
    "wide_guarded": "宽域冲刺",
    "wide_floor_harvest": "宽域收割",
    "wide_front_jackpot": "宽域前区冲刺",
}


def _backtest_confidence_threshold(strategy_mode: str, scheme_count: int) -> float:
    if strategy_mode == SMART_BALANCE_MODE:
        strategy_mode = "multi_cover"
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


def _backtest_issue_result_json_row(item: BacktestIssueResult) -> dict:
    row = item.__dict__.copy()
    draw_date_value = row.get("draw_date")
    if isinstance(draw_date_value, date):
        row["draw_date"] = draw_date_value.isoformat()
    row["winning_scheme_labels"] = list(row.get("winning_scheme_labels") or [])
    row["prize_level_hits"] = dict(row.get("prize_level_hits") or {})
    row["prize_level_amounts"] = dict(row.get("prize_level_amounts") or {})
    return row


def _json_compatible_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_compatible_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_compatible_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_compatible_value(item) for key, item in value.items()}
    raw = getattr(value, "__dict__", None)
    if isinstance(raw, dict):
        return {key: _json_compatible_value(item) for key, item in raw.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value


def _backtest_response_json_payload(response: BacktestResponse, *, exclude: set[str]) -> dict:
    return {
        key: _json_compatible_value(value)
        for key, value in response.__dict__.items()
        if key not in exclude
    }


def _flat_model_json_rows(items: list[object]) -> list[dict]:
    return [_json_compatible_value(item) for item in items]


def _candidate_breakdown_json_rows(items: list[object]) -> list[dict]:
    rows: list[dict] = []
    for item in items:
        rows.append(
            {
                "number": int(getattr(item, "number")),
                "score": float(getattr(item, "score")),
                "tail": int(getattr(item, "tail")),
                "tail_weight": float(getattr(item, "tail_weight")),
                "omission": int(getattr(item, "omission")),
                "frequency": int(getattr(item, "frequency")),
                "recent_hits": int(getattr(item, "recent_hits")),
                "selected": bool(getattr(item, "selected")),
            }
        )
    return rows


def _performance_signal_totals(issue_results: list[BacktestIssueResult | dict]) -> dict[str, float]:
    totals = _empty_performance_signal_totals()
    for raw_item in issue_results:
        if isinstance(raw_item, BacktestIssueResult):
            totals["top3_hit_issues"] += 1.0 if raw_item.top3_hit else 0.0
            totals["top4_hit_issues"] += 1.0 if raw_item.top4_hit else 0.0
            totals["front_4plus_hit_issues"] += 1.0 if raw_item.front_4plus_hit else 0.0
            totals["front_5_hit_issues"] += 1.0 if raw_item.front_5_hit else 0.0
            totals["five_plus_zero_hit_issues"] += 1.0 if raw_item.five_plus_zero_hit else 0.0
            totals["five_plus_one_hit_issues"] += 1.0 if raw_item.five_plus_one_hit else 0.0
            totals["five_plus_two_hit_issues"] += 1.0 if raw_item.five_plus_two_hit else 0.0
            totals["four_plus_two_hit_issues"] += 1.0 if raw_item.four_plus_two_hit else 0.0
            totals["back_2plus_hit_issues"] += 1.0 if raw_item.back_2plus_hit else 0.0
            totals["front_best_match_total"] += float(raw_item.front_best_match_count or 0.0)
            totals["back_best_match_total"] += float(raw_item.back_best_match_count or 0.0)
            totals["issue_power_total"] += float(raw_item.issue_power_score or 0.0)
            prize_level_hits = raw_item.prize_level_hits or {}
        else:
            item = raw_item
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


def _copy_evaluation_summary(summary: dict[str, object]) -> dict[str, object]:
    return {
        "won_count": int(summary.get("won_count") or 0),
        "winning_scheme_labels": list(summary.get("winning_scheme_labels") or []),
        "best_prize_level": summary.get("best_prize_level"),
        "best_prize_amount": summary.get("best_prize_amount"),
        "total_prize_amount": float(summary.get("total_prize_amount") or 0.0),
        "prize_level_hits": dict(summary.get("prize_level_hits") or {}),
        "prize_level_amounts": dict(summary.get("prize_level_amounts") or {}),
    }


def _build_scheme_prefix_metrics(schemes: list, evaluations: list[dict]) -> list[dict]:
    prefix_metrics = [
        {
            "evaluation_summary": _summarize_scheme_evaluations([]),
            "quality_signals": _issue_quality_signals_from_evaluations([]),
            "coverage_metrics": _scheme_coverage_metrics([]),
        }
    ]
    for count in range(1, len(schemes) + 1):
        prefix_metrics.append(
            {
                "evaluation_summary": _summarize_scheme_evaluations(evaluations[:count]),
                "quality_signals": _issue_quality_signals_from_evaluations(evaluations[:count]),
                "coverage_metrics": _scheme_coverage_metrics(schemes[:count]),
            }
        )
    return prefix_metrics


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
    if count_policy in {"live_priority_value_ladder", "live_priority_zone_ladder"}:
        effective_margin = issue_confidence - threshold
        front_gap = (front_confidence - front_gate) if front_confidence is not None and front_gate is not None else 0.0
        back_gap = (back_confidence - back_gate) if back_confidence is not None and back_gate is not None else 0.0
        zone_penalty = max(0.0, -front_gap) * 0.95 + max(0.0, -back_gap) * 0.85
        zone_bonus = max(0.0, front_gap) * 0.25 + max(0.0, back_gap) * 0.20
        live_margin = effective_margin + zone_bonus - zone_penalty
        if live_margin < LIVE_PRIORITY_OBSERVE_MARGIN:
            return 0
        if live_margin < LIVE_PRIORITY_GUARDED_MARGIN:
            return 1
        if strategy_mode == "single_hit":
            if live_margin >= LIVE_PRIORITY_PRESS_MARGIN:
                return min(max_scheme_count, 2)
            return 1
        if live_margin >= LIVE_PRIORITY_PRESS_MARGIN:
            return min(max_scheme_count, 3)
        return min(max_scheme_count, 2)
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
    prepared_targets: list[tuple[object, list, PrecomputedHistoryFeatures]] = []
    for target in target_draws:
        history_item = history_context_cache.get(target.issue)
        if not history_item:
            continue
        prior_history_desc, history_context = history_item
        if history_context.history_size < BACKTEST_MIN_HISTORY_SIZE:
            continue
        prepared_targets.append((target, prior_history_desc, history_context))

    def evaluate_calibration_target(target, prior_history_desc: list, history_context: PrecomputedHistoryFeatures) -> dict:
        seed_timestamp = _historical_seed_timestamp(target.draw_date)
        raw = _evaluate_backtest_issue(
            0,
            target=target,
            prior_history_desc=prior_history_desc,
            history_context=history_context,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ticket_mode="basic",
            backtest_ai_config=ai_config,
            score_weights=score_weights,
            combo_weights=combo_weights,
            tuning_profile=None,
            include_baselines=False,
            search_profile="full",
        )
        evaluations = raw["scheme_evaluations"]
        full_hit = any(item.get("status") == "won" for item in evaluations)
        label_hits = {
            str(evaluation.get("label")): 1 if evaluation.get("status") == "won" else 0
            for evaluation in evaluations
            if evaluation.get("label")
        }
        return {
            "raw_confidence": float(raw.get("issue_confidence") or 0.0),
            "hit": 1 if full_hit else 0,
            "raw_front_confidence": float(raw.get("front_confidence") or 0.0),
            "front_hit": 1 if any(int(item.get("front_match_count") or 0) >= 3 for item in evaluations) else 0,
            "raw_back_confidence": float(raw.get("back_confidence") or 0.0),
            "back_hit": 1 if any(int(item.get("back_match_count") or 0) >= 1 for item in evaluations) else 0,
            "issue_mod_7": int(target.issue) % 7,
            "label_hits": label_hits,
        }

    calibration_history: list[dict] = []
    worker_count = _backtest_parallel_workers(len(prepared_targets), ai_replay_mode="local_only")
    if worker_count <= 1:
        for target, prior_history_desc, history_context in prepared_targets:
            calibration_history.append(evaluate_calibration_target(target, prior_history_desc, history_context))
    else:
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="live-calibration") as executor:
            future_map = [
                executor.submit(evaluate_calibration_target, target, prior_history_desc, history_context)
                for target, prior_history_desc, history_context in prepared_targets
            ]
            for future in as_completed(future_map):
                calibration_history.append(future.result())
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
    recent_issues = len(history_asc)
    requested_strategy_mode = strategy_mode
    smart_live_profile: SmartBalanceLiveProfile | None = None
    mode_live_profile: SmartBalanceLiveProfile | None = None
    with ThreadPoolExecutor(max_workers=LIVE_DIVINATION_PARALLEL_MAX_WORKERS, thread_name_prefix="live-divination-prep") as executor:
        cache_future = executor.submit(assert_full_history_cache_valid, scheme_count, "basic")
        history_context_future = executor.submit(build_history_feature_context, history_desc)
        if requested_strategy_mode == SMART_BALANCE_MODE:
            smart_profile_future = executor.submit(
                _select_live_smart_balance_profile,
                history_asc,
                scheme_count=scheme_count,
                ticket_mode="basic",
            )
            mode_profile_future = None
        else:
            smart_profile_future = None
            mode_profile_future = executor.submit(
                _resolve_live_mode_profile_and_weights,
                history_asc,
                requested_strategy_mode=requested_strategy_mode,
                scheme_count=scheme_count,
            )
    if requested_strategy_mode == SMART_BALANCE_MODE:
        cache_future.result()
        smart_live_profile = smart_profile_future.result() if smart_profile_future is not None else _select_live_smart_balance_profile(
            history_asc,
            scheme_count=scheme_count,
            ticket_mode="basic",
        )
        effective_strategy_mode = smart_live_profile.strategy_mode
        score_weights = smart_live_profile.score_weights
        combo_weights = smart_live_profile.combo_weights
        tuning_profile = f"智能平衡 / {smart_live_profile.display_name}"
    else:
        cache_future.result()
        if mode_profile_future is not None:
            (
                mode_live_profile,
                effective_strategy_mode,
                score_weights,
                combo_weights,
                tuning_profile,
            ) = mode_profile_future.result()
        else:
            effective_strategy_mode = strategy_mode
            mode_live_profile = _select_full_history_profile_for_mode(
                history_asc,
                effective_strategy_mode,
                scheme_count=scheme_count,
                ticket_mode="basic",
            )
            if mode_live_profile:
                score_weights = mode_live_profile.score_weights
                combo_weights = mode_live_profile.combo_weights
                tuning_profile = f"Full History / {mode_live_profile.display_name}"
            else:
                score_weights = DEFAULT_SCORE_WEIGHTS.copy()
                combo_weights = DEFAULT_COMBO_WEIGHTS.copy()
                tuning_profile = "Full History / Default Weights"
    history_context = history_context_future.result()
    use_ai = _external_ai_ready(ai_config)
    calibration_future = None
    calibration_executor: ThreadPoolExecutor | None = None
    if not smart_live_profile and mode_live_profile:
        calibration_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-calibration-prefetch")
        calibration_future = calibration_executor.submit(
            _full_history_report_calibration,
            history_asc,
            mode_live_profile.profile_name,
            scheme_count=scheme_count,
            ticket_mode="basic",
        )
    divination = generate_divination(
        history_desc,
        issue=issue,
        timestamp=timestamp,
        scheme_count=scheme_count,
        strategy_mode=effective_strategy_mode,
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
        strategy_mode=effective_strategy_mode,
        ai_config=None,
        score_weights=score_weights,
        combo_weights=combo_weights,
        history_context=history_context,
        metadata=runtime_metadata,
    )
    try:
        calibration_history = calibration_future.result() if calibration_future is not None else []
    finally:
        if calibration_executor is not None:
            calibration_executor.shutdown(wait=False)
    if not smart_live_profile and not mode_live_profile and len(calibration_history) < 30:
        calibration_history = _get_live_calibration_history(
            history_asc,
            sample_issues=recent_issues,
            scheme_count=scheme_count,
            strategy_mode=effective_strategy_mode,
            ai_config=None,
            score_weights=score_weights,
            combo_weights=combo_weights,
        )
    dynamic_threshold = _dynamic_confidence_threshold(
        strategy_mode=effective_strategy_mode,
        scheme_count=scheme_count,
        front_candidates=divination.front_candidates,
        back_candidates=divination.back_candidates,
    )
    if smart_live_profile:
        count_policy = f"smart_balance_{SMART_BALANCE_WINDOW}_{SMART_BALANCE_GUARD_WINDOW}"
    elif effective_strategy_mode == "single_hit":
        count_policy = "live_priority_zone_ladder"
    else:
        count_policy = "live_priority_value_ladder"
    divination, chosen_scheme_count = _apply_runtime_decision(
        divination=divination,
        tuning_profile=tuning_profile,
        strategy_mode=effective_strategy_mode,
        scheme_count=scheme_count,
        calibration_history=calibration_history,
        count_policy=count_policy,
        dynamic_threshold=dynamic_threshold,
        issue=live_issue,
        deep_search_triggered=bool(runtime_metadata.get("deep_search_triggered", False)),
        deep_search_reason=runtime_metadata.get("deep_search_reason"),
        min_visible_schemes=scheme_count,
    )
    if smart_live_profile:
        divination.strategy_mode = SMART_BALANCE_MODE  # type: ignore[assignment]
        divination.count_policy = count_policy
        divination.decision_reason = (
            f"{smart_live_profile.selection_reason} {divination.decision_reason or ''}"
        ).strip()
        divination.ai_analysis.engine = f"{divination.ai_analysis.engine} / Smart Balance"
        divination.ai_analysis.key_factors = [
            f"Smart balance profile: {smart_live_profile.display_name}.",
            *divination.ai_analysis.key_factors[:4],
        ]
        if divination.should_observe:
            divination.ai_analysis.final_advice = (
                f"Smart balance selected {smart_live_profile.display_name}; "
                f"the live gate suggests observing this round. {divination.ai_analysis.final_advice}"
            )
        else:
            divination.ai_analysis.final_advice = (
                f"Smart balance selected {smart_live_profile.display_name}; "
                f"kept {len(divination.final_schemes)} schemes after the live filter. "
                f"{divination.ai_analysis.final_advice}"
            )
    elif mode_live_profile:
        divination.decision_reason = (
            f"{mode_live_profile.selection_reason} {divination.decision_reason or ''}"
        ).strip()
        divination.ai_analysis.key_factors = [
            f"Full-history profile: {mode_live_profile.display_name}.",
            *divination.ai_analysis.key_factors[:4],
        ]
        if divination.should_observe:
            divination.ai_analysis.final_advice = (
                f"Full-history replay selected {mode_live_profile.display_name}; "
                f"the current live filter suggests observing this round. "
                f"{divination.ai_analysis.final_advice}"
            )
        else:
            divination.ai_analysis.final_advice = (
                f"Full-history replay selected {mode_live_profile.display_name}; "
                f"kept {len(divination.final_schemes)} schemes after the live filter. "
                f"{divination.ai_analysis.final_advice}"
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
            issue_results.append(
                {
                    "issue": trial["issue"],
                    "draw_date": trial["draw_date"],
                    "scheme_count": 0,
                    "tuning_profile": trial.get("tuning_profile"),
                    "issue_confidence": trial["issue_confidence"],
                    "calibrated_confidence": confidence,
                    "applied_threshold": threshold,
                    "should_observe": True,
                    "front_confidence": trial.get("front_confidence"),
                    "front_calibrated_confidence": trial.get("front_calibrated_confidence"),
                    "front_gate": trial.get("front_gate"),
                    "back_confidence": trial.get("back_confidence"),
                    "back_calibrated_confidence": trial.get("back_calibrated_confidence"),
                    "back_gate": trial.get("back_gate"),
                    "count_policy": count_policy,
                    "decision_tier": "observe",
                    "deep_search_triggered": trial.get("deep_search_triggered", False),
                    "deep_search_reason": trial.get("deep_search_reason"),
                    "decision_reason": "Threshold policy skipped this issue; kept in denominator with zero tickets.",
                    "won_count": 0,
                    "best_prize_level": None,
                    "best_prize_amount": None,
                    "total_prize_amount": 0.0,
                    "winning_scheme_labels": [],
                    "prize_level_hits": {},
                    "prize_level_amounts": {},
                    **_issue_quality_signals_from_evaluations([]),
                    "ticket_mode": ticket_mode,
                    "cost": 0.0,
                    "front_pairwise_overlap_avg": 0.0,
                    "back_pairwise_overlap_avg": 0.0,
                    "back_pair_reuse_rate": 0.0,
                    "fresh_back_number_rate": 0.0,
                }
            )
            continue
        selected_issue_count += 1
        selected_scheme_total += chosen_count
        applied_threshold_total += threshold
        trial_schemes = trial["schemes"]
        trial_evaluations = trial["evaluations"]
        cached_prefix_metrics = trial.get("prefix_metrics")
        can_use_cached_prefix_metrics = (
            isinstance(cached_prefix_metrics, list)
            and 0 <= chosen_count < len(cached_prefix_metrics)
            and not (count_policy == "must_issue_value_ladder" and strategy_mode != "single_hit" and chosen_count == 1)
        )
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
        if can_use_cached_prefix_metrics:
            cached_metrics = cached_prefix_metrics[chosen_count]
            evaluation_summary = _copy_evaluation_summary(cached_metrics["evaluation_summary"])
            quality_signals = dict(cached_metrics["quality_signals"])
            coverage_metrics = cached_metrics["coverage_metrics"]
        else:
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


def _issue_results_stats_for_threshold_resolver(
    issue_trials: list[dict],
    *,
    strategy_mode: str,
    max_scheme_count: int,
    ticket_mode: str,
    threshold_resolver,
    count_policy: str = "baseline",
) -> tuple[list[dict], BacktestResponse, int, float, float]:
    issue_results, skipped_issues, avg_scheme_count, avg_applied_threshold = _build_issue_results_for_threshold_resolver(
        issue_trials,
        strategy_mode=strategy_mode,
        max_scheme_count=max_scheme_count,
        ticket_mode=ticket_mode,
        threshold_resolver=threshold_resolver,
        count_policy=count_policy,
    )
    stats = build_backtest_stats(issue_results)  # type: ignore[arg-type]
    return issue_results, stats, skipped_issues, avg_scheme_count, avg_applied_threshold


def _threshold_scan_results(
    issue_trials: list[dict],
    *,
    strategy_mode: str,
    max_scheme_count: int,
    ticket_mode: str,
) -> list[BacktestThresholdScanItem]:
    rows: list[BacktestThresholdScanItem] = []
    for threshold in THRESHOLD_SCAN_VALUES:
        issue_results, stats, skipped_issues, avg_scheme_count, _ = _issue_results_stats_for_threshold_resolver(
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
                issue_results, stats, skipped_issues, avg_scheme_count, avg_applied_threshold = _issue_results_stats_for_threshold_resolver(
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
        issue_results, stats, skipped_issues, avg_scheme_count, avg_applied_threshold = _issue_results_stats_for_threshold_resolver(
            issue_trials,
            strategy_mode=strategy_mode,
            max_scheme_count=max_scheme_count,
            ticket_mode=ticket_mode,
            threshold_resolver=lambda confidence, t=threshold: t,
            count_policy=count_policy,
        )
        selection_score, _, score_range, _, _, _ = _selection_metrics_from_issue_results(
            issue_results,
            strategy_mode=strategy_mode,
            scheme_count=max(1, max_scheme_count),
        )
        recent_issue_dicts = issue_results[-LIVE_PRIORITY_MID_WINDOW:] if len(issue_results) > LIVE_PRIORITY_MID_WINDOW else issue_results
        recent_stats = build_backtest_stats(recent_issue_dicts)  # type: ignore[arg-type]
        recent_miss_streak = _max_miss_streak(recent_issue_dicts)
        rank = (
            selection_score,
            recent_stats.issue_hit_rate,
            recent_stats.overall_win_rate,
            stats.issue_hit_rate,
            -recent_miss_streak,
            -(score_range or 0.0),
            -abs(avg_scheme_count - 1.2),
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


def _smart_balance_mode_label(strategy_mode: str) -> str:
    return "Single Hit" if strategy_mode == "single_hit" else "Multi Cover"


def _smart_balance_candidate_profiles() -> list[tuple[str, str, str, dict[str, float], dict[str, float]]]:
    lookup = _predefined_tuning_profile_lookup()
    profiles: list[tuple[str, str, str, dict[str, float], dict[str, float]]] = []
    for strategy_mode, profile_name in SMART_BALANCE_PROFILE_CANDIDATES:
        profile = lookup.get(profile_name)
        if profile is None:
            continue
        display_name, score_weights, combo_weights = profile
        candidate_name = f"{strategy_mode}:{profile_name}"
        profiles.append(
            (
                candidate_name,
                strategy_mode,
                f"{_smart_balance_mode_label(strategy_mode)} / {display_name}",
                score_weights.copy(),
                combo_weights.copy(),
            )
        )
    return profiles


def _active_live_smart_balance_candidate_profiles(
    candidate_results: dict[str, dict[str, dict]],
) -> list[tuple[str, str, str, dict[str, float], dict[str, float]]]:
    candidate_profiles = _smart_balance_candidate_profiles()
    active_profiles = [profile for profile in candidate_profiles if candidate_results.get(profile[0])]
    return active_profiles or candidate_profiles


def _smart_balance_profile_from_candidate_name(candidate_name: str | None, selection_reason: str) -> SmartBalanceLiveProfile:
    candidate_profiles = _smart_balance_candidate_profiles()
    if not candidate_profiles:
        raise ValueError("智能平衡候选档位为空。")
    profile_lookup = {profile_name: profile for profile_name, *profile in candidate_profiles}
    resolved_name = candidate_name if candidate_name in profile_lookup else candidate_profiles[0][0]
    candidate_strategy_mode, display_name, score_weights, combo_weights = profile_lookup[resolved_name]
    return SmartBalanceLiveProfile(
        profile_name=resolved_name,
        strategy_mode=candidate_strategy_mode,
        display_name=display_name,
        score_weights=score_weights.copy(),
        combo_weights=combo_weights.copy(),
        selection_reason=selection_reason,
    )


def _recent_weighted_issue_score(
    issues: list[dict],
    *,
    score_fn: Callable[[dict], float],
    recent_window: int,
    recent_weight: float,
    mid_window: int | None = None,
    mid_weight: float = 1.0,
) -> float:
    if not issues:
        return 0.0
    weighted_total = 0.0
    weight_total = 0.0
    total = len(issues)
    mid_boundary = max(0, total - max(0, mid_window or 0)) if mid_window else total
    recent_boundary = max(0, total - max(0, recent_window))
    for index, item in enumerate(issues):
        weight = 1.0
        if index >= recent_boundary:
            weight = recent_weight
        elif mid_window and index >= mid_boundary:
            weight = mid_weight
        weighted_total += score_fn(item) * weight
        weight_total += weight
    return weighted_total / max(1.0, weight_total)


def _live_priority_issue_score(issue_result: dict) -> float:
    base = _smart_balance_issue_score(issue_result)
    if int(issue_result.get("won_count") or 0) > 0:
        return round(base + LIVE_PRIORITY_SCORE_BONUS, 4)
    if bool(issue_result.get("top4_hit")) or bool(issue_result.get("five_plus_one_hit")):
        return round(base + LIVE_PRIORITY_SCORE_BONUS * 0.6, 4)
    return base


def _live_priority_attack_score(issue_result: dict) -> float:
    base = _smart_balance_attack_issue_score(issue_result)
    if bool(issue_result.get("top4_hit")) or bool(issue_result.get("five_plus_one_hit")):
        return round(base + LIVE_PRIORITY_SCORE_BONUS, 4)
    return base


def _live_priority_profile_adjustment(issue_results: list[dict]) -> tuple[float, float, int]:
    if not issue_results:
        return 0.0, 0.0, 0
    total_issues = len(issue_results)
    hit_issues = sum(1 for item in issue_results if int(item.get("won_count") or 0) > 0)
    total_generated_schemes = sum(max(0, int(item.get("scheme_count") or 0)) for item in issue_results)
    won_schemes = sum(max(0, int(item.get("won_count") or 0)) for item in issue_results)
    issue_hit_rate = hit_issues / total_issues if total_issues else 0.0
    overall_win_rate = won_schemes / total_generated_schemes if total_generated_schemes else issue_hit_rate
    miss_streak = _max_miss_streak(issue_results)
    bonus = issue_hit_rate * LIVE_PRIORITY_HIT_RATE_WEIGHT + overall_win_rate * LIVE_PRIORITY_WIN_RATE_WEIGHT
    penalty = max(0, miss_streak - LIVE_PRIORITY_MISS_STREAK_SOFT_CAP) * LIVE_PRIORITY_MISS_STREAK_PENALTY
    return round(bonus, 4), round(penalty, 4), miss_streak


def _history_lag_after_issue(history_asc: list, issue: str) -> int | None:
    if not issue:
        return None
    for index, draw in enumerate(history_asc):
        if str(draw.issue) == issue:
            return max(0, len(history_asc) - index - 1)
    return None


def _smart_balance_score_text(value: object) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "n/a"


def _normalize_ticket_mode(ticket_mode: str) -> str:
    return "additional" if ticket_mode == "additional" else "basic"


def _cache_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_cache_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _expected_full_history_cache_issue_count(history_asc: list) -> int:
    return _expected_full_history_cache_issue_count_for_total_draws(len(history_asc))


def _expected_full_history_cache_issue_count_for_total_draws(total_draws: int) -> int:
    return max(0, total_draws - BACKTEST_MIN_HISTORY_SIZE)


def _full_history_cache_key(scheme_count: int, ticket_mode: str) -> str:
    safe_ticket_mode = _normalize_ticket_mode(ticket_mode)
    return f"{scheme_count}_{safe_ticket_mode}"


def _full_history_cache_manifest_path(scheme_count: int, ticket_mode: str) -> str:
    return _smart_balance_report_file_path(
        f"{FULL_HISTORY_CACHE_MANIFEST_PREFIX}_{_full_history_cache_key(scheme_count, ticket_mode)}.manifest.json"
    )


def _full_history_cache_report_name(scheme_count: int, ticket_mode: str, profile: str) -> str:
    return f"{FULL_HISTORY_CACHE_MANIFEST_PREFIX}_{_full_history_cache_key(scheme_count, ticket_mode)}_{profile}.json"


def _full_history_cache_profile_specs(scheme_count: int, ticket_mode: str) -> dict[str, dict[str, object]]:
    specs = {
        "default_multi": {
            "candidate_name": "multi_cover:balanced+balanced_combo",
            "strategy_mode": "multi_cover",
            "tuning_profile_override": "balanced+balanced_combo",
            "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "default_multi"),
        },
        "lowtier_multi": {
            "candidate_name": "multi_cover:frequency_revert+three_pack_low_tier_cover",
            "strategy_mode": "multi_cover",
            "tuning_profile_override": "frequency_revert+three_pack_low_tier_cover",
            "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "lowtier_multi"),
        },
        "candidate_multi": {
            "candidate_name": "multi_cover:frequency_revert+candidate_focus",
            "strategy_mode": "multi_cover",
            "tuning_profile_override": "frequency_revert+candidate_focus",
            "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "candidate_multi"),
        },
        "hybrid_guarded_multi": {
            "candidate_name": "multi_cover:frequency_revert+candidate_focus_jackpot_floor_guarded",
            "strategy_mode": "multi_cover",
            "tuning_profile_override": "frequency_revert+candidate_focus_jackpot_floor_guarded",
            "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "hybrid_guarded_multi"),
        },
        "front_back_multi": {
            "candidate_name": "multi_cover:frequency_revert+front_back_split",
            "strategy_mode": "multi_cover",
            "tuning_profile_override": "frequency_revert+front_back_split",
            "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "front_back_multi"),
        },
        "single_hit_default": {
            "candidate_name": "single_hit:balanced+balanced_combo",
            "strategy_mode": "single_hit",
            "tuning_profile_override": "balanced+balanced_combo",
            "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "single_hit_default"),
        },
    }
    if scheme_count <= FULL_HISTORY_CACHE_EXTENDED_PROFILE_MAX_SCHEME_COUNT:
        specs.update(
            {
                "recent_lowtier_multi": {
                    "candidate_name": "multi_cover:recent_bias+three_pack_low_tier_cover",
                    "strategy_mode": "multi_cover",
                    "tuning_profile_override": "recent_bias+three_pack_low_tier_cover",
                    "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "recent_lowtier_multi"),
                },
                "recent_hit_guarded_multi": {
                    "candidate_name": "multi_cover:recent_bias+three_pack_hit_guarded",
                    "strategy_mode": "multi_cover",
                    "tuning_profile_override": "recent_bias+three_pack_hit_guarded",
                    "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "recent_hit_guarded_multi"),
                },
                "front_focus_multi": {
                    "candidate_name": "multi_cover:balanced+front_focus",
                    "strategy_mode": "multi_cover",
                    "tuning_profile_override": "balanced+front_focus",
                    "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "front_focus_multi"),
                },
                "front_focus_guarded_multi": {
                    "candidate_name": "multi_cover:balanced+front_focus_floor_guarded",
                    "strategy_mode": "multi_cover",
                    "tuning_profile_override": "balanced+front_focus_floor_guarded",
                    "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "front_focus_guarded_multi"),
                },
                "recent_front_focus_guarded_multi": {
                    "candidate_name": "multi_cover:recent_bias+front_focus_floor_guarded",
                    "strategy_mode": "multi_cover",
                    "tuning_profile_override": "recent_bias+front_focus_floor_guarded",
                    "file_name": _full_history_cache_report_name(scheme_count, ticket_mode, "recent_front_focus_guarded_multi"),
                },
            }
        )
    return specs


def _serialize_full_history_cache_job(job: _FullHistoryCacheJobState) -> FullHistoryCacheRebuildJob:
    return FullHistoryCacheRebuildJob(
        job_id=job.job_id,
        status=job.status,  # type: ignore[arg-type]
        progress=job.progress,
        message=job.message,
        scheme_count=job.scheme_count,
        ticket_mode=job.ticket_mode,  # type: ignore[arg-type]
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
    )


def _clone_full_history_cache_status(status: FullHistoryCacheStatus) -> FullHistoryCacheStatus:
    return FullHistoryCacheStatus(
        algorithm_version=status.algorithm_version,
        latest_issue=status.latest_issue,
        total_draws=status.total_draws,
        expected_issue_count=status.expected_issue_count,
        scheme_count=status.scheme_count,
        ticket_mode=status.ticket_mode,
        valid=status.valid,
        stale_reasons=list(status.stale_reasons),
        generated_at=status.generated_at,
        invalidated_at=status.invalidated_at,
        profiles=[item.model_copy() for item in status.profiles],
        active_job=status.active_job.model_copy() if status.active_job is not None else None,
    )


def _active_full_history_cache_job(scheme_count: int, ticket_mode: str) -> FullHistoryCacheRebuildJob | None:
    with _full_history_cache_lock:
        for job in sorted(_full_history_cache_jobs.values(), key=lambda item: item.created_at, reverse=True):
            if job.scheme_count == scheme_count and job.ticket_mode == ticket_mode and job.status in {"queued", "running"}:
                return _serialize_full_history_cache_job(job)
    return None


def _load_full_history_cache_manifest(scheme_count: int, ticket_mode: str) -> dict | None:
    path = _full_history_cache_manifest_path(scheme_count, ticket_mode)
    manifest, _exists = _load_json_dict_file_cached(path, warning_label="full-history cache manifest")
    return manifest


def _load_json_report(file_name: str) -> dict | None:
    path = _smart_balance_report_file_path(file_name)
    payload, _exists = _load_json_dict_file_cached(path, warning_label=f"report {file_name}")
    if not isinstance(payload, dict):
        return payload
    issues = payload.get("issues")
    if isinstance(issues, list):
        return payload
    sidecar_issues = _load_full_history_cache_issue_rows(file_name)
    if not isinstance(sidecar_issues, list):
        return payload
    return {
        **payload,
        "issues": sidecar_issues,
    }


def _json_dict_file_signature(path: str, *, warning_label: str) -> tuple[JsonFileSignature | None, bool]:
    try:
        stat_result = os.stat(path)
    except FileNotFoundError:
        return None, False
    except OSError as exc:  # noqa: BLE001
        logger.warning("Failed to stat %s: %s", warning_label, exc)
        return None, False
    return (stat_result.st_mtime, stat_result.st_size), True


def _load_json_dict_file_cached(
    path: str,
    *,
    warning_label: str,
    signature: JsonFileSignature | None = None,
) -> tuple[dict | None, bool]:
    effective_signature = signature
    exists = True
    if effective_signature is None:
        effective_signature, exists = _json_dict_file_signature(path, warning_label=warning_label)
        if effective_signature is None:
            return None, exists
    with _json_dict_file_cache_lock:
        cached = _json_dict_file_cache.get(path)
        if cached is not None and cached[0] == effective_signature:
            return cached[1], True

    payload: dict | None
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            raw_payload = json.load(file_obj)
        payload = raw_payload if isinstance(raw_payload, dict) else None
    except FileNotFoundError:
        return None, False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read %s: %s", warning_label, exc)
        payload = None

    with _json_dict_file_cache_lock:
        _json_dict_file_cache[path] = (effective_signature, payload)
    return payload, True


def _clear_json_dict_file_cache(path: str | None = None) -> None:
    with _json_dict_file_cache_lock:
        if path is None:
            _json_dict_file_cache.clear()
        else:
            _json_dict_file_cache.pop(path, None)


def _write_json_file_atomic(path: str, payload: dict, *, compact: bool = False) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.{uuid4().hex}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file_obj:
        json.dump(
            payload,
            file_obj,
            ensure_ascii=False,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
            default=str,
        )
        file_obj.write("\n")
    os.replace(temp_path, path)
    _clear_json_dict_file_cache(path)


def _write_json_report_atomic(
    file_name: str,
    payload: dict,
    *,
    clear_caches: bool = True,
) -> None:
    path = _smart_balance_report_file_path(file_name)
    compact_cache_file = file_name.startswith(f"{FULL_HISTORY_CACHE_MANIFEST_PREFIX}_")
    if _should_split_full_history_cache_issue_payload(file_name, payload):
        issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
        summary_payload = dict(payload)
        summary_payload.pop("issues", None)
        _write_full_history_cache_issue_sidecar(
            file_name,
            [item for item in issues if isinstance(item, dict)],
            metadata=payload.get("full_history_cache") if isinstance(payload.get("full_history_cache"), dict) else None,
        )
        _write_json_file_atomic(path, summary_payload, compact=True)
    else:
        _write_json_file_atomic(path, payload, compact=compact_cache_file)
    if clear_caches:
        _clear_full_history_cache_status_cache()
        _clear_smart_balance_report_signature_cache()


def _clear_smart_balance_report_signature_cache(
    scheme_count: int | None = None,
    ticket_mode: str | None = None,
) -> None:
    with _smart_balance_report_cache_lock:
        if scheme_count is None or ticket_mode is None:
            _smart_balance_report_signature_cache.clear()
            return
        _smart_balance_report_signature_cache.pop((scheme_count, _normalize_ticket_mode(ticket_mode)), None)


def _trim_full_history_cache_jobs() -> None:
    if len(_full_history_cache_jobs) <= FULL_HISTORY_CACHE_MAX_JOBS:
        return
    removable = sorted(_full_history_cache_jobs.values(), key=lambda item: item.created_at)
    while removable and len(_full_history_cache_jobs) > FULL_HISTORY_CACHE_MAX_JOBS:
        item = removable.pop(0)
        if item.status in {"completed", "failed"}:
            _full_history_cache_jobs.pop(item.job_id, None)


def _update_full_history_cache_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    cache_key: str | None = None
    with _full_history_cache_lock:
        job = _full_history_cache_jobs.get(job_id)
        if not job:
            return
        cache_key = _full_history_cache_key(job.scheme_count, job.ticket_mode)
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = max(0.0, min(1.0, progress))
        if message is not None:
            job.message = message
        if error is not None:
            job.error = error
        if started_at is not None:
            job.started_at = started_at
        if finished_at is not None:
            job.finished_at = finished_at
    _clear_full_history_cache_status_cache(cache_key=cache_key)


def _report_profile_status(
    *,
    profile: str,
    mode: str,
    file_name: str | None,
    manifest_profile: dict[str, object] | None = None,
    latest_issue: str | None,
    total_draws: int,
    expected_issue_count: int,
    scheme_count: int,
    ticket_mode: str,
) -> FullHistoryCacheProfileStatus:
    if not file_name:
        return FullHistoryCacheProfileStatus(profile=profile, mode=mode, reason="manifest missing file name")
    path = _smart_balance_report_file_path(file_name)
    signature, exists = _json_dict_file_signature(path, warning_label=f"report {file_name}")
    if not exists:
        return FullHistoryCacheProfileStatus(profile=profile, mode=mode, file_name=file_name, reason="report file missing")
    if (
        isinstance(manifest_profile, dict)
        and manifest_profile.get("total_issues") is not None
        and manifest_profile.get("latest_issue") is not None
    ):
        issue_count = int(manifest_profile.get("total_issues") or 0)
        report_latest_issue = str(manifest_profile.get("latest_issue") or "") or None
        report_scheme_count = int(manifest_profile.get("scheme_count") or 0)
        report_ticket_mode = str(manifest_profile.get("ticket_mode") or "")
        requested_issues = int(manifest_profile.get("requested_issues") or 0)
        generated_at = str(manifest_profile.get("generated_at") or "") or None
        reason = None
        if str(manifest_profile.get("profile") or "") not in {"", profile}:
            reason = "profile metadata mismatch"
        elif issue_count <= 0:
            reason = "manifest summary missing issue count"
        elif issue_count > expected_issue_count:
            reason = f"issue count exceeds history: {issue_count}/{expected_issue_count}"
        elif report_latest_issue == latest_issue and issue_count != expected_issue_count:
            reason = f"issue count mismatch: {issue_count}/{expected_issue_count}"
        elif report_latest_issue != latest_issue:
            reason = f"latest draw not cached yet: {report_latest_issue}/{latest_issue}"
        elif requested_issues not in {0, total_draws, issue_count}:
            reason = f"requested issue mismatch: {requested_issues}/{total_draws}"
        elif report_scheme_count != scheme_count:
            reason = f"scheme count mismatch: {report_scheme_count}/{scheme_count}"
        elif report_ticket_mode != ticket_mode:
            reason = f"ticket mode mismatch: {report_ticket_mode}/{ticket_mode}"
        return FullHistoryCacheProfileStatus(
            profile=profile,
            mode=mode,
            file_name=file_name,
            exists=True,
            valid=reason is None,
            issue_count=issue_count,
            latest_issue=report_latest_issue,
            generated_at=generated_at,
            reason=reason,
        )
    report, _exists = _load_json_dict_file_cached(
        path,
        warning_label=f"report {file_name}",
        signature=signature,
    )
    if not report:
        return FullHistoryCacheProfileStatus(
            profile=profile,
            mode=mode,
            file_name=file_name,
            exists=True,
            reason="report file unreadable",
        )
    issues = report.get("issues") if isinstance(report, dict) else None
    issue_count = len(issues) if isinstance(issues, list) else 0
    report_latest_issue = str(issues[-1].get("issue")) if issue_count and isinstance(issues[-1], dict) else None
    report_scheme_count = int(report.get("scheme_count") or 0) if isinstance(report, dict) else 0
    report_ticket_mode = str(report.get("ticket_mode") or "") if isinstance(report, dict) else ""
    requested_issues = int(report.get("requested_issues") or 0) if isinstance(report, dict) else 0
    total_issues = int(report.get("total_issues") or 0) if isinstance(report, dict) else 0
    metadata = report.get("full_history_cache") if isinstance(report, dict) else None
    generated_at = metadata.get("generated_at") if isinstance(metadata, dict) else None
    reason = None
    if not isinstance(metadata, dict):
        reason = "cache metadata missing"
    elif str(metadata.get("profile") or "") != profile:
        reason = "profile metadata mismatch"
    elif int(metadata.get("scheme_count") or 0) != scheme_count:
        reason = f"metadata scheme count mismatch: {metadata.get('scheme_count')}/{scheme_count}"
    elif str(metadata.get("ticket_mode") or "") != ticket_mode:
        reason = f"metadata ticket mode mismatch: {metadata.get('ticket_mode')}/{ticket_mode}"
    elif total_issues != issue_count:
        reason = f"total issue mismatch: {total_issues}/{issue_count}"
    elif issue_count > expected_issue_count:
        reason = f"issue count exceeds history: {issue_count}/{expected_issue_count}"
    elif report_latest_issue == latest_issue and issue_count != expected_issue_count:
        reason = f"issue count mismatch: {issue_count}/{expected_issue_count}"
    elif report_latest_issue != latest_issue:
        reason = f"latest draw not cached yet: {report_latest_issue}/{latest_issue}"
    elif requested_issues not in {0, total_draws, issue_count, total_issues}:
        reason = f"requested issue mismatch: {requested_issues}/{total_draws}"
    elif report_scheme_count != scheme_count:
        reason = f"scheme count mismatch: {report_scheme_count}/{scheme_count}"
    elif report_ticket_mode != ticket_mode:
        reason = f"ticket mode mismatch: {report_ticket_mode}/{ticket_mode}"
    return FullHistoryCacheProfileStatus(
        profile=profile,
        mode=mode,
        file_name=file_name,
        exists=True,
        valid=reason is None,
        issue_count=issue_count,
        latest_issue=report_latest_issue,
        generated_at=generated_at,
        reason=reason,
    )


def _collect_full_history_profile_statuses(
    profile_args: list[dict[str, object]],
) -> list[FullHistoryCacheProfileStatus]:
    if not profile_args:
        return []
    if len(profile_args) == 1:
        return [_report_profile_status(**profile_args[0])]

    statuses: list[FullHistoryCacheProfileStatus | None] = [None] * len(profile_args)
    max_workers = min(FULL_HISTORY_CACHE_STATUS_MAX_WORKERS, len(profile_args))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fh-cache-status") as executor:
        future_map = {
            executor.submit(_report_profile_status, **args): index
            for index, args in enumerate(profile_args)
        }
        for future in as_completed(future_map):
            statuses[future_map[future]] = future.result()
    return [status for status in statuses if status is not None]


def _clear_full_history_cache_status_cache(
    *,
    scheme_count: int | None = None,
    ticket_mode: str | None = None,
    cache_key: str | None = None,
) -> None:
    with _full_history_status_cache_lock:
        if cache_key is not None:
            _full_history_status_cache.pop(cache_key, None)
            return
        if scheme_count is None or ticket_mode is None:
            _full_history_status_cache.clear()
            return
        _full_history_status_cache.pop(_full_history_cache_key(scheme_count, ticket_mode), None)


def get_full_history_cache_status(scheme_count: int = 3, ticket_mode: str = "basic") -> FullHistoryCacheStatus:
    ticket_mode = _normalize_ticket_mode(ticket_mode)
    cache_key = _full_history_cache_key(scheme_count, ticket_mode)
    with _full_history_status_cache_lock:
        cached = _full_history_status_cache.get(cache_key)
        if cached is not None and monotonic() - cached[0] <= FULL_HISTORY_CACHE_STATUS_TTL_SECONDS:
            return _clone_full_history_cache_status(cached[1])

    history_asc = get_all_history_asc()
    latest_issue = str(history_asc[-1].issue) if history_asc else None
    total_draws = len(history_asc)
    expected_issue_count = _expected_full_history_cache_issue_count_for_total_draws(total_draws)
    manifest = _load_full_history_cache_manifest(scheme_count, ticket_mode)
    specs = _full_history_cache_profile_specs(scheme_count, ticket_mode)
    active_job = _active_full_history_cache_job(scheme_count, ticket_mode)
    stale_reasons: list[str] = []
    generated_at: str | None = None
    profile_statuses: list[FullHistoryCacheProfileStatus] = []

    if not manifest:
        stale_reasons.append("full-history cache manifest is missing")
        profile_status_args: list[dict[str, object]] = []
        for profile, spec in specs.items():
            if active_job:
                profile_statuses.append(
                    FullHistoryCacheProfileStatus(
                        profile=profile,
                        mode=str(spec["strategy_mode"]),
                        file_name=str(spec["file_name"]),
                        reason="rebuild running",
                    )
                )
            else:
                profile_status_args.append(
                    {
                        "profile": profile,
                        "mode": str(spec["strategy_mode"]),
                        "file_name": str(spec["file_name"]),
                        "manifest_profile": None,
                        "latest_issue": latest_issue,
                        "total_draws": total_draws,
                        "expected_issue_count": expected_issue_count,
                        "scheme_count": scheme_count,
                        "ticket_mode": ticket_mode,
                    }
                )
        if profile_status_args:
            profile_statuses.extend(_collect_full_history_profile_statuses(profile_status_args))
    else:
        generated_at = str(manifest.get("generated_at") or "")
        source_snapshot_at = str(manifest.get("source_snapshot_at") or generated_at)
        if int(manifest.get("scheme_count") or 0) != scheme_count:
            stale_reasons.append("scheme count does not match cache")
        if str(manifest.get("ticket_mode") or "") != ticket_mode:
            stale_reasons.append("ticket mode does not match cache")
        profiles = manifest.get("profiles") if isinstance(manifest.get("profiles"), dict) else {}
        profile_status_args: list[dict[str, object]] = []
        for profile, spec in specs.items():
            manifest_profile = profiles.get(profile) if isinstance(profiles, dict) else None
            file_name = (
                str(manifest_profile.get("file_name"))
                if isinstance(manifest_profile, dict) and manifest_profile.get("file_name")
                else str(spec["file_name"])
            )
            profile_status_args.append(
                {
                    "profile": profile,
                    "mode": str(spec["strategy_mode"]),
                    "file_name": file_name,
                    "manifest_profile": manifest_profile if isinstance(manifest_profile, dict) else None,
                    "latest_issue": latest_issue,
                    "total_draws": total_draws,
                    "expected_issue_count": expected_issue_count,
                    "scheme_count": scheme_count,
                    "ticket_mode": ticket_mode,
                }
            )
        for profile_status in _collect_full_history_profile_statuses(profile_status_args):
            if not profile_status.valid:
                stale_reasons.append(f"{profile_status.profile} cache invalid: {profile_status.reason}")
            profile_statuses.append(profile_status)

    invalidated_at = get_meta("full_history_cache_invalidated_at")
    if invalidated_at and generated_at:
        invalidated_time = _parse_cache_datetime(invalidated_at)
        generated_time = _parse_cache_datetime(source_snapshot_at if manifest else generated_at)
        if not invalidated_time or not generated_time:
            stale_reasons.append("cache invalidation timestamp is invalid")
        elif invalidated_time > generated_time:
            stale_reasons.append("draw data changed after cache generation")
    elif invalidated_at and not generated_at:
        stale_reasons.append("draw data changed after cache generation")

    status = FullHistoryCacheStatus(
        algorithm_version=FULL_HISTORY_CACHE_ALGORITHM_VERSION,
        latest_issue=latest_issue,
        total_draws=total_draws,
        expected_issue_count=expected_issue_count,
        scheme_count=scheme_count,
        ticket_mode=ticket_mode,  # type: ignore[arg-type]
        valid=not stale_reasons and all(item.valid for item in profile_statuses),
        stale_reasons=list(dict.fromkeys(stale_reasons)),
        generated_at=generated_at or None,
        invalidated_at=invalidated_at,
        profiles=profile_statuses,
        active_job=active_job,
    )
    with _full_history_status_cache_lock:
        _full_history_status_cache[cache_key] = (monotonic(), status)
    return _clone_full_history_cache_status(status)


def assert_full_history_cache_valid(scheme_count: int, ticket_mode: str = "basic") -> FullHistoryCacheStatus:
    status = get_full_history_cache_status(scheme_count=scheme_count, ticket_mode=ticket_mode)
    if not status.valid:
        raise FullHistoryCacheStaleError(status)
    return status


def _clear_smart_balance_candidate_cache() -> None:
    global _smart_balance_report_cache_signature, _smart_balance_report_candidate_cache
    _smart_balance_report_cache_signature = None
    _smart_balance_report_candidate_cache = None
    _clear_smart_balance_report_signature_cache()
    _clear_json_dict_file_cache()
    _clear_full_history_cache_status_cache()


def _full_history_cache_manifest_profile_entries(
    specs: dict[str, dict[str, object]],
    report_metadata: dict[str, dict],
) -> dict[str, dict[str, object]]:
    profiles: dict[str, dict[str, object]] = {}
    for profile, spec in specs.items():
        metadata = report_metadata.get(profile, {})
        profiles[profile] = {
            "candidate_name": spec.get("candidate_name"),
            "strategy_mode": spec.get("strategy_mode"),
            "tuning_profile_override": spec.get("tuning_profile_override"),
            "file_name": spec.get("file_name"),
            "generated_at": metadata.get("generated_at"),
            "latest_issue": metadata.get("latest_issue"),
            "scheme_count": metadata.get("scheme_count"),
            "ticket_mode": metadata.get("ticket_mode"),
            "requested_issues": metadata.get("requested_issues"),
            "total_issues": metadata.get("total_issues"),
            "total_generated_schemes": metadata.get("total_generated_schemes"),
            "issue_hit_rate": metadata.get("issue_hit_rate"),
            "overall_win_rate": metadata.get("overall_win_rate"),
            "total_prize_amount": metadata.get("total_prize_amount"),
            "net_profit": metadata.get("net_profit"),
        }
    return profiles


def _incremental_full_history_cache_window(
    *,
    report: dict | None,
    history_asc: list,
    latest_issue: str | None,
    expected_issue_count: int,
    history_positions: dict[str, int] | None = None,
) -> tuple[list[dict], int]:
    if not isinstance(report, dict):
        return [], len(history_asc)
    raw_issues = report.get("issues")
    if not isinstance(raw_issues, list):
        return [], len(history_asc)
    cached_issues = raw_issues if all(isinstance(item, dict) for item in raw_issues) else [item for item in raw_issues if isinstance(item, dict)]
    if not cached_issues:
        return [], len(history_asc)

    cached_latest_issue = str(cached_issues[-1].get("issue") or "")
    effective_history_positions = (
        history_positions
        if history_positions is not None
        else {str(draw.issue): index for index, draw in enumerate(history_asc)}
    )
    cached_latest_index = effective_history_positions.get(cached_latest_issue)
    if cached_latest_index is None:
        return [], len(history_asc)

    cached_expected_issue_count = _expected_full_history_cache_issue_count_for_total_draws(cached_latest_index + 1)
    if len(cached_issues) != cached_expected_issue_count:
        return [], len(history_asc)

    missing_recent_issues = max(0, len(history_asc) - cached_latest_index - 1)
    if missing_recent_issues == 0:
        if cached_latest_issue == str(latest_issue or "") and len(cached_issues) == expected_issue_count:
            return cached_issues, 0
        return [], len(history_asc)
    return cached_issues, missing_recent_issues


def _build_full_history_cache_report_payload(
    *,
    existing_report: dict | None,
    response: BacktestResponse,
    combined_issue_rows: list[dict],
    recent_issues: int,
    scheme_count: int,
    strategy_mode: str,
    ticket_mode: str,
) -> dict:
    stats = build_backtest_stats(combined_issue_rows)  # type: ignore[arg-type]
    issue_rows = combined_issue_rows

    payload = _backtest_response_json_payload(
        response,
        exclude={
            "issues",
            "prize_rates",
            "prize_level_breakdown",
            "coverage_metrics",
            "benchmarks",
            "window_summaries",
            "mode_comparison",
            "issue_comparison",
            "threshold_scan",
        },
    )
    if isinstance(existing_report, dict):
        payload = {**existing_report, **payload}

    payload["recent_issues"] = recent_issues
    payload["requested_issues"] = recent_issues
    payload["skipped_issues"] = 0
    payload["scheme_count"] = scheme_count
    payload["strategy_mode"] = strategy_mode
    payload["ticket_mode"] = ticket_mode
    payload["ai_replay_mode"] = "local_only"
    payload["total_issues"] = stats.total_issues
    payload["total_generated_schemes"] = stats.total_generated_schemes
    payload["won_schemes"] = stats.won_schemes
    payload["total_prize_amount"] = stats.total_prize_amount
    payload["total_cost"] = stats.total_cost
    payload["net_profit"] = stats.net_profit
    payload["overall_win_rate"] = stats.overall_win_rate
    payload["issue_hit_rate"] = stats.issue_hit_rate
    payload["prize_rates"] = _flat_model_json_rows(stats.prize_rates)
    payload["prize_level_breakdown"] = _flat_model_json_rows(stats.prize_level_breakdown)
    payload["issues"] = issue_rows
    payload["coverage_metrics"] = stats.coverage_metrics.__dict__.copy()
    payload["max_drawdown"] = _max_drawdown(issue_rows)
    payload["max_miss_streak"] = _max_miss_streak(issue_rows)
    payload["theoretical_single_win_rate"] = round(_theoretical_single_win_rate(), 6)
    payload["window_summaries"] = _flat_model_json_rows(_build_window_summaries(issue_rows))
    payload.setdefault("benchmarks", [])
    payload.setdefault("mode_comparison", [])
    payload.setdefault("issue_comparison", [])
    payload.setdefault("threshold_scan", [])
    return payload


def _full_history_cache_rebuild_search_profile(
    *,
    scheme_count: int,
    strategy_mode: str,
) -> str:
    if scheme_count >= 5:
        return "coarse"
    return "full"


def _reusable_full_history_cache_profile_metadata(
    *,
    profile: str,
    spec: dict[str, object],
    manifest_profile: dict[str, object] | None,
    manifest_source_snapshot_at: str | None,
    latest_issue: str | None,
    total_draws: int,
    expected_issue_count: int,
    scheme_count: int,
    ticket_mode: str,
) -> dict | None:
    if not isinstance(manifest_profile, dict):
        return None

    issue_count = int(manifest_profile.get("total_issues") or 0)
    report_latest_issue = str(manifest_profile.get("latest_issue") or "") or None
    report_scheme_count = int(manifest_profile.get("scheme_count") or 0)
    report_ticket_mode = str(manifest_profile.get("ticket_mode") or "")
    requested_issues = int(manifest_profile.get("requested_issues") or 0)
    generated_at = str(manifest_profile.get("generated_at") or "") or None
    if (
        issue_count != expected_issue_count
        or report_latest_issue != latest_issue
        or report_scheme_count != scheme_count
        or report_ticket_mode != ticket_mode
        or requested_issues not in {0, total_draws, expected_issue_count}
        or not generated_at
    ):
        return None

    strategy_mode = str(spec["strategy_mode"])
    tuning_profile_override = spec.get("tuning_profile_override")
    tuning_profile = str(tuning_profile_override) if tuning_profile_override else None
    return {
        "algorithm_version": FULL_HISTORY_CACHE_ALGORITHM_VERSION,
        "generated_at": generated_at,
        "source_snapshot_at": manifest_source_snapshot_at or generated_at,
        "latest_issue": latest_issue,
        "total_draws": total_draws,
        "expected_issue_count": expected_issue_count,
        "scheme_count": scheme_count,
        "ticket_mode": ticket_mode,
        "requested_issues": requested_issues or total_draws,
        "profile": profile,
        "candidate_name": spec.get("candidate_name"),
        "strategy_mode": strategy_mode,
        "tuning_profile_override": tuning_profile,
        "total_issues": issue_count,
        "total_generated_schemes": int(manifest_profile.get("total_generated_schemes") or 0),
        "issue_hit_rate": float(manifest_profile.get("issue_hit_rate") or 0.0),
        "overall_win_rate": float(manifest_profile.get("overall_win_rate") or 0.0),
        "total_prize_amount": float(manifest_profile.get("total_prize_amount") or 0.0),
        "net_profit": float(manifest_profile.get("net_profit") or 0.0),
    }


def _build_full_history_cache_profile_result(
    *,
    profile: str,
    spec: dict[str, object],
    history_asc: list,
    latest_issue: str | None,
    total_draws: int,
    expected_issue_count: int,
    scheme_count: int,
    ticket_mode: str,
    source_snapshot_at: str,
    rebuild_context_cache: dict[str, tuple[list, PrecomputedHistoryFeatures]],
    manifest_profile: dict[str, object] | None = None,
    manifest_source_snapshot_at: str | None = None,
    history_positions: dict[str, int] | None = None,
) -> tuple[str, dict | None, dict]:
    strategy_mode = str(spec["strategy_mode"])
    tuning_profile_override = spec.get("tuning_profile_override")
    tuning_profile = str(tuning_profile_override) if tuning_profile_override else None
    file_name = str(spec["file_name"])
    rebuild_search_profile = _full_history_cache_rebuild_search_profile(
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
    )

    reusable_metadata = _reusable_full_history_cache_profile_metadata(
        profile=profile,
        spec=spec,
        manifest_profile=manifest_profile,
        manifest_source_snapshot_at=manifest_source_snapshot_at,
        latest_issue=latest_issue,
        total_draws=total_draws,
        expected_issue_count=expected_issue_count,
        scheme_count=scheme_count,
        ticket_mode=ticket_mode,
    )
    if reusable_metadata is not None and os.path.exists(_smart_balance_report_file_path(file_name)):
        return profile, None, reusable_metadata

    existing_report = _load_json_report(file_name)
    cached_issues, missing_recent_issues = _incremental_full_history_cache_window(
        report=existing_report,
        history_asc=history_asc,
        latest_issue=latest_issue,
        expected_issue_count=expected_issue_count,
        history_positions=history_positions,
    )
    should_replay = missing_recent_issues != 0 or not cached_issues
    recent_issues = missing_recent_issues if missing_recent_issues > 0 else total_draws

    if should_replay:
        response = run_backtest(
            recent_issues=recent_issues,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ticket_mode=ticket_mode,
            ai_replay_mode="local_only",
            compare_modes=False,
            ai_config=None,
            tuning_profile_override=tuning_profile,
            multiple=1,
            include_baselines=False,
            include_applied_profile_comparison=False,
            skip_auto_tuning_search=True,
            history_context_cache=rebuild_context_cache,
            search_profile=rebuild_search_profile,
        )
    else:
        response = build_backtest_stats(cached_issues)  # type: ignore[arg-type]
        response.recent_issues = total_draws
        response.requested_issues = total_draws
        response.scheme_count = scheme_count
        response.strategy_mode = strategy_mode  # type: ignore[assignment]
        response.ticket_mode = ticket_mode  # type: ignore[assignment]

    response_issue_rows = _issue_rows_from_backtest_response(response)
    if cached_issues and missing_recent_issues > 0 and should_replay:
        merged_issue_map = {
            str(item.get("issue") or ""): item
            for item in cached_issues
            if isinstance(item, dict) and item.get("issue") is not None
        }
        for item in response_issue_rows:
            if isinstance(item, dict) and item.get("issue") is not None:
                merged_issue_map[str(item.get("issue"))] = item
        merged_issue_rows = sorted(
            merged_issue_map.values(),
            key=lambda item: int(str(item.get("issue") or "0")),
        )
    else:
        merged_issue_rows = response_issue_rows

    payload = _build_full_history_cache_report_payload(
        existing_report=existing_report if cached_issues and missing_recent_issues > 0 else None,
        response=response,
        combined_issue_rows=merged_issue_rows,
        recent_issues=total_draws,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ticket_mode=ticket_mode,
    )
    total_issues = int(payload.get("total_issues") or 0)
    requested_issues = int(payload.get("requested_issues") or 0)
    if requested_issues != total_draws:
        raise RuntimeError(f"{profile} requested issue mismatch: {requested_issues}/{total_draws}")
    if total_issues != expected_issue_count:
        raise RuntimeError(f"{profile} runnable issue mismatch: {total_issues}/{expected_issue_count}")

    generated_at = _cache_timestamp()
    metadata = {
        "algorithm_version": FULL_HISTORY_CACHE_ALGORITHM_VERSION,
        "generated_at": generated_at,
        "source_snapshot_at": source_snapshot_at,
        "latest_issue": latest_issue,
        "total_draws": total_draws,
        "expected_issue_count": expected_issue_count,
        "scheme_count": scheme_count,
        "ticket_mode": ticket_mode,
        "requested_issues": total_draws,
        "profile": profile,
        "candidate_name": spec.get("candidate_name"),
        "strategy_mode": strategy_mode,
        "tuning_profile_override": tuning_profile,
        "total_issues": total_issues,
        "total_generated_schemes": int(payload.get("total_generated_schemes") or 0),
        "issue_hit_rate": float(payload.get("issue_hit_rate") or 0.0),
        "overall_win_rate": float(payload.get("overall_win_rate") or 0.0),
        "total_prize_amount": float(payload.get("total_prize_amount") or 0.0),
        "net_profit": float(payload.get("net_profit") or 0.0),
    }
    payload["full_history_cache"] = metadata
    return profile, payload, metadata


def _store_full_history_cache_profile_payload(
    file_name: str,
    payload: dict,
) -> None:
    _write_json_report_atomic(file_name, payload, clear_caches=False)
    _write_json_file_atomic(
        _smart_balance_candidate_cache_file_path(file_name),
        _smart_balance_candidate_cache_payload_from_report(payload),
        compact=True,
    )


def _run_full_history_cache_rebuild_job(job_id: str) -> None:
    _update_full_history_cache_job(
        job_id,
        status="running",
        progress=0.0,
        message="Preparing full-history cache update",
        started_at=datetime.utcnow(),
    )
    try:
        with _full_history_cache_lock:
            job = _full_history_cache_jobs.get(job_id)
            if not job:
                return
            scheme_count = job.scheme_count
            ticket_mode = _normalize_ticket_mode(job.ticket_mode)

        source_snapshot_at = _cache_timestamp()
        history_asc = get_all_history_asc()
        total_draws = len(history_asc)
        latest_issue = str(history_asc[-1].issue) if history_asc else None
        expected_issue_count = _expected_full_history_cache_issue_count_for_total_draws(total_draws)
        history_positions = {str(draw.issue): index for index, draw in enumerate(history_asc)}
        specs = _full_history_cache_profile_specs(scheme_count, ticket_mode)
        existing_manifest = _load_full_history_cache_manifest(scheme_count, ticket_mode)
        manifest_profiles = existing_manifest.get("profiles") if isinstance(existing_manifest, dict) and isinstance(existing_manifest.get("profiles"), dict) else {}
        manifest_source_snapshot_at = (
            str(existing_manifest.get("source_snapshot_at") or existing_manifest.get("generated_at") or "")
            if isinstance(existing_manifest, dict)
            else ""
        ) or None
        rebuild_context_cache = _build_history_context_cache(history_asc, history_asc[-total_draws:] if total_draws > 0 else [])
        report_metadata: dict[str, dict] = {}
        profile_items = list(specs.items())
        profile_count = max(1, len(profile_items))
        max_workers = min(FULL_HISTORY_CACHE_PROFILE_MAX_WORKERS, profile_count)
        _update_full_history_cache_job(
            job_id,
            progress=0.0,
            message=f"Updating {profile_count} cache profiles with up to {max_workers} workers",
        )

        completed_profiles = 0
        if max_workers <= 1:
            for profile, spec in profile_items:
                profile_name, payload, metadata = _build_full_history_cache_profile_result(
                    profile=profile,
                    spec=spec,
                    history_asc=history_asc,
                    latest_issue=latest_issue,
                    total_draws=total_draws,
                    expected_issue_count=expected_issue_count,
                    scheme_count=scheme_count,
                    ticket_mode=ticket_mode,
                    source_snapshot_at=source_snapshot_at,
                    rebuild_context_cache=rebuild_context_cache,
                    manifest_profile=manifest_profiles.get(profile) if isinstance(manifest_profiles, dict) else None,
                    manifest_source_snapshot_at=manifest_source_snapshot_at,
                    history_positions=history_positions,
                )
                if payload is not None:
                    _store_full_history_cache_profile_payload(str(spec["file_name"]), payload)
                report_metadata[profile_name] = metadata
                completed_profiles += 1
                _update_full_history_cache_job(
                    job_id,
                    progress=completed_profiles / profile_count,
                    message=f"Updated {completed_profiles}/{profile_count} cache profiles",
                )
        else:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fh-cache-profile") as executor:
                future_map = {
                    executor.submit(
                        _build_full_history_cache_profile_result,
                        profile=profile,
                        spec=spec,
                        history_asc=history_asc,
                        latest_issue=latest_issue,
                        total_draws=total_draws,
                        expected_issue_count=expected_issue_count,
                        scheme_count=scheme_count,
                        ticket_mode=ticket_mode,
                        source_snapshot_at=source_snapshot_at,
                        rebuild_context_cache=rebuild_context_cache,
                        manifest_profile=manifest_profiles.get(profile) if isinstance(manifest_profiles, dict) else None,
                        manifest_source_snapshot_at=manifest_source_snapshot_at,
                        history_positions=history_positions,
                    ): (profile, spec)
                    for profile, spec in profile_items
                }
                for future in as_completed(future_map):
                    profile, spec = future_map[future]
                    profile_name, payload, metadata = future.result()
                    if payload is not None:
                        _store_full_history_cache_profile_payload(str(spec["file_name"]), payload)
                    report_metadata[profile_name] = metadata
                    completed_profiles += 1
                    _update_full_history_cache_job(
                        job_id,
                        progress=completed_profiles / profile_count,
                        message=f"Updated {completed_profiles}/{profile_count} cache profiles",
                    )

        manifest_generated_at = _cache_timestamp()
        manifest = {
            "algorithm_version": FULL_HISTORY_CACHE_ALGORITHM_VERSION,
            "generated_at": manifest_generated_at,
            "source_snapshot_at": source_snapshot_at,
            "latest_issue": latest_issue,
            "total_draws": total_draws,
            "expected_issue_count": expected_issue_count,
            "scheme_count": scheme_count,
            "ticket_mode": ticket_mode,
            "profiles": _full_history_cache_manifest_profile_entries(specs, report_metadata),
        }
        _write_json_report_atomic(
            os.path.basename(_full_history_cache_manifest_path(scheme_count, ticket_mode)),
            manifest,
            clear_caches=False,
        )
        _clear_smart_balance_candidate_cache()
        _clear_full_history_cache_status_cache()
        _clear_smart_balance_report_signature_cache()
        _update_full_history_cache_job(
            job_id,
            status="completed",
            progress=1.0,
            message="Full-history cache update completed",
            finished_at=datetime.utcnow(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Full-history cache rebuild failed: %s", job_id)
        _update_full_history_cache_job(
            job_id,
            status="failed",
            progress=1.0,
            message="Full-history cache update failed",
            error=str(exc),
            finished_at=datetime.utcnow(),
        )


def create_full_history_cache_rebuild_job(
    scheme_count: int = 3,
    ticket_mode: str = "basic",
    *,
    force: bool = False,
) -> FullHistoryCacheRebuildJob:
    ticket_mode = _normalize_ticket_mode(ticket_mode)
    active_job = _active_full_history_cache_job(scheme_count, ticket_mode)
    if active_job:
        return active_job
    status = get_full_history_cache_status(scheme_count=scheme_count, ticket_mode=ticket_mode)
    if status.valid:
        job = _FullHistoryCacheJobState(
            job_id=uuid4().hex,
            scheme_count=scheme_count,
            ticket_mode=ticket_mode,
            status="completed",
            progress=1.0,
            message="Full-history cache is already up to date",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
        )
        with _full_history_cache_lock:
            _full_history_cache_jobs[job.job_id] = job
            _trim_full_history_cache_jobs()
        return _serialize_full_history_cache_job(job)

    job = _FullHistoryCacheJobState(
        job_id=uuid4().hex,
        scheme_count=scheme_count,
        ticket_mode=ticket_mode,
        message="Queued full-history cache update",
    )
    with _full_history_cache_lock:
        _full_history_cache_jobs[job.job_id] = job
        _trim_full_history_cache_jobs()
    _full_history_cache_executor.submit(_run_full_history_cache_rebuild_job, job.job_id)
    return _serialize_full_history_cache_job(job)


def rebuild_full_history_cache_now(
    scheme_count: int = 3,
    ticket_mode: str = "basic",
    *,
    force: bool = False,
) -> FullHistoryCacheStatus:
    ticket_mode = _normalize_ticket_mode(ticket_mode)
    status = get_full_history_cache_status(scheme_count=scheme_count, ticket_mode=ticket_mode)
    if status.valid and not force:
        return status

    job = _FullHistoryCacheJobState(
        job_id=uuid4().hex,
        scheme_count=scheme_count,
        ticket_mode=ticket_mode,
        message="Running full-history cache update synchronously",
    )
    with _full_history_cache_lock:
        _full_history_cache_jobs[job.job_id] = job
        _trim_full_history_cache_jobs()

    _run_full_history_cache_rebuild_job(job.job_id)

    final_job = get_full_history_cache_rebuild_job(job.job_id)
    if final_job and final_job.status == "failed":
        raise RuntimeError(final_job.error or "full-history cache update failed")
    return get_full_history_cache_status(scheme_count=scheme_count, ticket_mode=ticket_mode)


def get_full_history_cache_rebuild_job(job_id: str) -> FullHistoryCacheRebuildJob | None:
    with _full_history_cache_lock:
        job = _full_history_cache_jobs.get(job_id)
        return _serialize_full_history_cache_job(job) if job else None


def _smart_balance_report_file_path(file_name: str) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "reports", file_name))


def _full_history_cache_issue_sidecar_file_name(file_name: str) -> str:
    base_name, extension = os.path.splitext(file_name)
    return f"{base_name}.issues{extension or '.json'}"


def _full_history_cache_issue_sidecar_path(file_name: str) -> str:
    return _smart_balance_report_file_path(_full_history_cache_issue_sidecar_file_name(file_name))


def _full_history_cache_issue_chunk_file_name(file_name: str, chunk_index: int) -> str:
    base_name, extension = os.path.splitext(file_name)
    return f"{base_name}.issues.{chunk_index:04d}{extension or '.json'}"


def _full_history_cache_issue_chunk_path(file_name: str, chunk_index: int) -> str:
    return _smart_balance_report_file_path(_full_history_cache_issue_chunk_file_name(file_name, chunk_index))


def _load_full_history_cache_issue_rows(file_name: str) -> list[dict] | None:
    issue_sidecar_path = _full_history_cache_issue_sidecar_path(file_name)
    issue_payload, _sidecar_exists = _load_json_dict_file_cached(
        issue_sidecar_path,
        warning_label=f"report issues {os.path.basename(issue_sidecar_path)}",
    )
    if not isinstance(issue_payload, dict):
        return None

    legacy_issues = issue_payload.get("issues")
    if isinstance(legacy_issues, list):
        return [item for item in legacy_issues if isinstance(item, dict)]

    if not issue_payload.get("sharded_issues"):
        return None

    chunk_files = issue_payload.get("chunks")
    if not isinstance(chunk_files, list):
        return None

    issues: list[dict] = []
    for chunk_file in chunk_files:
        if not isinstance(chunk_file, str) or not chunk_file:
            continue
        chunk_path = _smart_balance_report_file_path(chunk_file)
        chunk_payload, _chunk_exists = _load_json_dict_file_cached(
            chunk_path,
            warning_label=f"report issue chunk {chunk_file}",
        )
        chunk_issues = chunk_payload.get("issues") if isinstance(chunk_payload, dict) else None
        if not isinstance(chunk_issues, list):
            continue
        issues.extend(item for item in chunk_issues if isinstance(item, dict))
    return issues


def _write_full_history_cache_issue_sidecar(
    file_name: str,
    issues: list[dict],
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    issue_sidecar_path = _full_history_cache_issue_sidecar_path(file_name)
    chunk_size = max(1, FULL_HISTORY_CACHE_ISSUE_CHUNK_SIZE)
    total_issues = len(issues)
    new_chunk_count = (total_issues + chunk_size - 1) // chunk_size if total_issues > 0 else 0

    existing_payload, existing_exists = _load_json_dict_file_cached(
        issue_sidecar_path,
        warning_label=f"report issues {os.path.basename(issue_sidecar_path)}",
    )
    existing_chunk_files: list[str] = []
    reusable_prefix_count = 0
    if isinstance(existing_payload, dict) and existing_payload.get("sharded_issues"):
        raw_chunk_files = existing_payload.get("chunks")
        if isinstance(raw_chunk_files, list):
            existing_chunk_files = [item for item in raw_chunk_files if isinstance(item, str) and item]
        existing_issue_count = int(existing_payload.get("issue_count") or 0)
        compatible_metadata = isinstance(metadata, dict) and (
            str(existing_payload.get("algorithm_version") or "") == str(metadata.get("algorithm_version") or "")
            and str(existing_payload.get("profile") or "") == str(metadata.get("profile") or "")
            and str(existing_payload.get("ticket_mode") or "") == str(metadata.get("ticket_mode") or "")
            and int(existing_payload.get("scheme_count") or 0) == int(metadata.get("scheme_count") or 0)
        )
        if compatible_metadata and 0 < existing_issue_count < total_issues and existing_chunk_files:
            last_existing_chunk_index = min(len(existing_chunk_files) - 1, (existing_issue_count - 1) // chunk_size)
            last_existing_chunk_file = existing_chunk_files[last_existing_chunk_index]
            last_existing_chunk_path = _smart_balance_report_file_path(last_existing_chunk_file)
            last_existing_chunk_payload, _last_chunk_exists = _load_json_dict_file_cached(
                last_existing_chunk_path,
                warning_label=f"report issue chunk {last_existing_chunk_file}",
            )
            last_existing_chunk_issues = (
                last_existing_chunk_payload.get("issues")
                if isinstance(last_existing_chunk_payload, dict)
                else None
            )
            if isinstance(last_existing_chunk_issues, list) and last_existing_chunk_issues:
                existing_latest_issue = str(last_existing_chunk_issues[-1].get("issue") or "")
                payload_latest_prefix_issue = str(issues[existing_issue_count - 1].get("issue") or "")
                if existing_latest_issue and existing_latest_issue == payload_latest_prefix_issue:
                    reusable_prefix_count = (existing_issue_count // chunk_size) * chunk_size

    for chunk_start in range(reusable_prefix_count, total_issues, chunk_size):
        chunk_index = chunk_start // chunk_size
        _write_json_file_atomic(
            _full_history_cache_issue_chunk_path(file_name, chunk_index),
            {"issues": issues[chunk_start: chunk_start + chunk_size]},
            compact=True,
        )

    manifest_chunk_files = [
        _full_history_cache_issue_chunk_file_name(file_name, chunk_index)
        for chunk_index in range(new_chunk_count)
    ]
    if existing_chunk_files:
        obsolete_chunk_files = set(existing_chunk_files) - set(manifest_chunk_files)
        for chunk_file in obsolete_chunk_files:
            chunk_path = _smart_balance_report_file_path(chunk_file)
            try:
                os.remove(chunk_path)
            except FileNotFoundError:
                pass
            except OSError as exc:  # noqa: BLE001
                logger.warning("Failed to remove stale report issue chunk %s: %s", chunk_file, exc)
            _clear_json_dict_file_cache(chunk_path)

    issue_manifest = {
        "sharded_issues": True,
        "chunk_size": chunk_size,
        "issue_count": total_issues,
        "chunks": manifest_chunk_files,
        "latest_issue": str(issues[-1].get("issue") or "") if issues else None,
    }
    if isinstance(metadata, dict):
        issue_manifest.update(
            {
                "algorithm_version": metadata.get("algorithm_version"),
                "profile": metadata.get("profile"),
                "scheme_count": metadata.get("scheme_count"),
                "ticket_mode": metadata.get("ticket_mode"),
            }
        )
    _write_json_file_atomic(issue_sidecar_path, issue_manifest, compact=True)


def _should_split_full_history_cache_issue_payload(file_name: str, payload: dict) -> bool:
    if not file_name.startswith(f"{FULL_HISTORY_CACHE_MANIFEST_PREFIX}_"):
        return False
    if ".manifest." in file_name:
        return False
    if not isinstance(payload.get("issues"), list):
        return False
    return isinstance(payload.get("full_history_cache"), dict)


def _smart_balance_candidate_cache_file_name(file_name: str) -> str:
    base_name, extension = os.path.splitext(file_name)
    return f"{base_name}.candidate-cache{extension or '.json'}"


def _smart_balance_candidate_cache_file_path(file_name: str) -> str:
    return _smart_balance_report_file_path(_smart_balance_candidate_cache_file_name(file_name))


def _full_history_cache_candidate_report_files(
    scheme_count: int = 3,
    ticket_mode: str = "basic",
) -> dict[str, str] | None:
    manifest = _load_full_history_cache_manifest(scheme_count, _normalize_ticket_mode(ticket_mode))
    profiles = manifest.get("profiles") if isinstance(manifest, dict) else None
    if not isinstance(profiles, dict):
        return None
    specs = _full_history_cache_profile_specs(scheme_count, ticket_mode)
    report_files: dict[str, str] = {}
    for profile, spec in specs.items():
        manifest_profile = profiles.get(profile)
        file_name = (
            str(manifest_profile.get("file_name"))
            if isinstance(manifest_profile, dict) and manifest_profile.get("file_name")
            else str(spec["file_name"])
        )
        report_files[profile] = file_name
    return report_files


def _smart_balance_report_signature(
    scheme_count: int = 3,
    ticket_mode: str = "basic",
) -> tuple[tuple[str, float, int], ...]:
    normalized_ticket_mode = _normalize_ticket_mode(ticket_mode)
    cache_key = (scheme_count, normalized_ticket_mode)
    now = monotonic()
    with _smart_balance_report_cache_lock:
        cached = _smart_balance_report_signature_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1]
    report_files = _full_history_cache_candidate_report_files(scheme_count, ticket_mode) or SMART_BALANCE_CANDIDATE_REPORT_FILES
    file_names = [*report_files.values()]
    signature: list[tuple[str, float, int]] = []
    for file_name in file_names:
        path = _smart_balance_report_file_path(file_name)
        try:
            stat_result = os.stat(path)
            signature.append((path, stat_result.st_mtime, stat_result.st_size))
        except OSError:
            signature.append((path, 0.0, 0))
    resolved_signature = tuple(signature)
    with _smart_balance_report_cache_lock:
        _smart_balance_report_signature_cache[cache_key] = (
            now + SMART_BALANCE_REPORT_SIGNATURE_TTL_SECONDS,
            resolved_signature,
        )
    return resolved_signature


def _smart_balance_issue_result_from_report(issue: dict) -> dict:
    return {
        "issue": str(issue.get("issue") or ""),
        "draw_date": issue.get("draw_date"),
        "issue_confidence": float(issue.get("issue_confidence") or 0.0),
        "front_confidence": float(issue.get("front_confidence") or 0.0),
        "back_confidence": float(issue.get("back_confidence") or 0.0),
        "front_best_match_count": int(issue.get("front_best_match_count") or 0),
        "back_best_match_count": int(issue.get("back_best_match_count") or 0),
        "won_count": int(issue.get("won_count") or 0),
        "total_prize_amount": float(issue.get("total_prize_amount") or 0.0),
        "best_prize_level": issue.get("best_prize_level"),
        "best_prize_amount": issue.get("best_prize_amount"),
        "prize_level_hits": issue.get("prize_level_hits") or {},
        "top3_hit": bool(issue.get("top3_hit")),
        "top4_hit": bool(issue.get("top4_hit")),
        "front_4plus_hit": bool(issue.get("front_4plus_hit")),
        "front_5_hit": bool(issue.get("front_5_hit")),
        "five_plus_zero_hit": bool(issue.get("five_plus_zero_hit")),
        "five_plus_one_hit": bool(issue.get("five_plus_one_hit")),
        "five_plus_two_hit": bool(issue.get("five_plus_two_hit")),
        "four_plus_two_hit": bool(issue.get("four_plus_two_hit")),
        "back_2plus_hit": bool(issue.get("back_2plus_hit")),
        "issue_power_score": float(issue.get("issue_power_score") or 0.0),
        "winning_scheme_labels": issue.get("winning_scheme_labels") or [],
    }


def _smart_balance_single_hit_issue_result(issue_comparison: dict) -> dict:
    secondary = issue_comparison.get("secondary") if isinstance(issue_comparison, dict) else None
    secondary = secondary if isinstance(secondary, dict) else {}
    best_amount = secondary.get("best_prize_amount")
    return {
        "issue": str(issue_comparison.get("issue") or ""),
        "draw_date": issue_comparison.get("draw_date"),
        "won_count": int(secondary.get("won_count") or 0),
        "total_prize_amount": float(best_amount or 0.0),
        "best_prize_level": secondary.get("best_prize_level"),
        "best_prize_amount": best_amount,
        "prize_level_hits": secondary.get("prize_level_hits") or {},
        "top3_hit": bool(secondary.get("top3_hit")),
        "top4_hit": bool(secondary.get("top4_hit")),
        "front_4plus_hit": bool(secondary.get("front_4plus_hit")),
        "front_5_hit": bool(secondary.get("front_5_hit")),
        "five_plus_zero_hit": bool(secondary.get("five_plus_zero_hit")),
        "five_plus_one_hit": bool(secondary.get("five_plus_one_hit")),
        "five_plus_two_hit": bool(secondary.get("five_plus_two_hit")),
        "four_plus_two_hit": bool(secondary.get("four_plus_two_hit")),
        "back_2plus_hit": bool(secondary.get("back_2plus_hit")),
        "issue_power_score": float(secondary.get("issue_power_score") or 0.0),
    }


def _smart_balance_candidate_cache_payload_from_report(report: dict) -> dict:
    cache_payload = {
        "issue_map": {},
        "single_hit_issue_map": {},
    }
    for issue in report.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        issue_result = _smart_balance_issue_result_from_report(issue)
        if issue_result["issue"]:
            cache_payload["issue_map"][issue_result["issue"]] = issue_result
    for issue_comparison in report.get("issue_comparison") or []:
        if not isinstance(issue_comparison, dict):
            continue
        issue_result = _smart_balance_single_hit_issue_result(issue_comparison)
        if issue_result["issue"]:
            cache_payload["single_hit_issue_map"][issue_result["issue"]] = issue_result
    metadata = report.get("full_history_cache")
    if isinstance(metadata, dict):
        cache_payload["full_history_cache"] = {
            "generated_at": metadata.get("generated_at"),
            "latest_issue": metadata.get("latest_issue"),
            "scheme_count": metadata.get("scheme_count"),
            "ticket_mode": metadata.get("ticket_mode"),
            "profile": metadata.get("profile"),
        }
    cache_payload["issue_count"] = len(cache_payload["issue_map"])
    cache_payload["single_hit_issue_count"] = len(cache_payload["single_hit_issue_map"])
    return cache_payload


def _smart_balance_candidate_issue_map_from_cache(cache_payload: dict, key: str) -> dict[str, dict]:
    raw_value = cache_payload.get(key)
    if isinstance(raw_value, dict):
        return {
            str(issue): item
            for issue, item in raw_value.items()
            if issue and isinstance(item, dict)
        }
    if isinstance(raw_value, list):
        issue_map: dict[str, dict] = {}
        for item in raw_value:
            if not isinstance(item, dict):
                continue
            issue_key = str(item.get("issue") or "")
            if issue_key:
                issue_map[issue_key] = item
        return issue_map
    return {}


def _load_or_build_smart_balance_candidate_cache(file_name: str) -> dict | None:
    cache_path = _smart_balance_candidate_cache_file_path(file_name)
    report_path = _smart_balance_report_file_path(file_name)
    report_signature, report_exists = _json_dict_file_signature(report_path, warning_label=f"report {file_name}")
    if not report_exists or report_signature is None:
        return None

    cache_signature, cache_exists = _json_dict_file_signature(
        cache_path,
        warning_label=f"candidate cache {_smart_balance_candidate_cache_file_name(file_name)}",
    )
    if (
        cache_exists
        and cache_signature is not None
        and cache_signature[0] >= report_signature[0]
    ):
        cache_payload, _exists = _load_json_dict_file_cached(
            cache_path,
            warning_label=f"candidate cache {_smart_balance_candidate_cache_file_name(file_name)}",
            signature=cache_signature,
        )
        if isinstance(cache_payload, dict):
            return cache_payload

    report = _load_json_report(file_name)
    if not isinstance(report, dict):
        return None
    issue_rows = report.get("issues")
    issue_comparison_rows = report.get("issue_comparison")
    existing_cache_payload, _existing_cache_exists = _load_json_dict_file_cached(
        cache_path,
        warning_label=f"candidate cache {_smart_balance_candidate_cache_file_name(file_name)}",
    )
    issue_map: dict[str, dict] = {}
    single_hit_issue_map: dict[str, dict] = {}
    reused_tail_append = False

    if (
        isinstance(existing_cache_payload, dict)
        and isinstance(issue_rows, list)
        and isinstance(issue_comparison_rows, list)
    ):
        existing_issue_map = _smart_balance_candidate_issue_map_from_cache(existing_cache_payload, "issue_map")
        existing_single_hit_issue_map = _smart_balance_candidate_issue_map_from_cache(
            existing_cache_payload,
            "single_hit_issue_map",
        )
        existing_issue_count = len(existing_issue_map)
        existing_single_hit_issue_count = len(existing_single_hit_issue_map)
        current_issue_count = len([item for item in issue_rows if isinstance(item, dict)])
        current_single_hit_issue_count = len([item for item in issue_comparison_rows if isinstance(item, dict)])
        existing_latest_issue = str(existing_cache_payload.get("latest_issue") or "")
        report_metadata = report.get("full_history_cache") if isinstance(report.get("full_history_cache"), dict) else {}
        report_latest_issue = str(report_metadata.get("latest_issue") or "")

        if (
            existing_issue_map
            and existing_single_hit_issue_map is not None
            and 0 < existing_issue_count <= current_issue_count
            and 0 <= existing_single_hit_issue_count <= current_single_hit_issue_count
            and existing_latest_issue
            and current_issue_count > existing_issue_count
        ):
            prefix_issue = issue_rows[existing_issue_count - 1] if existing_issue_count - 1 < len(issue_rows) else None
            prefix_issue_key = str(prefix_issue.get("issue") or "") if isinstance(prefix_issue, dict) else ""
            if prefix_issue_key and prefix_issue_key == existing_latest_issue:
                issue_map = dict(existing_issue_map)
                single_hit_issue_map = dict(existing_single_hit_issue_map)
                for issue in issue_rows[existing_issue_count:]:
                    if not isinstance(issue, dict):
                        continue
                    issue_result = _smart_balance_issue_result_from_report(issue)
                    if issue_result["issue"]:
                        issue_map[issue_result["issue"]] = issue_result
                for issue_comparison in issue_comparison_rows[existing_single_hit_issue_count:]:
                    if not isinstance(issue_comparison, dict):
                        continue
                    issue_result = _smart_balance_single_hit_issue_result(issue_comparison)
                    if issue_result["issue"]:
                        single_hit_issue_map[issue_result["issue"]] = issue_result
                reused_tail_append = True

    if reused_tail_append:
        cache_payload = {
            "issue_map": issue_map,
            "single_hit_issue_map": single_hit_issue_map,
        }
        metadata = report.get("full_history_cache")
        if isinstance(metadata, dict):
            cache_payload["full_history_cache"] = {
                "generated_at": metadata.get("generated_at"),
                "latest_issue": metadata.get("latest_issue"),
                "scheme_count": metadata.get("scheme_count"),
                "ticket_mode": metadata.get("ticket_mode"),
                "profile": metadata.get("profile"),
            }
        cache_payload["issue_count"] = len(issue_map)
        cache_payload["single_hit_issue_count"] = len(single_hit_issue_map)
        cache_payload["latest_issue"] = str(
            (cache_payload.get("full_history_cache") or {}).get("latest_issue") or ""
        ) or next(reversed(issue_map), None)
    else:
        cache_payload = _smart_balance_candidate_cache_payload_from_report(report)
        metadata = report.get("full_history_cache")
        if isinstance(metadata, dict):
            cache_payload["latest_issue"] = str(metadata.get("latest_issue") or "") or None

    _write_json_file_atomic(cache_path, cache_payload, compact=True)
    return cache_payload


def _smart_balance_issue_with_proxy_signals(issue_result: dict) -> dict:
    normalized = dict(issue_result)
    prize_level_hits = normalized.get("prize_level_hits")
    if not isinstance(prize_level_hits, dict):
        prize_level_hits = {}
    best_prize_level = normalized.get("best_prize_level")
    if not isinstance(best_prize_level, str) or not best_prize_level:
        best_prize_level = None

    present_levels = {str(level) for level, count in prize_level_hits.items() if int(count or 0) > 0}
    if best_prize_level:
        present_levels.add(best_prize_level)
    if not best_prize_level and present_levels:
        for level in PRIZE_LEVEL_ORDER:
            if level in present_levels:
                best_prize_level = level
                break

    top3_from_level = any(level in TOP3_PRIZE_LEVELS for level in present_levels)
    top4_from_level = any(level in TOP4_PRIZE_LEVELS for level in present_levels)
    five_plus_two_from_level = "一等奖" in present_levels
    five_plus_one_from_level = bool({"一等奖", "二等奖"} & present_levels)
    five_plus_zero_from_level = bool({"一等奖", "二等奖", "三等奖"} & present_levels)
    four_plus_two_from_level = bool({"一等奖", "四等奖"} & present_levels)
    back_2plus_from_level = bool({"一等奖", "四等奖"} & present_levels)

    front_best_match_count = int(normalized.get("front_best_match_count") or 0)
    back_best_match_count = int(normalized.get("back_best_match_count") or 0)
    if front_best_match_count <= 0:
        if top3_from_level:
            front_best_match_count = 5
        elif top4_from_level:
            front_best_match_count = 4
    if back_best_match_count <= 0:
        if five_plus_two_from_level or four_plus_two_from_level:
            back_best_match_count = 2
        elif five_plus_one_from_level:
            back_best_match_count = 1

    normalized["top3_hit"] = bool(normalized.get("top3_hit")) or top3_from_level
    normalized["top4_hit"] = bool(normalized.get("top4_hit")) or top4_from_level
    normalized["front_4plus_hit"] = bool(normalized.get("front_4plus_hit")) or front_best_match_count >= 4
    normalized["front_5_hit"] = bool(normalized.get("front_5_hit")) or front_best_match_count >= 5
    normalized["five_plus_zero_hit"] = bool(normalized.get("five_plus_zero_hit")) or five_plus_zero_from_level
    normalized["five_plus_one_hit"] = bool(normalized.get("five_plus_one_hit")) or five_plus_one_from_level
    normalized["five_plus_two_hit"] = bool(normalized.get("five_plus_two_hit")) or five_plus_two_from_level
    normalized["four_plus_two_hit"] = bool(normalized.get("four_plus_two_hit")) or four_plus_two_from_level
    normalized["back_2plus_hit"] = bool(normalized.get("back_2plus_hit")) or back_best_match_count >= 2 or back_2plus_from_level
    normalized["front_best_match_count"] = front_best_match_count
    normalized["back_best_match_count"] = back_best_match_count
    normalized["issue_power_score"] = max(
        float(normalized.get("issue_power_score") or 0.0),
        _evaluation_power_score(
            front_match_count=front_best_match_count,
            back_match_count=back_best_match_count,
            prize_level=best_prize_level,
        ),
    )
    normalized["prize_level_hits"] = prize_level_hits
    return normalized


def _issue_rows_from_backtest_response(response: BacktestResponse) -> list[dict]:
    return [_backtest_issue_result_json_row(item) for item in response.issues]


def _load_smart_balance_candidate_results(
    scheme_count: int = 3,
    ticket_mode: str = "basic",
) -> dict[str, dict[str, dict]]:
    global _smart_balance_report_cache_signature, _smart_balance_report_candidate_cache
    signature = _smart_balance_report_signature(scheme_count, ticket_mode)
    with _smart_balance_report_cache_lock:
        if _smart_balance_report_candidate_cache is not None and _smart_balance_report_cache_signature == signature:
            return _smart_balance_report_candidate_cache

    candidate_results: dict[str, dict[str, dict]] = {
        profile_name: {} for profile_name, *_ in _smart_balance_candidate_profiles()
    }
    report_files = _full_history_cache_candidate_report_files(scheme_count, ticket_mode) or SMART_BALANCE_CANDIDATE_REPORT_FILES
    report_tasks = [
        (report_profile, file_name, candidate_name)
        for report_profile, file_name in report_files.items()
        if (candidate_name := SMART_BALANCE_REPORT_PROFILE_MAP.get(report_profile)) and candidate_name in candidate_results
    ]

    def _load_candidate_report(task: tuple[str, str, str]) -> tuple[str, dict[str, dict], dict[str, dict]]:
        report_profile, file_name, candidate_name = task
        candidate_cache = _load_or_build_smart_balance_candidate_cache(file_name)
        if not isinstance(candidate_cache, dict):
            return candidate_name, {}, {}

        profile_issues = _smart_balance_candidate_issue_map_from_cache(candidate_cache, "issue_map")
        if not profile_issues:
            profile_issues = _smart_balance_candidate_issue_map_from_cache(candidate_cache, "issues")

        single_profile_issues: dict[str, dict] = {}
        if report_profile == "default_multi":
            single_candidate_name = SMART_BALANCE_REPORT_PROFILE_MAP.get("single_hit_default")
            if single_candidate_name and single_candidate_name in candidate_results:
                single_profile_issues = _smart_balance_candidate_issue_map_from_cache(
                    candidate_cache,
                    "single_hit_issue_map",
                )
                if not single_profile_issues:
                    single_profile_issues = _smart_balance_candidate_issue_map_from_cache(
                        candidate_cache,
                        "single_hit_issues",
                    )
        return candidate_name, profile_issues, single_profile_issues

    if report_tasks:
        max_workers = min(SMART_BALANCE_REPORT_LOAD_MAX_WORKERS, len(report_tasks))
        if max_workers <= 1:
            loaded_reports = [_load_candidate_report(task) for task in report_tasks]
        else:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="smart-report-load") as executor:
                loaded_reports = list(executor.map(_load_candidate_report, report_tasks))
        single_candidate_name = SMART_BALANCE_REPORT_PROFILE_MAP.get("single_hit_default")
        for candidate_name, profile_issues, single_profile_issues in loaded_reports:
            candidate_results[candidate_name].update(profile_issues)
            if single_candidate_name and single_candidate_name in candidate_results and single_profile_issues:
                candidate_results[single_candidate_name].update(single_profile_issues)

    with _smart_balance_report_cache_lock:
        _smart_balance_report_cache_signature = signature
        _smart_balance_report_candidate_cache = candidate_results
    return candidate_results


def _candidate_result_summary_from_issue_values(issue_values) -> dict[str, float]:
    issues = [_smart_balance_issue_with_proxy_signals(item) for item in issue_values]
    total_issues = len(issues)
    total_generated_schemes = sum(int(item.get("scheme_count") or 3) for item in issues)
    won_schemes = sum(int(item.get("won_count") or 0) for item in issues)
    hit_issues = sum(1 for item in issues if int(item.get("won_count") or 0) > 0)
    total_cost = total_generated_schemes * TICKET_PRICE
    total_prize_amount = sum(float(item.get("total_prize_amount") or 0.0) for item in issues)
    overall_win_rate = won_schemes / total_generated_schemes if total_generated_schemes else 0.0
    issue_hit_rate = hit_issues / total_issues if total_issues else 0.0
    roi = total_prize_amount / total_cost if total_cost else 0.0
    average_issue_score = (
        sum(_smart_balance_issue_score(item) for item in issues) / total_issues if total_issues else 0.0
    )
    signal_totals = _performance_signal_totals(issues)
    high_tier_proxy_score = _high_tier_proxy_score(signal_totals, total_issues=total_issues)
    top4_hit_rate = min(1.0, signal_totals["top4_hit_issues"] / total_issues) if total_issues else 0.0
    top3_hit_rate = min(1.0, signal_totals["top3_hit_issues"] / total_issues) if total_issues else 0.0
    five_plus_one_hit_rate = (
        min(1.0, signal_totals["five_plus_one_hit_issues"] / total_issues) if total_issues else 0.0
    )
    five_plus_two_hit_rate = (
        min(1.0, signal_totals["five_plus_two_hit_issues"] / total_issues) if total_issues else 0.0
    )
    return {
        "issues": float(total_issues),
        "won_schemes": float(won_schemes),
        "hit_issues": float(hit_issues),
        "total_cost": total_cost,
        "total_prize_amount": total_prize_amount,
        "net_profit": total_prize_amount - total_cost,
        "overall_win_rate": overall_win_rate,
        "issue_hit_rate": issue_hit_rate,
        "high_tier_proxy_score": high_tier_proxy_score,
        "top4_hit_rate": top4_hit_rate,
        "top3_hit_rate": top3_hit_rate,
        "five_plus_one_hit_rate": five_plus_one_hit_rate,
        "five_plus_two_hit_rate": five_plus_two_hit_rate,
        "score": (
            average_issue_score
            + high_tier_proxy_score * 1.20
            + top4_hit_rate * 0.45
            + top3_hit_rate * 0.30
            + five_plus_one_hit_rate * 0.28
            + five_plus_two_hit_rate * 0.34
            + issue_hit_rate * 0.12
            + overall_win_rate * 0.04
            + roi / 8.0
        ),
    }


def _candidate_result_summary(profile_results: dict[str, dict]) -> dict[str, float]:
    return _candidate_result_summary_from_issue_values(profile_results.values())


def _full_history_mode_priority_score(summary: dict[str, float], *, scheme_count: int, strategy_mode: str) -> tuple[float, float, float, float]:
    issue_hit_rate = float(summary.get("issue_hit_rate") or 0.0)
    overall_win_rate = float(summary.get("overall_win_rate") or 0.0)
    high_tier_proxy_score = float(summary.get("high_tier_proxy_score") or 0.0)
    net_profit = float(summary.get("net_profit") or 0.0)
    score = float(summary.get("score") or 0.0)
    if strategy_mode != "multi_cover":
        return (score, issue_hit_rate, overall_win_rate, net_profit)
    if scheme_count <= 3:
        return (
            issue_hit_rate * 2.8 + overall_win_rate * 0.45 + high_tier_proxy_score * 0.30 + score * 0.20,
            issue_hit_rate,
            overall_win_rate,
            net_profit,
        )
    if scheme_count <= 5:
        return (
            issue_hit_rate * 2.2 + overall_win_rate * 0.60 + high_tier_proxy_score * 0.32 + score * 0.24,
            issue_hit_rate,
            overall_win_rate,
            net_profit,
        )
    return (score, issue_hit_rate, overall_win_rate, net_profit)


def _select_full_history_profile_for_mode(
    history_asc: list,
    strategy_mode: str,
    *,
    scheme_count: int = 3,
    ticket_mode: str = "basic",
) -> SmartBalanceLiveProfile | None:
    candidate_results = _load_smart_balance_candidate_results(scheme_count, ticket_mode)
    _ensure_live_smart_balance_candidate_results(
        history_asc,
        candidate_results,
        scheme_count=scheme_count,
        ticket_mode=ticket_mode,
    )
    candidate_profiles = _smart_balance_candidate_profiles()
    mode_profiles = [
        (profile_name, display_name)
        for profile_name, candidate_strategy_mode, display_name, *_ in candidate_profiles
        if candidate_strategy_mode == strategy_mode
    ]
    if not mode_profiles:
        return None

    mode_profile_results = {
        profile_name: candidate_results.get(profile_name, {})
        for profile_name, _display_name in mode_profiles
    }
    base_profile_name, base_profile_results = min(
        mode_profile_results.items(),
        key=lambda item: len(item[1]),
    )
    other_profile_names = [profile_name for profile_name, _display_name in mode_profiles if profile_name != base_profile_name]

    best_profile_name: str | None = None
    best_summary: dict[str, float] | None = None
    summaries: dict[str, dict[str, float]] = {}
    for profile_name, _display_name in mode_profiles:
        profile_results = mode_profile_results[profile_name]
        if other_profile_names:
            summary = _candidate_result_summary_from_issue_values(
                profile_results[issue]
                for issue in base_profile_results
                if issue in profile_results
                and all(issue in mode_profile_results[other_profile_name] for other_profile_name in other_profile_names)
            )
        else:
            summary = _candidate_result_summary_from_issue_values(profile_results.values())
        summaries[profile_name] = summary
        if summary["issues"] <= 0:
            continue
        current_rank = _full_history_mode_priority_score(
            summary,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
        )
        best_rank = (
            _full_history_mode_priority_score(
                best_summary,
                scheme_count=scheme_count,
                strategy_mode=strategy_mode,
            )
            if best_summary is not None
            else None
        )
        if best_summary is None or current_rank > best_rank:
            best_profile_name = profile_name
            best_summary = summary
    if not best_profile_name or not best_summary:
        return None

    display_lookup = {profile_name: display_name for profile_name, display_name in mode_profiles}
    reason = (
        f"{_smart_balance_mode_label(strategy_mode)} 模式按全历史 {int(best_summary['issues'])} 期重跑结果选档，"
        f"当前采用 {display_lookup.get(best_profile_name, best_profile_name)}；"
        f"高奖代理分 {best_summary['high_tier_proxy_score']:.4f}，"
        f"期命中率 {best_summary['issue_hit_rate']:.3%}，"
        f"注命中率 {best_summary['overall_win_rate']:.3%}，"
        f"净收益 {best_summary['net_profit']:.2f}。"
    )
    return _smart_balance_profile_from_candidate_name(best_profile_name, reason)


def _calibration_history_from_candidate_results(profile_results: dict[str, dict]) -> list[dict]:
    calibration_history: list[dict] = []
    for issue in sorted(profile_results):
        item = profile_results[issue]
        raw_confidence = float(item.get("issue_confidence") or 0.0)
        if raw_confidence <= 0:
            continue
        winning_labels = item.get("winning_scheme_labels")
        winning_label_set = set(winning_labels if isinstance(winning_labels, list) else [])
        label_hits = {label: 1 for label in winning_label_set}
        try:
            issue_mod_7 = int(issue) % 7
        except ValueError:
            issue_mod_7 = 0
        calibration_history.append(
            {
                "raw_confidence": raw_confidence,
                "hit": 1 if int(item.get("won_count") or 0) > 0 else 0,
                "raw_front_confidence": float(item.get("front_confidence") or 0.0),
                "front_hit": 1 if int(item.get("front_best_match_count") or 0) >= 3 else 0,
                "raw_back_confidence": float(item.get("back_confidence") or 0.0),
                "back_hit": 1 if int(item.get("back_best_match_count") or 0) >= 1 else 0,
                "issue_mod_7": issue_mod_7,
                "label_hits": label_hits,
            }
        )
    return calibration_history


def _full_history_report_calibration(
    history_asc: list,
    profile_name: str,
    *,
    scheme_count: int = 3,
    ticket_mode: str = "basic",
) -> list[dict]:
    candidate_results = _load_smart_balance_candidate_results(scheme_count, ticket_mode)
    _ensure_live_smart_balance_candidate_results(
        history_asc,
        candidate_results,
        scheme_count=scheme_count,
        ticket_mode=ticket_mode,
    )
    return _calibration_history_from_candidate_results(candidate_results.get(profile_name, {}))


def _ensure_live_smart_balance_candidate_results(
    history_asc: list,
    candidate_results: dict[str, dict[str, dict]],
    *,
    scheme_count: int = 3,
    ticket_mode: str = "basic",
) -> None:
    candidate_profiles = _active_live_smart_balance_candidate_profiles(candidate_results)
    if not candidate_profiles:
        return
    active_profile_specs = [
        (
            profile_name,
            candidate_strategy_mode,
            display_name,
            score_weights,
            combo_weights,
            candidate_results.get(profile_name, {}),
        )
        for profile_name, candidate_strategy_mode, display_name, score_weights, combo_weights in candidate_profiles
    ]
    missing_targets: list[tuple[object, str, list[tuple[str, str, str, dict[str, float], dict[str, float], dict[str, dict]]]]] = []
    for draw in history_asc:
        issue = str(draw.issue)
        missing_profiles = [
            spec for spec in active_profile_specs
            if issue not in spec[5]
        ]
        if missing_profiles:
            missing_targets.append((draw, issue, missing_profiles))
    if not missing_targets:
        return
    recent_window = max(SMART_BALANCE_GUARD_WINDOW, SMART_BALANCE_WINDOW)
    if len(missing_targets) > recent_window:
        logger.info(
            "Smart balance candidate cache missing %s issues; backfilling the most recent %s only.",
            len(missing_targets),
            recent_window,
        )
        missing_targets = missing_targets[-recent_window:]
    missing_draws = [draw for draw, _issue, _missing_profiles in missing_targets]
    history_context_cache = _build_history_context_cache(history_asc, missing_draws)
    backfill_tasks: list[tuple[int, object, str, str, str, dict[str, float], dict[str, float], list, PrecomputedHistoryFeatures]] = []
    for index, (target, issue, missing_profiles) in enumerate(missing_targets):
        history_item = history_context_cache.get(issue)
        if not history_item:
            continue
        prior_history_desc, history_context = history_item
        if history_context.history_size < BACKTEST_MIN_HISTORY_SIZE:
            continue
        for profile_name, candidate_strategy_mode, display_name, score_weights, combo_weights, _profile_results in missing_profiles:
            backfill_tasks.append(
                (
                    index,
                    target,
                    profile_name,
                    candidate_strategy_mode,
                    display_name,
                    score_weights,
                    combo_weights,
                    prior_history_desc,
                    history_context,
                )
            )

    if not backfill_tasks:
        return

    def _compute_candidate_backfill(
        task: tuple[int, object, str, str, str, dict[str, float], dict[str, float], list, PrecomputedHistoryFeatures]
    ) -> tuple[str, str, dict]:
        (
            index,
            target,
            profile_name,
            candidate_strategy_mode,
            display_name,
            score_weights,
            combo_weights,
            prior_history_desc,
            history_context,
        ) = task
        raw = _evaluate_backtest_issue(
            index,
            target=target,
            prior_history_desc=prior_history_desc,
            history_context=history_context,
            scheme_count=scheme_count,
            strategy_mode=candidate_strategy_mode,
            ticket_mode=ticket_mode,
            backtest_ai_config=None,
            score_weights=score_weights,
            combo_weights=combo_weights,
            tuning_profile=display_name,
            include_baselines=False,
            search_profile="full",
        )
        return (
            profile_name,
            str(target.issue),
            _issue_result_from_backtest_payload(
                raw,
                scheme_count=scheme_count,
                ticket_mode=ticket_mode,
                tuning_profile=display_name,
                count_policy="smart_balance_live_candidate",
                decision_tier=profile_name,
                decision_reason=f"智能平衡现场补算候选档位：{display_name}",
            ),
        )

    max_workers = min(SMART_BALANCE_CANDIDATE_BACKFILL_MAX_WORKERS, len(backfill_tasks))
    if max_workers <= 1:
        for task in backfill_tasks:
            profile_name, issue, issue_result = _compute_candidate_backfill(task)
            candidate_results.setdefault(profile_name, {})[issue] = issue_result
        return

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="smart-balance-backfill") as executor:
        futures = [executor.submit(_compute_candidate_backfill, task) for task in backfill_tasks]
        for future in as_completed(futures):
            profile_name, issue, issue_result = future.result()
            candidate_results.setdefault(profile_name, {})[issue] = issue_result


def _select_smart_balance_candidate_name_from_scores(
    history_asc: list,
    candidate_results: dict[str, dict[str, dict]],
) -> tuple[str | None, str]:
    candidate_profiles = _active_live_smart_balance_candidate_profiles(candidate_results)
    if not candidate_profiles:
        return None, "智能平衡候选档位为空。"
    fallback_profile = candidate_profiles[0][0]
    profile_display = {profile_name: display_name for profile_name, _, display_name, *_ in candidate_profiles}
    active_profile_results = [
        (profile_name, candidate_results.get(profile_name, {}))
        for profile_name, *_ in candidate_profiles
    ]
    profile_issue_windows = {
        profile_name: deque(maxlen=SMART_BALANCE_GUARD_WINDOW)
        for profile_name, _profile_results in active_profile_results
    }
    common_issue_count = 0
    for draw in history_asc:
        issue = str(draw.issue)
        common_issue_row: list[tuple[str, dict]] = []
        for profile_name, profile_results in active_profile_results:
            issue_result = profile_results.get(issue)
            if issue_result is None:
                common_issue_row = []
                break
            common_issue_row.append((profile_name, issue_result))
        if not common_issue_row:
            continue
        common_issue_count += 1
        for profile_name, issue_result in common_issue_row:
            profile_issue_windows[profile_name].append(issue_result)
    if common_issue_count == 0:
        return fallback_profile, "智能平衡没有可用候选回放评分，使用默认候选档位。"

    attack_scores: dict[str, float] = {}
    guard_scores: dict[str, float] = {}
    live_priority_scores: dict[str, float] = {}
    miss_streaks: dict[str, int] = {}
    for profile_name, _profile_results in active_profile_results:
        guard_issue_results = list(profile_issue_windows[profile_name])
        attack_issue_results = guard_issue_results[-SMART_BALANCE_WINDOW:]
        attack_scores[profile_name] = _recent_weighted_issue_score(
            attack_issue_results,
            score_fn=_live_priority_attack_score,
            recent_window=min(SMART_BALANCE_LIVE_WINDOW, len(attack_issue_results)),
            recent_weight=LIVE_PRIORITY_RECENT_WEIGHT,
        )
        guard_score, miss_streak = _smart_balance_live_profile_score(guard_issue_results)
        guard_scores[profile_name] = guard_score
        miss_streaks[profile_name] = miss_streak
        live_priority_scores[profile_name] = round(attack_scores[profile_name] * 0.46 + guard_score * 0.54, 4)

    attack_profile = max(
        attack_scores,
        key=lambda name: (attack_scores[name], live_priority_scores.get(name, 0.0), name == fallback_profile),
    )
    guard_profile = max(
        guard_scores,
        key=lambda name: (guard_scores[name], -miss_streaks.get(name, 0), live_priority_scores.get(name, 0.0), name == fallback_profile),
    )
    if attack_scores[attack_profile] >= guard_scores[guard_profile] + SMART_BALANCE_SWITCH_MARGIN:
        chosen_profile = attack_profile
        reason = (
            f"智能平衡按当前已知历史重算 {SMART_BALANCE_WINDOW}/{SMART_BALANCE_GUARD_WINDOW} 窗口，"
            f"短窗冲高选择 {profile_display.get(chosen_profile, chosen_profile)} "
            f"({attack_scores[chosen_profile]:.3f})，长窗最佳 "
            f"{profile_display.get(guard_profile, guard_profile)} ({guard_scores[guard_profile]:.3f})。"
        )
    else:
        chosen_profile = guard_profile
        reason = (
            f"智能平衡按当前已知历史重算 {SMART_BALANCE_WINDOW}/{SMART_BALANCE_GUARD_WINDOW} 窗口，"
            f"长窗保底选择 {profile_display.get(chosen_profile, chosen_profile)} "
            f"({guard_scores[chosen_profile]:.3f})，短窗最佳 "
            f"{profile_display.get(attack_profile, attack_profile)} ({attack_scores[attack_profile]:.3f})。"
        )
    return chosen_profile, reason


def _select_live_smart_balance_profile(
    history_asc: list,
    *,
    scheme_count: int = 3,
    ticket_mode: str = "basic",
) -> SmartBalanceLiveProfile:
    candidate_results = _load_smart_balance_candidate_results(scheme_count, ticket_mode)
    _ensure_live_smart_balance_candidate_results(
        history_asc,
        candidate_results,
        scheme_count=scheme_count,
        ticket_mode=ticket_mode,
    )
    candidate_name, selection_reason = _select_smart_balance_candidate_name_from_scores(history_asc, candidate_results)
    return _smart_balance_profile_from_candidate_name(candidate_name, selection_reason)


def _live_calibration_cache_key(
    history_asc: list,
    *,
    sample_issues: int,
    scheme_count: int,
    strategy_mode: str,
    score_weights: dict[str, float],
    combo_weights: dict[str, float],
) -> tuple:
    latest_issue = history_asc[-1].issue if history_asc else None
    latest_draw_date = str(history_asc[-1].draw_date) if history_asc else None
    return (
        latest_issue,
        latest_draw_date,
        sample_issues,
        scheme_count,
        strategy_mode,
        tuple(sorted((key, round(value, 6)) for key, value in score_weights.items())),
        tuple(sorted((key, round(value, 6)) for key, value in combo_weights.items())),
    )


_live_calibration_history_cache: dict[tuple, list[dict]] = {}


def _clone_calibration_history_entry(item: dict) -> dict:
    return {
        "raw_confidence": float(item.get("raw_confidence") or 0.0),
        "hit": int(item.get("hit") or 0),
        "raw_front_confidence": float(item.get("raw_front_confidence") or 0.0),
        "front_hit": int(item.get("front_hit") or 0),
        "raw_back_confidence": float(item.get("raw_back_confidence") or 0.0),
        "back_hit": int(item.get("back_hit") or 0),
        "issue_mod_7": int(item.get("issue_mod_7") or 0),
        "label_hits": dict(item.get("label_hits") or {}),
    }


def _clone_calibration_history(history: list[dict]) -> list[dict]:
    return [_clone_calibration_history_entry(item) for item in history]


def _get_live_calibration_history(
    history_asc: list,
    *,
    sample_issues: int,
    scheme_count: int,
    strategy_mode: str,
    ai_config: AIConfigRequest | None,
    score_weights: dict[str, float],
    combo_weights: dict[str, float],
) -> list[dict]:
    cache_key = _live_calibration_cache_key(
        history_asc,
        sample_issues=sample_issues,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        score_weights=score_weights,
        combo_weights=combo_weights,
    )
    cached = _live_calibration_history_cache.get(cache_key)
    if cached is not None:
        return _clone_calibration_history(cached)
    calibration_history = _build_live_calibration_history(
        history_asc,
        sample_issues=sample_issues,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ai_config=ai_config,
        score_weights=score_weights,
        combo_weights=combo_weights,
    )
    _live_calibration_history_cache[cache_key] = _clone_calibration_history(calibration_history)
    while len(_live_calibration_history_cache) > 8:
        oldest_key = next(iter(_live_calibration_history_cache))
        _live_calibration_history_cache.pop(oldest_key, None)
    return calibration_history


def _resolve_live_mode_profile_and_weights(
    history_asc: list,
    *,
    requested_strategy_mode: str,
    scheme_count: int,
) -> tuple[SmartBalanceLiveProfile | None, str, dict[str, float], dict[str, float], str]:
    mode_live_profile = _select_full_history_profile_for_mode(
        history_asc,
        requested_strategy_mode,
        scheme_count=scheme_count,
        ticket_mode="basic",
    )
    if mode_live_profile:
        return (
            mode_live_profile,
            requested_strategy_mode,
            mode_live_profile.score_weights,
            mode_live_profile.combo_weights,
            f"Full History / {mode_live_profile.display_name}",
        )
    return (
        None,
        requested_strategy_mode,
        DEFAULT_SCORE_WEIGHTS.copy(),
        DEFAULT_COMBO_WEIGHTS.copy(),
        "Full History / Default Weights",
    )



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
    if strategy_mode == "multi_cover" and 3 <= scheme_count < 5:
        score_name_allow = set(THREE_PACK_FAST_SCORE_PROFILE_NAMES if fast_tuning else THREE_PACK_SCORE_PROFILE_NAMES)
        combo_name_allow = set(THREE_PACK_FAST_COMBO_PROFILE_NAMES if fast_tuning else THREE_PACK_COMBO_PROFILE_NAMES)
        score_profiles = [item for item in SCORE_WEIGHT_PROFILES if item[0] in score_name_allow]
        combo_profiles = [item for item in COMBO_WEIGHT_PROFILES if item[0] in combo_name_allow]
    elif strategy_mode == "multi_cover" and scheme_count >= 5:
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

    def _snapshot_front_pair_window_hits() -> dict[int, dict[tuple[int, int], int]]:
        pair_hits_by_window: dict[int, dict[tuple[int, int], int]] = {}
        recent_draws = list(recent_history_desc)
        for window_size, _weight in SUPERVISED_WINDOWS:
            pair_hits: dict[tuple[int, int], int] = {}
            for draw_item in recent_draws[:window_size]:
                for left, right in combinations(sorted(draw_item.front_numbers), 2):
                    pair_key = (left, right)
                    pair_hits[pair_key] = pair_hits.get(pair_key, 0) + 1
            pair_hits_by_window[window_size] = pair_hits
        return pair_hits_by_window

    def _snapshot_back_pair_window_hits() -> dict[int, dict[tuple[int, int], int]]:
        pair_hits_by_window: dict[int, dict[tuple[int, int], int]] = {}
        recent_draws = list(recent_history_desc)
        for window_size, _weight in SUPERVISED_WINDOWS:
            pair_hits: dict[tuple[int, int], int] = {}
            for draw_item in recent_draws[:window_size]:
                pair_key = tuple(sorted(draw_item.back_numbers))
                pair_hits[pair_key] = pair_hits.get(pair_key, 0) + 1
            pair_hits_by_window[window_size] = pair_hits
        return pair_hits_by_window

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
            front_pair_window_hits=_snapshot_front_pair_window_hits(),
            back_pair_window_hits=_snapshot_back_pair_window_hits(),
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
        if history_context.history_size < BACKTEST_MIN_HISTORY_SIZE:
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
        all_issue_results.extend(_issue_rows_from_backtest_response(stats))
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
    include_baselines: bool = True,
    search_profile: str = "full",
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
        search_profile=search_profile,
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
    cost = round(selected_scheme_count * _ticket_unit_price(ticket_mode), 2)
    random_issue_results: list[dict] = []
    if include_baselines:
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
    else:
        window_summary = {
            "won_count": 0,
            "best_prize_level": None,
            "best_prize_amount": None,
            "total_prize_amount": 0.0,
            "prize_level_hits": {},
            "prize_level_amounts": {},
        }
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


def _issue_result_from_backtest_payload(
    raw: dict,
    *,
    scheme_count: int,
    ticket_mode: str,
    tuning_profile: str | None,
    count_policy: str,
    decision_tier: str,
    decision_reason: str,
) -> dict:
    evaluation_summary = raw["evaluation_summary"]
    quality_signals = raw["quality_signals"]
    coverage_metrics = raw["coverage_metrics"]
    return {
        "issue": raw["issue"],
        "draw_date": raw["draw_date"],
        "scheme_count": scheme_count,
        "ticket_mode": ticket_mode,
        "tuning_profile": tuning_profile,
        "issue_confidence": float(raw.get("issue_confidence") or 0.0),
        "calibrated_confidence": float(raw.get("issue_confidence") or 0.0),
        "applied_threshold": float(raw.get("dynamic_threshold") or 0.0),
        "should_observe": False,
        "front_confidence": round(float(raw.get("front_confidence") or 0.0), 4),
        "front_calibrated_confidence": round(float(raw.get("front_confidence") or 0.0), 4),
        "front_gate": 0.0,
        "back_confidence": round(float(raw.get("back_confidence") or 0.0), 4),
        "back_calibrated_confidence": round(float(raw.get("back_confidence") or 0.0), 4),
        "back_gate": 0.0,
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
        "cost": round(scheme_count * _ticket_unit_price(ticket_mode), 2),
        "front_pairwise_overlap_avg": coverage_metrics.front_pairwise_overlap_avg,
        "back_pairwise_overlap_avg": coverage_metrics.back_pairwise_overlap_avg,
        "back_pair_reuse_rate": coverage_metrics.back_pair_reuse_rate,
        "fresh_back_number_rate": coverage_metrics.fresh_back_number_rate,
    }


def _smart_balance_issue_score(issue_result: dict) -> float:
    issue_result = _smart_balance_issue_with_proxy_signals(issue_result)
    won_count = int(issue_result.get("won_count") or 0)
    prize_level_hits = issue_result.get("prize_level_hits")
    if not isinstance(prize_level_hits, dict):
        prize_level_hits = {}
    if not prize_level_hits:
        best_prize_level = issue_result.get("best_prize_level")
        if isinstance(best_prize_level, str) and best_prize_level:
            prize_level_hits = {best_prize_level: max(1, won_count)}
    level_score = sum(
        float(prize_level_hits.get(level, 0) or 0) * weight
        for level, weight in SMART_BALANCE_PRIZE_LEVEL_SCORE_WEIGHTS.items()
    )
    hit_score = SMART_BALANCE_HIT_WEIGHT if won_count > 0 else 0.0
    win_score = min(3.0, float(won_count)) * SMART_BALANCE_WIN_WEIGHT
    amount_score = float(issue_result.get("total_prize_amount") or issue_result.get("best_prize_amount") or 0.0)
    amount_score /= SMART_BALANCE_AMOUNT_DIVISOR
    signal_score = 0.0
    for signal_name, weight in SMART_BALANCE_SIGNAL_SCORE_WEIGHTS.items():
        if bool(issue_result.get(signal_name)):
            signal_score += weight
    issue_power_score = min(1.0, max(0.0, float(issue_result.get("issue_power_score") or 0.0)))
    return round(hit_score + win_score + level_score + amount_score + signal_score + issue_power_score * 0.45, 4)


def _smart_balance_attack_issue_score(issue_result: dict) -> float:
    issue_result = _smart_balance_issue_with_proxy_signals(issue_result)
    signal_score = 0.0
    for signal_name, weight in SMART_BALANCE_SIGNAL_SCORE_WEIGHTS.items():
        if bool(issue_result.get(signal_name)):
            signal_score += weight
    issue_power_score = min(1.0, max(0.0, float(issue_result.get("issue_power_score") or 0.0)))
    prize_level_hits = issue_result.get("prize_level_hits")
    if not isinstance(prize_level_hits, dict):
        prize_level_hits = {}
    level_score = sum(
        float(prize_level_hits.get(level, 0) or 0) * weight
        for level, weight in SMART_BALANCE_PRIZE_LEVEL_SCORE_WEIGHTS.items()
        if level not in LOW_TIER_PRIZE_LEVELS
    )
    amount_score = float(issue_result.get("best_prize_amount") or issue_result.get("total_prize_amount") or 0.0)
    amount_score /= max(1.0, SMART_BALANCE_AMOUNT_DIVISOR * 2.0)
    return round(signal_score * 1.15 + issue_power_score * 0.85 + level_score * 0.30 + amount_score, 4)


def _smart_balance_profile_summary_score(stats: BacktestResponse) -> float:
    level_issue_score = 0.0
    breakdown_by_level = {item.level: item for item in stats.prize_level_breakdown}
    for level in PRIZE_LEVEL_ORDER:
        item = breakdown_by_level.get(level)
        if item is None:
            continue
        level_issue_score += item.issue_rate * SMART_BALANCE_PRIZE_LEVEL_SCORE_WEIGHTS.get(level, 0.0)
    signal_totals = _performance_signal_totals(stats.issues)
    high_tier_proxy_score = _high_tier_proxy_score(signal_totals, total_issues=stats.total_issues)
    top4_hit_rate = min(1.0, signal_totals["top4_hit_issues"] / stats.total_issues) if stats.total_issues else 0.0
    five_plus_one_hit_rate = (
        min(1.0, signal_totals["five_plus_one_hit_issues"] / stats.total_issues) if stats.total_issues else 0.0
    )
    five_plus_two_hit_rate = (
        min(1.0, signal_totals["five_plus_two_hit_issues"] / stats.total_issues) if stats.total_issues else 0.0
    )
    roi = stats.total_prize_amount / max(1.0, stats.total_cost)
    return round(
        level_issue_score
        + high_tier_proxy_score * 1.10
        + top4_hit_rate * 0.40
        + five_plus_one_hit_rate * 0.25
        + five_plus_two_hit_rate * 0.30
        + stats.issue_hit_rate * 0.24
        + stats.overall_win_rate * 0.08
        + roi / 8.0,
        4,
    )


def _smart_balance_live_profile_score(issue_results: list[dict]) -> tuple[float, int]:
    if not issue_results:
        return 0.0, 0
    issue_count = len(issue_results)
    recent_score = _recent_weighted_issue_score(
        issue_results,
        score_fn=_live_priority_issue_score,
        recent_window=LIVE_PRIORITY_RECENT_WINDOW,
        recent_weight=LIVE_PRIORITY_RECENT_WEIGHT,
        mid_window=LIVE_PRIORITY_MID_WINDOW,
        mid_weight=LIVE_PRIORITY_MID_WEIGHT,
    )
    attack_score = _recent_weighted_issue_score(
        issue_results,
        score_fn=_live_priority_attack_score,
        recent_window=min(LIVE_PRIORITY_RECENT_WINDOW, issue_count),
        recent_weight=LIVE_PRIORITY_RECENT_WEIGHT,
    )
    bonus, penalty, miss_streak = _live_priority_profile_adjustment(issue_results)
    return round(recent_score * 0.72 + attack_score * 0.28 + bonus - penalty, 4), miss_streak


def _run_smart_balance_backtest_core(
    history_asc: list,
    *,
    recent_issues: int,
    scheme_count: int,
    ticket_mode: str,
    ai_replay_mode: str,
    ai_config: AIConfigRequest | None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> BacktestResponse:
    if ai_replay_mode != "local_only":
        raise ValueError("智能平衡回测目前仅支持本地回放。")
    _resolve_backtest_ai_config(ai_replay_mode, ai_config)
    target_draws = history_asc[-recent_issues:]
    eval_start_index = max(0, len(history_asc) - recent_issues)
    warmup_window = max(SMART_BALANCE_WINDOW, SMART_BALANCE_GUARD_WINDOW)
    warmup_draws = history_asc[max(0, eval_start_index - warmup_window) : eval_start_index]
    eval_draws = [*warmup_draws, *target_draws]
    target_issue_set = {draw.issue for draw in target_draws}
    history_context_cache = _build_history_context_cache(history_asc, eval_draws)
    prepared_targets: list[tuple[int, object, list, PrecomputedHistoryFeatures]] = []
    for index, target in enumerate(eval_draws):
        if cancel_check:
            cancel_check()
        history_item = history_context_cache.get(target.issue)
        if not history_item:
            continue
        prior_history_desc, history_context = history_item
        if history_context.history_size < BACKTEST_MIN_HISTORY_SIZE:
            continue
        prepared_targets.append((index, target, prior_history_desc, history_context))

    candidate_profiles = _smart_balance_candidate_profiles()
    if not candidate_profiles:
        raise ValueError("智能平衡候选档位为空。")

    total_tasks = len(prepared_targets) * len(candidate_profiles)
    completed_tasks = 0
    candidate_issue_results: dict[str, dict[str, dict]] = {profile_name: {} for profile_name, *_ in candidate_profiles}

    def _update_smart_progress(stage: str, progress: float, message: str, processed: int, total: int) -> None:
        if progress_callback:
            progress_callback(
                stage=stage,
                progress=progress,
                message=message,
                processed_issues=processed,
                total_issues=total,
            )

    _update_smart_progress(
        "smart_candidates",
        0.02,
        "正在生成智能平衡候选档位",
        0,
        max(1, total_tasks),
    )

    def evaluate_candidate(
        target_index: int,
        target,
        prior_history_desc: list,
        history_context: PrecomputedHistoryFeatures,
        profile_name: str,
        candidate_strategy_mode: str,
        display_name: str,
        score_weights: dict[str, float],
        combo_weights: dict[str, float],
    ) -> tuple[str, str, dict]:
        raw = _evaluate_backtest_issue(
            target_index,
            target=target,
            prior_history_desc=prior_history_desc,
            history_context=history_context,
            scheme_count=scheme_count,
            strategy_mode=candidate_strategy_mode,
            ticket_mode=ticket_mode,
            backtest_ai_config=None,
            score_weights=score_weights,
            combo_weights=combo_weights,
            tuning_profile=display_name,
            include_baselines=False,
            search_profile="full",
        )
        issue_result = _issue_result_from_backtest_payload(
            raw,
            scheme_count=scheme_count,
            ticket_mode=ticket_mode,
            tuning_profile=display_name,
            count_policy="smart_balance_candidate",
            decision_tier=profile_name,
            decision_reason=f"智能平衡候选档位：{display_name}",
        )
        return profile_name, target.issue, issue_result

    worker_count = _backtest_parallel_workers(total_tasks, ai_replay_mode=ai_replay_mode)
    if worker_count <= 1:
        for target_index, target, prior_history_desc, history_context in prepared_targets:
            for profile_name, candidate_strategy_mode, display_name, score_weights, combo_weights in candidate_profiles:
                if cancel_check:
                    cancel_check()
                profile_name, issue, issue_result = evaluate_candidate(
                    target_index,
                    target,
                    prior_history_desc,
                    history_context,
                    profile_name,
                    candidate_strategy_mode,
                    display_name,
                    score_weights,
                    combo_weights,
                )
                candidate_issue_results[profile_name][issue] = issue_result
                completed_tasks += 1
                _update_smart_progress(
                    "smart_candidates",
                    0.03 + (completed_tasks / max(1, total_tasks)) * 0.83,
                    f"正在生成智能候选 {completed_tasks}/{total_tasks}",
                    completed_tasks,
                    total_tasks,
                )
    else:
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="smart-backtest") as executor:
            future_map = {}
            for target_index, target, prior_history_desc, history_context in prepared_targets:
                for profile_name, candidate_strategy_mode, display_name, score_weights, combo_weights in candidate_profiles:
                    future = executor.submit(
                        evaluate_candidate,
                        target_index,
                        target,
                        prior_history_desc,
                        history_context,
                        profile_name,
                        candidate_strategy_mode,
                        display_name,
                        score_weights,
                        combo_weights,
                    )
                    future_map[future] = (profile_name, target.issue)
            for future in as_completed(future_map):
                if cancel_check:
                    cancel_check()
                profile_name, issue, issue_result = future.result()
                candidate_issue_results[profile_name][issue] = issue_result
                completed_tasks += 1
                _update_smart_progress(
                    "smart_candidates",
                    0.03 + (completed_tasks / max(1, total_tasks)) * 0.83,
                    f"正在生成智能候选 {completed_tasks}/{total_tasks}",
                    completed_tasks,
                    total_tasks,
                )

    _update_smart_progress(
        "smart_selecting",
        0.88,
        "正在按滚动窗口选择每期档位",
        0,
        len(prepared_targets),
    )
    profile_display = {profile_name: display_name for profile_name, _, display_name, *_ in candidate_profiles}
    fallback_profile = candidate_profiles[0][0]
    selected_issue_results: list[dict] = []
    selected_profile_counts: Counter[str] = Counter()
    prepared_issues = [target.issue for _, target, _, _ in prepared_targets]
    profile_score_prefixes: dict[str, list[float]] = {}
    for profile_name, *_ in candidate_profiles:
        running_total = 0.0
        score_prefix = [0.0]
        profile_issue_results = candidate_issue_results[profile_name]
        for issue in prepared_issues:
            running_total += _smart_balance_issue_score(profile_issue_results[issue])
            score_prefix.append(running_total)
        profile_score_prefixes[profile_name] = score_prefix
    for index, issue in enumerate(prepared_issues):
        if cancel_check:
            cancel_check()
        if index < warmup_window:
            chosen_profile = fallback_profile
            reason = (
                f"智能平衡需要至少 {warmup_window} 期滚动样本；"
                f"当前为预热期，使用{profile_display.get(chosen_profile, chosen_profile)}。"
            )
        else:
            attack_scores: dict[str, float] = {}
            guard_scores: dict[str, float] = {}
            for profile_name, *_ in candidate_profiles:
                score_prefix = profile_score_prefixes[profile_name]
                attack_scores[profile_name] = (
                    score_prefix[index] - score_prefix[index - SMART_BALANCE_WINDOW]
                ) / max(1, SMART_BALANCE_WINDOW)
                guard_scores[profile_name] = (
                    score_prefix[index] - score_prefix[index - SMART_BALANCE_GUARD_WINDOW]
                ) / max(1, SMART_BALANCE_GUARD_WINDOW)
            attack_profile = max(
                attack_scores,
                key=lambda name: (attack_scores[name], name == fallback_profile),
            )
            guard_profile = max(
                guard_scores,
                key=lambda name: (guard_scores[name], name == fallback_profile),
            )
            if attack_scores[attack_profile] >= guard_scores[guard_profile] + SMART_BALANCE_SWITCH_MARGIN:
                chosen_profile = attack_profile
                reason = (
                    f"智能平衡按短窗 {SMART_BALANCE_WINDOW} 期评分选择"
                    f"{profile_display.get(chosen_profile, chosen_profile)}；"
                    f"短窗 {attack_scores[chosen_profile]:.3f}，长窗最佳 {guard_scores[guard_profile]:.3f}。"
                )
            else:
                chosen_profile = guard_profile
                reason = (
                    f"智能平衡以长窗 {SMART_BALANCE_GUARD_WINDOW} 期保底选择"
                    f"{profile_display.get(chosen_profile, chosen_profile)}；"
                    f"长窗 {guard_scores[chosen_profile]:.3f}，短窗最佳 {attack_scores[attack_profile]:.3f}。"
                )
        selected_result = dict(candidate_issue_results[chosen_profile][issue])
        selected_result["count_policy"] = f"smart_balance_{SMART_BALANCE_WINDOW}_{SMART_BALANCE_GUARD_WINDOW}"
        selected_result["decision_tier"] = chosen_profile
        selected_result["decision_reason"] = reason
        if issue in target_issue_set:
            selected_profile_counts[chosen_profile] += 1
            selected_issue_results.append(selected_result)

    response = build_backtest_stats(selected_issue_results)  # type: ignore[arg-type]
    response.recent_issues = recent_issues
    response.requested_issues = recent_issues
    response.skipped_issues = 0
    response.confidence_threshold = 0.0
    response.scheme_count = scheme_count
    response.strategy_mode = SMART_BALANCE_MODE  # type: ignore[assignment]
    response.ticket_mode = ticket_mode  # type: ignore[assignment]
    response.ai_replay_mode = ai_replay_mode  # type: ignore[assignment]
    response.count_policy = f"smart_balance_{SMART_BALANCE_WINDOW}_{SMART_BALANCE_GUARD_WINDOW}"
    response.policy_selection_reason = (
        f"智能平衡每期只使用开奖前已知结果，先看近 {SMART_BALANCE_WINDOW} 期进攻评分，"
        f"再用近 {SMART_BALANCE_GUARD_WINDOW} 期长窗评分做保底校验，"
        "在多注覆盖参数档位与单注优先档位中选择候选。"
    )
    response.threshold_selection_reason = "智能平衡不按置信阈值删票，主结果保持每期固定全量方案组数。"
    response.max_drawdown = _max_drawdown(selected_issue_results)
    response.max_miss_streak = _max_miss_streak(selected_issue_results)
    response.theoretical_single_win_rate = round(_theoretical_single_win_rate(), 6)
    response.window_summaries = _build_window_summaries(selected_issue_results)
    response.benchmarks = []
    response.mode_comparison = []
    response.issue_comparison = []
    response.threshold_scan = []
    response.ai_engine = "Local Ensemble AI / Smart Balance"

    candidate_summaries: list[BacktestTuningCandidate] = []
    for profile_name, _, display_name, *_ in candidate_profiles:
        profile_issue_results = [
            candidate_issue_results[profile_name][issue]
            for issue in prepared_issues
            if issue in target_issue_set and issue in candidate_issue_results[profile_name]
        ]
        profile_stats = build_backtest_stats(profile_issue_results)  # type: ignore[arg-type]
        candidate_summaries.append(
            BacktestTuningCandidate(
                name=profile_name,
                display_name=display_name,
                score=_smart_balance_profile_summary_score(profile_stats),
                overall_win_rate=profile_stats.overall_win_rate,
                issue_hit_rate=profile_stats.issue_hit_rate,
                sample_issues=profile_stats.total_issues,
            )
        )
    counts_text = "；".join(
        f"{profile_display.get(profile_name, profile_name)} {count} 期"
        for profile_name, count in selected_profile_counts.most_common()
    )
    response.tuning_summary = BacktestTuningSummary(
        enabled=True,
        selected_profile=f"smart_balance_{SMART_BALANCE_WINDOW}_{SMART_BALANCE_GUARD_WINDOW}",
        selected_display_name=f"智能平衡滚动 {SMART_BALANCE_WINDOW}/{SMART_BALANCE_GUARD_WINDOW} 期",
        selected_reason="按开奖前短窗进攻评分与长窗保底评分逐期选择候选档位。",
        applied_profile=f"smart_balance_{SMART_BALANCE_WINDOW}_{SMART_BALANCE_GUARD_WINDOW}",
        applied_display_name=f"智能平衡滚动 {SMART_BALANCE_WINDOW}/{SMART_BALANCE_GUARD_WINDOW} 期",
        applied_reason=f"本次智能平衡档位分布：{counts_text}",
        sample_issues=min(warmup_window, response.total_issues),
        selection_basis="rolling_profile_selector",
        profiles=candidate_summaries,
        weights={
            "hit_weight": SMART_BALANCE_HIT_WEIGHT,
            "win_weight": SMART_BALANCE_WIN_WEIGHT,
            "amount_divisor": SMART_BALANCE_AMOUNT_DIVISOR,
            "level_weight_top3": SMART_BALANCE_PRIZE_LEVEL_SCORE_WEIGHTS["\u4e09\u7b49\u5956"],
            "level_weight_top4": SMART_BALANCE_PRIZE_LEVEL_SCORE_WEIGHTS["\u56db\u7b49\u5956"],
            "level_weight_top5": SMART_BALANCE_PRIZE_LEVEL_SCORE_WEIGHTS["\u4e94\u7b49\u5956"],
            "level_weight_top6": SMART_BALANCE_PRIZE_LEVEL_SCORE_WEIGHTS["\u516d\u7b49\u5956"],
            "level_weight_top7": SMART_BALANCE_PRIZE_LEVEL_SCORE_WEIGHTS["\u4e03\u7b49\u5956"],
            "window": float(SMART_BALANCE_WINDOW),
            "guard_window": float(SMART_BALANCE_GUARD_WINDOW),
            "switch_margin": SMART_BALANCE_SWITCH_MARGIN,
        },
    )
    _update_smart_progress(
        "finalizing",
        0.98,
        "正在汇总智能平衡结果",
        response.total_issues,
        response.total_issues,
    )
    return response


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
    guarded_baseline_profile = (
        THREE_PACK_FALLBACK_PROFILE
        if strategy_mode == "multi_cover" and 3 <= scheme_count < 5
        else HIGH_TIER_FALLBACK_PROFILE
    )
    guarded_candidate_enabled = strategy_mode == "multi_cover" and scheme_count >= 3
    guarded_overall_coarse_candidate = (
        _pick_guarded_overall_win_candidate(coarse_candidate_records, baseline_name=guarded_baseline_profile)
        if guarded_candidate_enabled
        else None
    )
    for extra_name in (
        guarded_baseline_profile,
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
        _pick_guarded_overall_win_candidate(train_candidate_records, baseline_name=guarded_baseline_profile)
        if guarded_candidate_enabled
        else None
    )
    guarded_train_candidate = (
        _pick_guarded_high_tier_candidate(train_candidate_records, baseline_name=guarded_baseline_profile)
        if guarded_candidate_enabled
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
            validation_issue_rows = _issue_rows_from_backtest_response(validation_stats)
            candidate.validation_max_drawdown = _max_drawdown(validation_issue_rows)
            candidate.validation_max_miss_streak = _max_miss_streak(validation_issue_rows)
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
        selected_validation_issue_rows = _issue_rows_from_backtest_response(best_validation[6])
        selected_validation_max_drawdown = _max_drawdown(selected_validation_issue_rows)
        selected_validation_max_miss_streak = _max_miss_streak(selected_validation_issue_rows)
        if runner_up_validation:
            runner_up_profile_name = runner_up_validation[2]
            runner_up_display_name = runner_up_validation[3]
            selection_margin = round(best_validation[0] - runner_up_validation[0], 4)
            selected_reason = f"按单次验证集分数选中，领先 {runner_up_display_name} {selection_margin:.4f}"
        else:
            selected_reason = "按单次验证集分数选中"

        if guarded_candidate_enabled:
            guarded_overall_validation_candidate = _pick_guarded_overall_win_candidate(
                validation_candidate_records,
                baseline_name=guarded_baseline_profile,
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
                    guarded_validation_issue_rows = _issue_rows_from_backtest_response(guarded_validation_stats)
                    selected_validation_max_drawdown = _max_drawdown(guarded_validation_issue_rows)
                    selected_validation_max_miss_streak = _max_miss_streak(guarded_validation_issue_rows)
                selection_basis = "guarded_overall_validation_split"
                selected_reason = "在低奖不回退约束下，验证集优先选择综合中奖率达到 10% 的方案"
                selection_margin = None
            guarded_validation_candidate = _pick_guarded_high_tier_candidate(
                validation_candidate_records,
                baseline_name=guarded_baseline_profile,
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
                    guarded_validation_issue_rows = _issue_rows_from_backtest_response(guarded_validation_stats)
                    selected_validation_max_drawdown = _max_drawdown(guarded_validation_issue_rows)
                    selected_validation_max_miss_streak = _max_miss_streak(guarded_validation_issue_rows)
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
            guarded_baseline_profile,
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
            if guarded_candidate_enabled:
                guarded_overall_walk_candidate = _pick_guarded_overall_win_candidate(
                    walk_forward_candidate_records,
                    baseline_name=guarded_baseline_profile,
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
                    baseline_name=guarded_baseline_profile,
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
    include_baselines: bool = True,
    skip_auto_tuning_search: bool = False,
    search_profile: str = "full",
    history_context_cache: dict[str, tuple[list, PrecomputedHistoryFeatures]] | None = None,
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
    issue_trials: list[dict] | None = [] if include_baselines else None
    raw_diag_path = os.environ.get("BACKTEST_RAW_DIAG_PATH")
    raw_diagnostic_rows: list[dict] | None = [] if raw_diag_path else None
    calibration_history: list[dict] = []
    ai_engine: str | None = None
    confidence_threshold = _backtest_confidence_threshold(strategy_mode, scheme_count)
    skipped_issues = 0
    dynamic_threshold_total = 0.0
    dynamic_threshold_count = 0
    calibrated_threshold_total = 0.0
    if history_context_cache is None:
        history_context_cache = _build_history_context_cache(history_asc, target_draws)
    if progress_callback:
        progress_callback(
            stage="tuning",
            progress=0.02,
            message="正在分析调参与权重",
            processed_issues=0,
            total_issues=len(target_draws),
        )
    if skip_auto_tuning_search and tuning_profile_override:
        tuning_summary = _override_only_tuning_summary(
            tuning_profile_override,
            sample_issues=max(0, len(target_draws)),
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
        )
    else:
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
        if history_context.history_size < BACKTEST_MIN_HISTORY_SIZE:
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
                    include_baselines=include_baselines,
                    search_profile=search_profile,
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
                    include_baselines=include_baselines,
                    search_profile=search_profile,
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
        selected_schemes = raw_selected_schemes
        scheme_evaluations = raw_scheme_evaluations
        evaluation_summary = _summarize_scheme_evaluations(scheme_evaluations)
        quality_signals = _issue_quality_signals_from_evaluations(scheme_evaluations)
        coverage_metrics = _scheme_coverage_metrics(selected_schemes)
        if issue_trials is not None:
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
                    "prefix_metrics": _build_scheme_prefix_metrics(raw_selected_schemes, raw_scheme_evaluations),
                }
            )
        if raw_diagnostic_rows is not None:
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
                    "front_candidates": _candidate_breakdown_json_rows(raw["front_candidates"]),
                    "back_candidates": _candidate_breakdown_json_rows(raw["back_candidates"]),
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
                "should_observe": False,
                "front_confidence": round(front_confidence, 4),
                "front_calibrated_confidence": front_calibrated_confidence,
                "front_gate": round(front_gate, 4),
                "back_confidence": round(back_confidence, 4),
                "back_calibrated_confidence": back_calibrated_confidence,
                "back_gate": round(back_gate, 4),
                "count_policy": "fixed_full_count",
                "decision_tier": "full_count",
                "deep_search_triggered": raw["deep_search_triggered"],
                "deep_search_reason": raw["deep_search_reason"],
                "decision_reason": (
                    "Backtest main result evaluates the full user-requested scheme count for every issue. "
                    f"Adaptive diagnostic policy suggestion: {decision_reason}"
                ),
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
        if include_baselines:
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

    if raw_diag_path and raw_diagnostic_rows is not None:
        with open(raw_diag_path, "w", encoding="utf-8") as file:
            json.dump(raw_diagnostic_rows, file, ensure_ascii=False, default=str)

    response = build_backtest_stats(issue_results)  # type: ignore[arg-type]
    response.threshold_scan = (
        _threshold_scan_results(
            issue_trials or [],
            strategy_mode=strategy_mode,
            max_scheme_count=scheme_count,
            ticket_mode=ticket_mode,
        )
        if include_baselines
        else []
    )
    default_threshold = round(
        (calibrated_threshold_total / dynamic_threshold_count) if dynamic_threshold_count else confidence_threshold,
        4,
    )
    applied_threshold = default_threshold
    applied_skipped_issues = 0
    current_policy_name = "fixed_full_count"
    policy_selection_reason = (
        "主回测结果按每期固定全量出号统计，与推演中心当前展示的可见方案组数保持一致。"
        "动态阈值、观望判断和分层出手策略仅保留在诊断字段与阈值扫描中，不再直接改变主回测的出票数。"
    )
    default_selection_score, _, _, default_max_drawdown, default_max_miss_streak, default_stability_breakdown = _selection_metrics_from_issue_results(
        issue_results,
        strategy_mode=strategy_mode,
        scheme_count=max(1, scheme_count),
    )
    threshold_selection_reason = (
        f"主回测按固定 {scheme_count} 组全量评估；阈值扫描仅作辅助参考。"
        f"当前主结果最大回撤 {default_max_drawdown:.2f}，最长空窗 {default_max_miss_streak} 期。"
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
    response_issue_rows = _issue_rows_from_backtest_response(response)
    response.max_drawdown = _max_drawdown(response_issue_rows)
    response.max_miss_streak = _max_miss_streak(response_issue_rows)
    response.theoretical_single_win_rate = round(_theoretical_single_win_rate(), 6)
    response.window_summaries = _build_window_summaries(response_issue_rows)
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
    if not include_baselines:
        response.benchmarks = []
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


def _scale_backtest_response(response: BacktestResponse, multiple: int) -> None:
    """Multiply all monetary fields by `multiple` in place.

    Hit counts, win rates and probabilities are NOT scaled, only money amounts.
    """
    if multiple <= 1:
        return
    factor = float(multiple)

    def _scale_amount(value):
        if value is None:
            return None
        return round(value * factor, 2)

    response.total_cost = _scale_amount(response.total_cost)
    response.total_prize_amount = _scale_amount(response.total_prize_amount) or 0.0
    response.net_profit = _scale_amount(response.net_profit)
    if response.max_drawdown is not None:
        response.max_drawdown = _scale_amount(response.max_drawdown)

    for item in response.issues:
        item.cost = _scale_amount(item.cost)
        item.best_prize_amount = _scale_amount(item.best_prize_amount)
        item.total_prize_amount = _scale_amount(item.total_prize_amount)
        if item.prize_level_amounts:
            item.prize_level_amounts = {
                level: _scale_amount(amount) or 0.0
                for level, amount in item.prize_level_amounts.items()
            }
        if getattr(item, "schemes", None):
            for scheme in item.schemes:
                if getattr(scheme, "prize_amount", None) is not None:
                    scheme.prize_amount = _scale_amount(scheme.prize_amount)

    for benchmark in (response.benchmarks or []):
        benchmark.total_cost = _scale_amount(benchmark.total_cost)
        benchmark.total_prize_amount = _scale_amount(benchmark.total_prize_amount)
        benchmark.net_profit = _scale_amount(benchmark.net_profit)

    for window in (response.window_summaries or []):
        window.total_cost = _scale_amount(window.total_cost)
        window.total_prize_amount = _scale_amount(window.total_prize_amount)
        window.net_profit = _scale_amount(window.net_profit)

    for breakdown in (response.prize_level_breakdown or []):
        breakdown.total_prize_amount = _scale_amount(breakdown.total_prize_amount) or 0.0
        breakdown.average_prize_amount = _scale_amount(breakdown.average_prize_amount) or 0.0

    for mode in (response.mode_comparison or []):
        mode.total_cost = _scale_amount(mode.total_cost)
        mode.total_prize_amount = _scale_amount(mode.total_prize_amount)
        mode.net_profit = _scale_amount(mode.net_profit)


def run_backtest(
    recent_issues: int = 30,
    scheme_count: int = 3,
    strategy_mode: str = "multi_cover",
    ticket_mode: str = "basic",
    ai_replay_mode: str = "local_only",
    compare_modes: bool = False,
    ai_config: AIConfigRequest | None = None,
    tuning_profile_override: str | None = None,
    multiple: int = 1,
    include_baselines: bool = True,
    include_applied_profile_comparison: bool = True,
    skip_auto_tuning_search: bool = False,
    search_profile: str = "full",
    history_context_cache: dict[str, tuple[list, PrecomputedHistoryFeatures]] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> BacktestResponse:
    history_asc = get_all_history_asc()
    if strategy_mode == SMART_BALANCE_MODE:
        response = _run_smart_balance_backtest_core(
            history_asc,
            recent_issues=recent_issues,
            scheme_count=scheme_count,
            ticket_mode=ticket_mode,
            ai_replay_mode=ai_replay_mode,
            ai_config=ai_config,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        _scale_backtest_response(response, multiple)
        return response
    response = _run_backtest_core(
        history_asc,
        recent_issues=recent_issues,
        scheme_count=scheme_count,
        strategy_mode=strategy_mode,
        ticket_mode=ticket_mode,
        ai_replay_mode=ai_replay_mode,
        ai_config=ai_config,
        tuning_profile_override=tuning_profile_override,
        include_baselines=include_baselines,
        skip_auto_tuning_search=skip_auto_tuning_search,
        search_profile=search_profile,
        history_context_cache=history_context_cache,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    if include_applied_profile_comparison and response.tuning_summary and response.tuning_summary.applied_is_override:
        auto_response = _run_backtest_core(
            history_asc,
            recent_issues=recent_issues,
            scheme_count=scheme_count,
            strategy_mode=strategy_mode,
            ticket_mode=ticket_mode,
            ai_replay_mode=ai_replay_mode,
            ai_config=ai_config,
            tuning_profile_override=None,
            include_baselines=include_baselines,
            skip_auto_tuning_search=skip_auto_tuning_search,
            search_profile=search_profile,
            history_context_cache=history_context_cache,
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
        _scale_backtest_response(response, multiple)
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
        include_baselines=include_baselines,
        skip_auto_tuning_search=skip_auto_tuning_search,
        search_profile=search_profile,
        history_context_cache=history_context_cache,
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
    _scale_backtest_response(response, multiple)
    return response
