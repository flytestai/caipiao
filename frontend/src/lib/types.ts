export interface LottoDraw {
  issue: string;
  draw_date: string;
  front_numbers: number[];
  back_numbers: number[];
  raw_result?: string | null;
  pool_balance_afterdraw?: string | null;
}

export interface RecommendationNumber {
  number: number;
  score: number;
  reason: string;
}

export interface CandidateBreakdown {
  number: number;
  score: number;
  tail: number;
  tail_weight: number;
  omission: number;
  frequency: number;
  recent_hits: number;
  selected: boolean;
}

export interface TailWeightItem {
  tail: number;
  weight: number;
}

export interface Hexagram {
  code: string;
  name: string;
  upper_trigram: string;
  lower_trigram: string;
  element: string;
  lines: number[];
}

export interface RecommendationSummary {
  front_sum: number;
  back_sum: number;
  front_span: number;
  back_span: number;
  front_odd_even: string;
  back_odd_even: string;
  favored_tails: number[];
  explanation: string;
}

export interface ZoneSignal {
  zone: "front" | "back";
  main_hexagram: Hexagram;
  mutual_hexagram: Hexagram;
  changed_hexagram: Hexagram;
  active_elements: string[];
  favored_tails: number[];
  tail_weights: TailWeightItem[];
}

export interface FinalScheme {
  label: string;
  confidence: number;
  strategy: string;
  front_numbers: number[];
  back_numbers: number[];
  rationale: string;
}

export type StrategyMode = "smart_balance" | "multi_cover" | "single_hit";
export type BacktestStrategyMode = StrategyMode;
export type TicketMode = "basic" | "additional";
export type AIReplayMode = "local_only" | "external_rerank";

export interface AIAnalysis {
  engine: string;
  overview: string;
  key_factors: string[];
  final_advice: string;
}

export interface AIConfig {
  enabled: boolean;
  baseUrl: string;
  apiKey: string;
  model: string;
  selectedModels: string[];
  systemPrompt: string;
}

export interface AIModelItem {
  id: string;
  owned_by?: string | null;
}

export interface DivinationResponse {
  seed_mode: "issue" | "timestamp" | "system_time";
  seed_value: string;
  divination_datetime: string;
  target_draw_datetime: string;
  strategy_mode: StrategyMode;
  moving_line: number;
  active_elements: string[];
  favored_tails: number[];
  tail_weights: TailWeightItem[];
  main_hexagram: Hexagram;
  mutual_hexagram: Hexagram;
  changed_hexagram: Hexagram;
  front_recommendations: RecommendationNumber[];
  back_recommendations: RecommendationNumber[];
  front_candidates: CandidateBreakdown[];
  back_candidates: CandidateBreakdown[];
  front_signal?: ZoneSignal;
  back_signal?: ZoneSignal;
  summary: RecommendationSummary;
  ai_analysis: AIAnalysis;
  final_schemes: FinalScheme[];
  tuning_profile?: string | null;
  issue_confidence?: number | null;
  calibrated_confidence?: number | null;
  applied_threshold?: number | null;
  should_observe?: boolean;
  front_confidence?: number | null;
  front_calibrated_confidence?: number | null;
  front_gate?: number | null;
  back_confidence?: number | null;
  back_calibrated_confidence?: number | null;
  back_gate?: number | null;
  count_policy?: string | null;
  decision_tier?: string | null;
  deep_search_triggered?: boolean;
  deep_search_reason?: string | null;
  decision_reason?: string | null;
}

export interface SyncStatus {
  total_draws: number;
  latest_issue: string | null;
  latest_draw_date: string | null;
  next_issue: string | null;
  next_draw_datetime: string | null;
  last_synced_at: string | null;
  source: string;
}

export interface FullHistoryCacheRebuildJob {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  message?: string | null;
  scheme_count: number;
  ticket_mode: TicketMode;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
}

export interface FullHistoryCacheProfileStatus {
  profile: string;
  mode: StrategyMode | string;
  file_name?: string | null;
  exists: boolean;
  valid: boolean;
  issue_count: number;
  latest_issue?: string | null;
  generated_at?: string | null;
  reason?: string | null;
}

export interface FullHistoryCacheStatus {
  algorithm_version: string;
  latest_issue?: string | null;
  total_draws: number;
  expected_issue_count: number;
  scheme_count: number;
  ticket_mode: TicketMode;
  valid: boolean;
  stale_reasons: string[];
  generated_at?: string | null;
  invalidated_at?: string | null;
  profiles: FullHistoryCacheProfileStatus[];
  active_job?: FullHistoryCacheRebuildJob | null;
}

export interface PrizeEvaluation {
  status: "pending" | "won" | "not_won";
  result_source: "none" | "official" | "manual";
  multiple: number;
  is_additional: boolean;
  cost_amount: number;
  front_match_count: number;
  back_match_count: number;
  prize_level?: string | null;
  base_prize_amount?: number | null;
  additional_prize_amount?: number | null;
  bonus_prize_amount?: number | null;
  prize_amount?: number | null;
  prize_amount_text?: string | null;
  promotion_active: boolean;
  promotion_eligible: boolean;
  promotion_label?: string | null;
  promotion_min_ticket_amount?: number | null;
  draw_issue?: string | null;
  draw_date?: string | null;
  winning_front_numbers: number[];
  winning_back_numbers: number[];
  evaluated_at?: string | null;
}

export interface ManualDrawResult {
  issue: string;
  draw_date?: string | null;
  front_numbers: number[];
  back_numbers: number[];
  high_pool: boolean;
  created_at: string;
  updated_at: string;
}

export interface SavedScheme {
  id: number;
  target_issue: string;
  seed_mode: "issue" | "timestamp" | "system_time";
  seed_value: string;
  moving_line: number;
  ai_engine: string;
  label: string;
  confidence: number;
  strategy: string;
  front_numbers: number[];
  back_numbers: number[];
  rationale: string;
  tuning_profile?: string | null;
  issue_confidence?: number | null;
  calibrated_confidence?: number | null;
  applied_threshold?: number | null;
  should_observe?: boolean;
  front_confidence?: number | null;
  front_gate?: number | null;
  back_confidence?: number | null;
  back_gate?: number | null;
  deep_search_triggered?: boolean;
  deep_search_reason?: string | null;
  decision_reason?: string | null;
  multiple: number;
  is_additional: boolean;
  created_at: string;
  updated_at: string;
  evaluation: PrizeEvaluation;
}

export interface PrizeRateItem {
  level: string;
  wins: number;
  rate: number;
}

export interface BacktestPrizeLevelSummary {
  level: string;
  wins: number;
  scheme_rate: number;
  issue_hits: number;
  issue_rate: number;
  total_prize_amount: number;
  average_prize_amount: number;
}

export interface SavedSchemeModeStats {
  total_saved: number;
  evaluated_count: number;
  won_count: number;
  total_cost: number;
  total_prize_amount: number;
  overall_win_rate: number;
  roi: number;
}

export interface SavedSchemeStats {
  total_saved: number;
  evaluated_count: number;
  pending_count: number;
  won_count: number;
  total_cost: number;
  total_prize_amount: number;
  overall_win_rate: number;
  roi: number;
  basic: SavedSchemeModeStats;
  additional: SavedSchemeModeStats;
  prize_rates: PrizeRateItem[];
}

export interface SavedSchemeListResponse {
  items: SavedScheme[];
  stats: SavedSchemeStats;
}

export interface DivinationRunScheme {
  id: number;
  run_id: number;
  scheme_index: number;
  label: string;
  confidence: number;
  strategy: string;
  front_numbers: number[];
  back_numbers: number[];
  rationale: string;
  evaluation: PrizeEvaluation;
}

export interface DivinationRun {
  id: number;
  target_issue?: string | null;
  seed_mode: "issue" | "timestamp" | "system_time";
  seed_value: string;
  divination_datetime: string;
  target_draw_datetime: string;
  requested_scheme_count: number;
  visible_scheme_count: number;
  requested_strategy_mode: StrategyMode;
  effective_strategy_mode: StrategyMode;
  moving_line: number;
  ai_engine: string;
  ai_enabled: boolean;
  tuning_profile?: string | null;
  issue_confidence?: number | null;
  calibrated_confidence?: number | null;
  applied_threshold?: number | null;
  should_observe?: boolean;
  front_confidence?: number | null;
  front_calibrated_confidence?: number | null;
  front_gate?: number | null;
  back_confidence?: number | null;
  back_calibrated_confidence?: number | null;
  back_gate?: number | null;
  count_policy?: string | null;
  decision_tier?: string | null;
  deep_search_triggered?: boolean;
  deep_search_reason?: string | null;
  decision_reason?: string | null;
  summary_explanation?: string | null;
  created_at: string;
  schemes: DivinationRunScheme[];
}

export interface DivinationRunStats {
  total_runs: number;
  evaluated_runs: number;
  pending_runs: number;
  hit_issue_count: number;
  total_scheme_count: number;
  evaluated_scheme_count: number;
  won_scheme_count: number;
  scheme_win_rate: number;
  issue_hit_rate: number;
}

export interface DivinationRunListResponse {
  items: DivinationRun[];
  stats: DivinationRunStats;
}

export interface BacktestIssueResult {
  issue: string;
  draw_date: string;
  scheme_count: number;
  ticket_mode?: TicketMode;
  tuning_profile?: string | null;
  issue_confidence?: number;
  calibrated_confidence?: number;
  applied_threshold?: number;
  should_observe?: boolean;
  front_confidence?: number | null;
  front_calibrated_confidence?: number | null;
  front_gate?: number | null;
  back_confidence?: number | null;
  back_calibrated_confidence?: number | null;
  back_gate?: number | null;
  count_policy?: string | null;
  decision_tier?: string | null;
  deep_search_triggered?: boolean;
  deep_search_reason?: string | null;
  decision_reason?: string | null;
  won_count: number;
  best_prize_level?: string | null;
  best_prize_amount?: number | null;
  total_prize_amount?: number;
  winning_scheme_labels: string[];
  prize_level_hits?: Record<string, number>;
  prize_level_amounts?: Record<string, number>;
  cost?: number;
  front_pairwise_overlap_avg?: number;
  back_pairwise_overlap_avg?: number;
  back_pair_reuse_rate?: number;
  fresh_back_number_rate?: number;
}

export interface BacktestCoverageMetrics {
  front_pairwise_overlap_avg: number;
  back_pairwise_overlap_avg: number;
  back_pair_reuse_rate: number;
  fresh_back_number_rate: number;
}

export interface BacktestCoverageScoreComponents {
  front_diversity: number;
  back_diversity: number;
  back_pair_diversity: number;
  fresh_back: number;
}

export interface BacktestStabilityBreakdown {
  base_score: number;
  adjusted_score: number;
  range_penalty: number;
  drawdown_penalty: number;
  miss_streak_penalty: number;
}

export interface BacktestBenchmark {
  name: string;
  display_name: string;
  sample_runs?: number;
  total_issues: number;
  total_generated_schemes: number;
  won_schemes: number;
  total_prize_amount: number;
  total_cost?: number;
  net_profit?: number;
  overall_win_rate: number;
  issue_hit_rate: number;
  prize_rates: PrizeRateItem[];
}

export interface BacktestWindowSummary {
  label: string;
  total_issues: number;
  won_schemes: number;
  total_prize_amount: number;
  total_cost?: number;
  net_profit?: number;
  overall_win_rate: number;
  issue_hit_rate: number;
  max_drawdown?: number;
  max_miss_streak?: number;
}

export interface BacktestTuningCandidate {
  name: string;
  display_name: string;
  score: number;
  performance_score?: number | null;
  coverage_score?: number | null;
  coverage_components?: BacktestCoverageScoreComponents | null;
  overall_win_rate: number;
  issue_hit_rate: number;
  sample_issues: number;
  validation_score?: number | null;
  validation_performance_score?: number | null;
  validation_coverage_score?: number | null;
  validation_coverage_components?: BacktestCoverageScoreComponents | null;
  validation_overall_win_rate?: number | null;
  validation_issue_hit_rate?: number | null;
  validation_stability_adjusted_score?: number | null;
  validation_stability_breakdown?: BacktestStabilityBreakdown | null;
  validation_max_drawdown?: number | null;
  validation_max_miss_streak?: number | null;
  walk_forward_score?: number | null;
  walk_forward_stability_adjusted_score?: number | null;
  walk_forward_stability_breakdown?: BacktestStabilityBreakdown | null;
  walk_forward_performance_score?: number | null;
  walk_forward_coverage_score?: number | null;
  walk_forward_coverage_components?: BacktestCoverageScoreComponents | null;
  walk_forward_overall_win_rate?: number | null;
  walk_forward_issue_hit_rate?: number | null;
  walk_forward_windows?: number;
  walk_forward_stability?: string | null;
  walk_forward_score_range?: number | null;
  walk_forward_max_drawdown?: number | null;
  walk_forward_max_miss_streak?: number | null;
}

export interface BacktestWalkForwardWindow {
  label: string;
  train_start_issue: string;
  train_end_issue: string;
  test_start_issue: string;
  test_end_issue: string;
  test_issues: number;
  score: number;
  overall_win_rate: number;
  issue_hit_rate: number;
}

export interface BacktestTuningWalkForwardDetail {
  name: string;
  display_name: string;
  stability?: string | null;
  score_range?: number | null;
  windows: BacktestWalkForwardWindow[];
}

export interface BacktestTuningIssueSide {
  profile_name: string;
  display_name: string;
  won_count: number;
  best_prize_level?: string | null;
  best_prize_amount?: number | null;
  cost?: number;
}

export interface BacktestTuningIssueComparison {
  issue: string;
  draw_date: string;
  applied: BacktestTuningIssueSide;
  selected: BacktestTuningIssueSide;
  won_count_delta: number;
  prize_amount_delta: number;
}

export interface BacktestTuningSummary {
  enabled: boolean;
  selected_profile?: string | null;
  selected_display_name?: string | null;
  selected_reason?: string | null;
  applied_profile?: string | null;
  applied_display_name?: string | null;
  applied_reason?: string | null;
  applied_is_override?: boolean;
  applied_total_prize_delta?: number | null;
  applied_issue_hit_rate_delta?: number | null;
  applied_roi_delta?: number | null;
  applied_delta_summary?: string | null;
  applied_issue_comparison?: BacktestTuningIssueComparison[];
  selection_warning?: string | null;
  compare_profile?: string | null;
  compare_display_name?: string | null;
  compare_reason?: string | null;
  runner_up_display_name?: string | null;
  selection_margin?: number | null;
  sample_issues: number;
  training_sample_issues?: number;
  validation_sample_issues?: number;
  selection_basis?: string;
  validation_score?: number | null;
  validation_overall_win_rate?: number | null;
  validation_issue_hit_rate?: number | null;
  validation_stability_adjusted_score?: number | null;
  validation_stability_breakdown?: BacktestStabilityBreakdown | null;
  validation_max_drawdown?: number | null;
  validation_max_miss_streak?: number | null;
  walk_forward_window_count?: number;
  walk_forward_score?: number | null;
  walk_forward_stability_adjusted_score?: number | null;
  walk_forward_stability_breakdown?: BacktestStabilityBreakdown | null;
  walk_forward_overall_win_rate?: number | null;
  walk_forward_issue_hit_rate?: number | null;
  walk_forward_stability?: string | null;
  walk_forward_score_range?: number | null;
  walk_forward_max_drawdown?: number | null;
  walk_forward_max_miss_streak?: number | null;
  walk_forward_details?: BacktestTuningWalkForwardDetail[];
  profiles: BacktestTuningCandidate[];
  weights: Record<string, number>;
}

export interface BacktestModeSummary {
  strategy_mode: BacktestStrategyMode;
  total_issues: number;
  total_generated_schemes: number;
  won_schemes: number;
  total_prize_amount: number;
  total_cost?: number;
  net_profit?: number;
  overall_win_rate: number;
  issue_hit_rate: number;
  ai_engine?: string | null;
  coverage_metrics: BacktestCoverageMetrics;
}

export interface BacktestThresholdScanItem {
  threshold: number;
  total_issues: number;
  skipped_issues?: number;
  total_generated_schemes: number;
  won_schemes: number;
  total_cost?: number;
  total_prize_amount?: number;
  net_profit?: number;
  overall_win_rate: number;
  issue_hit_rate: number;
  avg_scheme_count?: number;
  selection_score?: number | null;
  stability_breakdown?: BacktestStabilityBreakdown | null;
  stability?: string | null;
  score_range?: number | null;
  max_drawdown?: number | null;
  max_miss_streak?: number | null;
}

export interface BacktestIssueModeComparison {
  strategy_mode: BacktestStrategyMode;
  won_count: number;
  best_prize_level?: string | null;
  best_prize_amount?: number | null;
  cost?: number;
}

export interface BacktestIssueComparison {
  issue: string;
  draw_date: string;
  primary: BacktestIssueModeComparison;
  secondary: BacktestIssueModeComparison;
  won_count_delta: number;
  prize_amount_delta: number;
}

export interface BacktestResponse {
  recent_issues: number;
  requested_issues?: number;
  skipped_issues?: number;
  confidence_threshold?: number;
  scheme_count: number;
  strategy_mode: BacktestStrategyMode;
  ticket_mode?: TicketMode;
  ai_replay_mode?: AIReplayMode;
  count_policy?: string | null;
  threshold_selection_reason?: string | null;
  policy_selection_reason?: string | null;
  stability_breakdown?: BacktestStabilityBreakdown | null;
  max_drawdown?: number;
  max_miss_streak?: number;
  total_issues: number;
  total_generated_schemes: number;
  won_schemes: number;
  total_prize_amount: number;
  total_cost?: number;
  net_profit?: number;
  overall_win_rate: number;
  issue_hit_rate: number;
  prize_rates: PrizeRateItem[];
  prize_level_breakdown?: BacktestPrizeLevelSummary[];
  issues: BacktestIssueResult[];
  coverage_metrics: BacktestCoverageMetrics;
  ai_engine?: string | null;
  theoretical_single_win_rate?: number;
  benchmarks?: BacktestBenchmark[];
  window_summaries?: BacktestWindowSummary[];
  tuning_summary?: BacktestTuningSummary | null;
  mode_comparison?: BacktestModeSummary[];
  issue_comparison?: BacktestIssueComparison[];
  threshold_scan?: BacktestThresholdScanItem[];
}

export interface BacktestJobResponse {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | "canceled" | "canceling";
  stage: string;
  message?: string | null;
  progress: number;
  processed_issues: number;
  total_issues: number;
  scheme_count: number;
  strategy_mode: BacktestStrategyMode;
  ticket_mode: TicketMode;
  ai_replay_mode?: AIReplayMode;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  result?: BacktestResponse | null;
}

export interface BacktestJobListResponse {
  items: BacktestJobResponse[];
}
