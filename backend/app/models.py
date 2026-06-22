from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer, field_validator


class LottoDraw(BaseModel):
    issue: str = Field(..., description="Issue")
    draw_date: date = Field(..., description="Draw date")
    front_numbers: list[int] = Field(..., min_length=5, max_length=5)
    back_numbers: list[int] = Field(..., min_length=2, max_length=2)
    raw_result: str | None = None
    pool_balance_afterdraw: str | None = None
    prize_level_list: list["PrizeLevelItem"] = []


class PrizeLevelItem(BaseModel):
    prize_level: str
    award_type: int = 0
    stake_amount: str | None = None
    stake_amount_format: str | None = None
    stake_count: str | None = None
    total_prize_amount: str | None = None


class FrequencyItem(BaseModel):
    number: int
    count: int


class OmissionItem(BaseModel):
    number: int
    omission: int


class OddEvenStats(BaseModel):
    front_odd: int
    front_even: int
    back_odd: int
    back_even: int
    front_ratio: str
    back_ratio: str


class AnalyticsResponse(BaseModel):
    total_draws: int
    front_frequency: list[FrequencyItem]
    back_frequency: list[FrequencyItem]
    front_omission: list[OmissionItem]
    back_omission: list[OmissionItem]
    odd_even: OddEvenStats


class HexagramInfo(BaseModel):
    code: str
    name: str
    upper_trigram: str
    lower_trigram: str
    element: str
    lines: list[int]


class RecommendationNumber(BaseModel):
    number: int
    score: float
    reason: str


class CandidateBreakdown(BaseModel):
    number: int
    score: float
    tail: int
    tail_weight: float
    omission: int
    frequency: int
    recent_hits: int
    selected: bool


class TailWeightItem(BaseModel):
    tail: int
    weight: float


class ZoneSignal(BaseModel):
    zone: Literal["front", "back"]
    main_hexagram: HexagramInfo
    mutual_hexagram: HexagramInfo
    changed_hexagram: HexagramInfo
    active_elements: list[str]
    favored_tails: list[int]
    tail_weights: list[TailWeightItem]


class RecommendationSummary(BaseModel):
    front_sum: int
    back_sum: int
    front_span: int
    back_span: int
    front_odd_even: str
    back_odd_even: str
    favored_tails: list[int]
    explanation: str


class FinalScheme(BaseModel):
    label: str
    confidence: float
    strategy: str
    front_numbers: list[int]
    back_numbers: list[int]
    rationale: str


class AIAnalysis(BaseModel):
    engine: str
    overview: str
    key_factors: list[str]
    final_advice: str


class AIConfigRequest(BaseModel):
    enabled: bool = False
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    selected_models: list[str] = []
    system_prompt: str | None = None


class AIModelListRequest(BaseModel):
    base_url: str
    api_key: str


class AIModelItem(BaseModel):
    id: str
    owned_by: str | None = None


class AIModelListResponse(BaseModel):
    models: list[AIModelItem]


class DivinationRequest(BaseModel):
    issue: str | None = None
    timestamp: str | None = Field(None, description="ISO timestamp string; uses current system time if empty")
    scheme_count: int = Field(3, ge=1, le=50, description="How many schemes to return")
    strategy_mode: Literal["multi_cover", "single_hit", "smart_balance"] = "smart_balance"
    ai_config: AIConfigRequest | None = None


class DivinationResponse(BaseModel):
    seed_mode: Literal["issue", "timestamp", "system_time"]
    seed_value: str
    divination_datetime: str
    target_draw_datetime: str
    strategy_mode: Literal["multi_cover", "single_hit", "smart_balance"] = "smart_balance"
    moving_line: int
    main_hexagram: HexagramInfo
    mutual_hexagram: HexagramInfo
    changed_hexagram: HexagramInfo
    active_elements: list[str]
    favored_tails: list[int]
    tail_weights: list[TailWeightItem]
    front_recommendations: list[RecommendationNumber]
    back_recommendations: list[RecommendationNumber]
    front_candidates: list[CandidateBreakdown]
    back_candidates: list[CandidateBreakdown]
    front_signal: ZoneSignal
    back_signal: ZoneSignal
    summary: RecommendationSummary
    ai_analysis: AIAnalysis
    final_schemes: list[FinalScheme]
    tuning_profile: str | None = None
    issue_confidence: float | None = None
    calibrated_confidence: float | None = None
    applied_threshold: float | None = None
    should_observe: bool = False
    front_confidence: float | None = None
    front_calibrated_confidence: float | None = None
    front_gate: float | None = None
    back_confidence: float | None = None
    back_calibrated_confidence: float | None = None
    back_gate: float | None = None
    count_policy: str | None = None
    decision_tier: str | None = None
    deep_search_triggered: bool = False
    deep_search_reason: str | None = None
    decision_reason: str | None = None


class FullHistoryCacheRebuildJob(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: float = 0.0
    message: str | None = None
    scheme_count: int
    ticket_mode: Literal["basic", "additional"] = "basic"
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class FullHistoryCacheProfileStatus(BaseModel):
    profile: str
    mode: Literal["multi_cover", "single_hit", "smart_balance"] | str
    file_name: str | None = None
    exists: bool = False
    valid: bool = False
    issue_count: int = 0
    latest_issue: str | None = None
    generated_at: str | None = None
    reason: str | None = None


class FullHistoryCacheStatus(BaseModel):
    algorithm_version: str
    latest_issue: str | None = None
    total_draws: int = 0
    expected_issue_count: int = 0
    scheme_count: int
    ticket_mode: Literal["basic", "additional"] = "basic"
    valid: bool = False
    stale_reasons: list[str] = []
    generated_at: str | None = None
    invalidated_at: str | None = None
    profiles: list[FullHistoryCacheProfileStatus] = []
    active_job: FullHistoryCacheRebuildJob | None = None


class SyncResult(BaseModel):
    source: str
    fetched_pages: int
    inserted: int
    updated: int
    total_in_db: int
    latest_issue: str | None
    synced_at: datetime


class SyncStatus(BaseModel):
    total_draws: int
    latest_issue: str | None
    latest_draw_date: date | None
    next_issue: str | None = None
    next_draw_datetime: datetime | None = None
    last_synced_at: datetime | None
    source: str

    @field_serializer("next_draw_datetime")
    def _serialize_next_draw_datetime(self, value: datetime | None) -> str | None:
        return value.isoformat(timespec="minutes") if value else None


class SavedSchemeCreateRequest(BaseModel):
    target_issue: str
    seed_mode: Literal["issue", "timestamp", "system_time"]
    seed_value: str
    moving_line: int
    ai_engine: str
    scheme: FinalScheme
    tuning_profile: str | None = None
    issue_confidence: float | None = None
    calibrated_confidence: float | None = None
    applied_threshold: float | None = None
    should_observe: bool = False
    front_confidence: float | None = None
    front_gate: float | None = None
    back_confidence: float | None = None
    back_gate: float | None = None
    deep_search_triggered: bool = False
    deep_search_reason: str | None = None
    decision_reason: str | None = None
    multiple: int = Field(1, ge=1, le=99, description="\u6295\u6ce8\u500d\u6570")
    is_additional: bool = False


class SavedSchemeBatchCreateRequest(BaseModel):
    items: list[SavedSchemeCreateRequest] = Field(..., min_length=1, max_length=50)


class SavedSchemeManualCreateRequest(BaseModel):
    target_issue: str = Field(..., description="\u76ee\u6807\u671f\u53f7")
    front_numbers: list[int] = Field(..., min_length=5, max_length=5)
    back_numbers: list[int] = Field(..., min_length=2, max_length=2)
    label: str | None = Field(None, description="\u5907\u6ce8\u540d\u79f0")
    note: str | None = None
    multiple: int = Field(1, ge=1, le=99, description="\u6295\u6ce8\u500d\u6570")
    is_additional: bool = False

    @field_validator("front_numbers")
    @classmethod
    def _validate_front(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("\u524d\u533a\u53f7\u7801\u4e0d\u53ef\u91cd\u590d")
        for number in value:
            if not 1 <= number <= 35:
                raise ValueError("\u524d\u533a\u53f7\u7801\u8303\u56f4\u4e3a 1-35")
        return sorted(value)

    @field_validator("back_numbers")
    @classmethod
    def _validate_back(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("\u540e\u533a\u53f7\u7801\u4e0d\u53ef\u91cd\u590d")
        for number in value:
            if not 1 <= number <= 12:
                raise ValueError("\u540e\u533a\u53f7\u7801\u8303\u56f4\u4e3a 1-12")
        return sorted(value)


class ManualDrawResultUpsertRequest(BaseModel):
    draw_date: date | None = Field(None, description="\u5f00\u5956\u65e5\u671f\uff0c\u53ef\u9009")
    front_numbers: list[int] = Field(..., min_length=5, max_length=5)
    back_numbers: list[int] = Field(..., min_length=2, max_length=2)
    high_pool: bool = Field(False, description="\u5956\u6c60\u662f\u5426\u4e0d\u4f4e\u4e8e 8 \u4ebf\uff08\u7528\u4e8e\u56fa\u5b9a\u5956\u91d1\u6321\u4f4d\uff09")

    @field_validator("front_numbers")
    @classmethod
    def _validate_front(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("\u524d\u533a\u53f7\u7801\u4e0d\u53ef\u91cd\u590d")
        for number in value:
            if not 1 <= number <= 35:
                raise ValueError("\u524d\u533a\u53f7\u7801\u8303\u56f4\u4e3a 1-35")
        return sorted(value)

    @field_validator("back_numbers")
    @classmethod
    def _validate_back(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("\u540e\u533a\u53f7\u7801\u4e0d\u53ef\u91cd\u590d")
        for number in value:
            if not 1 <= number <= 12:
                raise ValueError("\u540e\u533a\u53f7\u7801\u8303\u56f4\u4e3a 1-12")
        return sorted(value)


class ManualDrawResult(BaseModel):
    issue: str
    draw_date: date | None = None
    front_numbers: list[int]
    back_numbers: list[int]
    high_pool: bool = False
    created_at: datetime
    updated_at: datetime


class PrizeEvaluation(BaseModel):
    status: Literal["pending", "won", "not_won"]
    result_source: Literal["none", "official", "manual"] = "none"
    multiple: int = 1
    is_additional: bool = False
    cost_amount: float = 0.0
    front_match_count: int = 0
    back_match_count: int = 0
    prize_level: str | None = None
    base_prize_amount: float | None = None
    additional_prize_amount: float | None = None
    bonus_prize_amount: float | None = None
    prize_amount: float | None = None
    prize_amount_text: str | None = None
    promotion_active: bool = False
    promotion_eligible: bool = False
    promotion_label: str | None = None
    promotion_min_ticket_amount: float | None = None
    draw_issue: str | None = None
    draw_date: date | None = None
    winning_front_numbers: list[int] = []
    winning_back_numbers: list[int] = []
    evaluated_at: datetime | None = None


class SavedScheme(BaseModel):
    id: int
    target_issue: str
    seed_mode: Literal["issue", "timestamp", "system_time"]
    seed_value: str
    moving_line: int
    ai_engine: str
    label: str
    confidence: float
    strategy: str
    front_numbers: list[int]
    back_numbers: list[int]
    rationale: str
    tuning_profile: str | None = None
    issue_confidence: float | None = None
    calibrated_confidence: float | None = None
    applied_threshold: float | None = None
    should_observe: bool = False
    front_confidence: float | None = None
    front_gate: float | None = None
    back_confidence: float | None = None
    back_gate: float | None = None
    deep_search_triggered: bool = False
    deep_search_reason: str | None = None
    decision_reason: str | None = None
    multiple: int = 1
    is_additional: bool = False
    created_at: datetime
    updated_at: datetime
    evaluation: PrizeEvaluation


class PrizeRateItem(BaseModel):
    level: str
    wins: int
    rate: float


class BacktestPrizeLevelSummary(BaseModel):
    level: str
    wins: int = 0
    scheme_rate: float = 0.0
    issue_hits: int = 0
    issue_rate: float = 0.0
    total_prize_amount: float = 0.0
    average_prize_amount: float = 0.0


class SavedSchemeModeStats(BaseModel):
    total_saved: int
    evaluated_count: int
    won_count: int
    total_cost: float
    total_prize_amount: float
    overall_win_rate: float
    roi: float


class SavedSchemeStats(BaseModel):
    total_saved: int
    evaluated_count: int
    pending_count: int
    won_count: int
    total_cost: float
    total_prize_amount: float
    overall_win_rate: float
    roi: float
    basic: SavedSchemeModeStats
    additional: SavedSchemeModeStats
    prize_rates: list[PrizeRateItem]


class SavedSchemeListResponse(BaseModel):
    items: list[SavedScheme]
    stats: SavedSchemeStats


class DivinationRunScheme(BaseModel):
    id: int
    run_id: int
    scheme_index: int
    label: str
    confidence: float
    strategy: str
    front_numbers: list[int]
    back_numbers: list[int]
    rationale: str
    evaluation: PrizeEvaluation


class DivinationRun(BaseModel):
    id: int
    target_issue: str | None = None
    seed_mode: Literal["issue", "timestamp", "system_time"]
    seed_value: str
    divination_datetime: str
    target_draw_datetime: str
    requested_scheme_count: int
    visible_scheme_count: int
    requested_strategy_mode: Literal["multi_cover", "single_hit", "smart_balance"]
    effective_strategy_mode: Literal["multi_cover", "single_hit", "smart_balance"]
    moving_line: int
    ai_engine: str
    ai_enabled: bool = False
    tuning_profile: str | None = None
    issue_confidence: float | None = None
    calibrated_confidence: float | None = None
    applied_threshold: float | None = None
    should_observe: bool = False
    front_confidence: float | None = None
    front_calibrated_confidence: float | None = None
    front_gate: float | None = None
    back_confidence: float | None = None
    back_calibrated_confidence: float | None = None
    back_gate: float | None = None
    count_policy: str | None = None
    decision_tier: str | None = None
    deep_search_triggered: bool = False
    deep_search_reason: str | None = None
    decision_reason: str | None = None
    summary_explanation: str | None = None
    created_at: datetime
    schemes: list[DivinationRunScheme]


class DivinationRunStats(BaseModel):
    total_runs: int
    evaluated_runs: int
    pending_runs: int
    hit_issue_count: int
    total_scheme_count: int
    evaluated_scheme_count: int
    won_scheme_count: int
    scheme_win_rate: float
    issue_hit_rate: float


class DivinationRunListResponse(BaseModel):
    items: list[DivinationRun]
    stats: DivinationRunStats


class BacktestRequest(BaseModel):
    recent_issues: int = Field(30, ge=5)
    scheme_count: int = Field(3, ge=1)
    multiple: int = Field(1, ge=1, le=99)
    strategy_mode: Literal["multi_cover", "single_hit", "smart_balance"] = "multi_cover"
    ticket_mode: Literal["basic", "additional"] = "basic"
    ai_replay_mode: Literal["local_only", "external_rerank"] = "local_only"
    compare_modes: bool = False
    tuning_profile_override: str | None = None
    ai_config: AIConfigRequest | None = None


class BacktestIssueResult(BaseModel):
    issue: str
    draw_date: date
    scheme_count: int
    ticket_mode: Literal["basic", "additional"] = "basic"
    tuning_profile: str | None = None
    issue_confidence: float = 0.0
    calibrated_confidence: float = 0.0
    applied_threshold: float = 0.0
    should_observe: bool = False
    front_confidence: float | None = None
    front_calibrated_confidence: float | None = None
    front_gate: float | None = None
    back_confidence: float | None = None
    back_calibrated_confidence: float | None = None
    back_gate: float | None = None
    count_policy: str | None = None
    decision_tier: str | None = None
    deep_search_triggered: bool = False
    deep_search_reason: str | None = None
    decision_reason: str | None = None
    won_count: int
    best_prize_level: str | None = None
    best_prize_amount: float | None = None
    total_prize_amount: float = 0.0
    winning_scheme_labels: list[str] = []
    prize_level_hits: dict[str, int] = Field(default_factory=dict)
    prize_level_amounts: dict[str, float] = Field(default_factory=dict)
    top3_hit: bool = False
    top4_hit: bool = False
    front_4plus_hit: bool = False
    front_5_hit: bool = False
    five_plus_zero_hit: bool = False
    five_plus_one_hit: bool = False
    five_plus_two_hit: bool = False
    four_plus_two_hit: bool = False
    back_2plus_hit: bool = False
    front_best_match_count: int = 0
    back_best_match_count: int = 0
    issue_power_score: float = 0.0
    cost: float = 0.0
    front_pairwise_overlap_avg: float = 0.0
    back_pairwise_overlap_avg: float = 0.0
    back_pair_reuse_rate: float = 0.0
    fresh_back_number_rate: float = 0.0


class BacktestCoverageMetrics(BaseModel):
    front_pairwise_overlap_avg: float = 0.0
    back_pairwise_overlap_avg: float = 0.0
    back_pair_reuse_rate: float = 0.0
    fresh_back_number_rate: float = 0.0


class BacktestCoverageScoreComponents(BaseModel):
    front_diversity: float = 0.0
    back_diversity: float = 0.0
    back_pair_diversity: float = 0.0
    fresh_back: float = 0.0


class BacktestStabilityBreakdown(BaseModel):
    base_score: float = 0.0
    adjusted_score: float = 0.0
    range_penalty: float = 0.0
    drawdown_penalty: float = 0.0
    miss_streak_penalty: float = 0.0


class BacktestBenchmark(BaseModel):
    name: str
    display_name: str
    sample_runs: int = 1
    total_issues: int
    total_generated_schemes: int
    won_schemes: int
    total_prize_amount: float
    total_cost: float = 0.0
    net_profit: float = 0.0
    overall_win_rate: float
    issue_hit_rate: float
    prize_rates: list[PrizeRateItem]


class BacktestWindowSummary(BaseModel):
    label: str
    total_issues: int
    won_schemes: int
    total_prize_amount: float
    total_cost: float = 0.0
    net_profit: float = 0.0
    overall_win_rate: float
    issue_hit_rate: float
    max_drawdown: float = 0.0
    max_miss_streak: int = 0


class BacktestTuningCandidate(BaseModel):
    name: str
    display_name: str
    score: float
    performance_score: float | None = None
    coverage_score: float | None = None
    coverage_components: BacktestCoverageScoreComponents | None = None
    overall_win_rate: float
    issue_hit_rate: float
    sample_issues: int
    validation_score: float | None = None
    validation_performance_score: float | None = None
    validation_coverage_score: float | None = None
    validation_coverage_components: BacktestCoverageScoreComponents | None = None
    validation_overall_win_rate: float | None = None
    validation_issue_hit_rate: float | None = None
    validation_stability_adjusted_score: float | None = None
    validation_stability_breakdown: BacktestStabilityBreakdown | None = None
    validation_max_drawdown: float | None = None
    validation_max_miss_streak: int | None = None
    walk_forward_score: float | None = None
    walk_forward_stability_adjusted_score: float | None = None
    walk_forward_stability_breakdown: BacktestStabilityBreakdown | None = None
    walk_forward_performance_score: float | None = None
    walk_forward_coverage_score: float | None = None
    walk_forward_coverage_components: BacktestCoverageScoreComponents | None = None
    walk_forward_overall_win_rate: float | None = None
    walk_forward_issue_hit_rate: float | None = None
    walk_forward_windows: int = 0
    walk_forward_stability: str | None = None
    walk_forward_score_range: float | None = None
    walk_forward_max_drawdown: float | None = None
    walk_forward_max_miss_streak: int | None = None


class BacktestWalkForwardWindow(BaseModel):
    label: str
    train_start_issue: str
    train_end_issue: str
    test_start_issue: str
    test_end_issue: str
    test_issues: int
    score: float
    overall_win_rate: float
    issue_hit_rate: float


class BacktestTuningWalkForwardDetail(BaseModel):
    name: str
    display_name: str
    stability: str | None = None
    score_range: float | None = None
    windows: list[BacktestWalkForwardWindow] = []


class BacktestTuningIssueSide(BaseModel):
    profile_name: str
    display_name: str
    won_count: int
    best_prize_level: str | None = None
    best_prize_amount: float | None = None
    cost: float = 0.0


class BacktestTuningIssueComparison(BaseModel):
    issue: str
    draw_date: date
    applied: BacktestTuningIssueSide
    selected: BacktestTuningIssueSide
    won_count_delta: int = 0
    prize_amount_delta: float = 0.0


class BacktestTuningSummary(BaseModel):
    enabled: bool = False
    selected_profile: str | None = None
    selected_display_name: str | None = None
    selected_reason: str | None = None
    applied_profile: str | None = None
    applied_display_name: str | None = None
    applied_reason: str | None = None
    applied_is_override: bool = False
    applied_total_prize_delta: float | None = None
    applied_issue_hit_rate_delta: float | None = None
    applied_roi_delta: float | None = None
    applied_delta_summary: str | None = None
    applied_issue_comparison: list[BacktestTuningIssueComparison] = []
    selection_warning: str | None = None
    compare_profile: str | None = None
    compare_display_name: str | None = None
    compare_reason: str | None = None
    runner_up_display_name: str | None = None
    selection_margin: float | None = None
    sample_issues: int = 0
    training_sample_issues: int = 0
    validation_sample_issues: int = 0
    selection_basis: str = "train_only"
    validation_score: float | None = None
    validation_overall_win_rate: float | None = None
    validation_issue_hit_rate: float | None = None
    validation_stability_adjusted_score: float | None = None
    validation_stability_breakdown: BacktestStabilityBreakdown | None = None
    validation_max_drawdown: float | None = None
    validation_max_miss_streak: int | None = None
    walk_forward_window_count: int = 0
    walk_forward_score: float | None = None
    walk_forward_stability_adjusted_score: float | None = None
    walk_forward_stability_breakdown: BacktestStabilityBreakdown | None = None
    walk_forward_overall_win_rate: float | None = None
    walk_forward_issue_hit_rate: float | None = None
    walk_forward_stability: str | None = None
    walk_forward_score_range: float | None = None
    walk_forward_max_drawdown: float | None = None
    walk_forward_max_miss_streak: int | None = None
    walk_forward_details: list[BacktestTuningWalkForwardDetail] = []
    profiles: list[BacktestTuningCandidate] = []
    weights: dict[str, float] = {}


class BacktestModeSummary(BaseModel):
    strategy_mode: Literal["multi_cover", "single_hit", "smart_balance"]
    total_issues: int
    total_generated_schemes: int
    won_schemes: int
    total_prize_amount: float
    total_cost: float = 0.0
    net_profit: float = 0.0
    overall_win_rate: float
    issue_hit_rate: float
    ai_engine: str | None = None
    coverage_metrics: BacktestCoverageMetrics = BacktestCoverageMetrics()


class BacktestThresholdScanItem(BaseModel):
    threshold: float
    total_issues: int
    skipped_issues: int = 0
    total_generated_schemes: int
    won_schemes: int
    total_cost: float = 0.0
    total_prize_amount: float = 0.0
    net_profit: float = 0.0
    overall_win_rate: float
    issue_hit_rate: float
    avg_scheme_count: float = 0.0
    selection_score: float | None = None
    stability_breakdown: BacktestStabilityBreakdown | None = None
    stability: str | None = None
    score_range: float | None = None
    max_drawdown: float | None = None
    max_miss_streak: int | None = None


class BacktestIssueModeComparison(BaseModel):
    strategy_mode: Literal["multi_cover", "single_hit", "smart_balance"]
    won_count: int
    best_prize_level: str | None = None
    best_prize_amount: float | None = None
    cost: float = 0.0


class BacktestIssueComparison(BaseModel):
    issue: str
    draw_date: date
    primary: BacktestIssueModeComparison
    secondary: BacktestIssueModeComparison
    won_count_delta: int = 0
    prize_amount_delta: float = 0.0


class BacktestResponse(BaseModel):
    recent_issues: int
    requested_issues: int = 0
    skipped_issues: int = 0
    confidence_threshold: float = 0.0
    scheme_count: int
    strategy_mode: Literal["multi_cover", "single_hit", "smart_balance"] = "multi_cover"
    ticket_mode: Literal["basic", "additional"] = "basic"
    ai_replay_mode: Literal["local_only", "external_rerank"] = "local_only"
    count_policy: str | None = None
    threshold_selection_reason: str | None = None
    policy_selection_reason: str | None = None
    stability_breakdown: BacktestStabilityBreakdown | None = None
    max_drawdown: float = 0.0
    max_miss_streak: int = 0
    total_issues: int
    total_generated_schemes: int
    won_schemes: int
    total_prize_amount: float
    total_cost: float = 0.0
    net_profit: float = 0.0
    overall_win_rate: float
    issue_hit_rate: float
    prize_rates: list[PrizeRateItem]
    prize_level_breakdown: list[BacktestPrizeLevelSummary] = []
    issues: list[BacktestIssueResult]
    coverage_metrics: BacktestCoverageMetrics = BacktestCoverageMetrics()
    ai_engine: str | None = None
    theoretical_single_win_rate: float = 0.0
    benchmarks: list[BacktestBenchmark] = []
    window_summaries: list[BacktestWindowSummary] = []
    tuning_summary: BacktestTuningSummary | None = None
    mode_comparison: list[BacktestModeSummary] = []
    issue_comparison: list[BacktestIssueComparison] = []
    threshold_scan: list[BacktestThresholdScanItem] = []


class BacktestJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed", "canceled", "canceling"]
    stage: str = "queued"
    message: str | None = None
    progress: float = 0.0
    processed_issues: int = 0
    total_issues: int = 0
    scheme_count: int = 0
    strategy_mode: Literal["multi_cover", "single_hit", "smart_balance"] = "multi_cover"
    ticket_mode: Literal["basic", "additional"] = "basic"
    ai_replay_mode: Literal["local_only", "external_rerank"] = "local_only"
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: BacktestResponse | None = None


class BacktestJobListResponse(BaseModel):
    items: list[BacktestJobResponse]
