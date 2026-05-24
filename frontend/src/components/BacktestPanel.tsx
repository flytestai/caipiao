import { useEffect, useMemo, useState } from "react";
import type { AIReplayMode, BacktestJobResponse, BacktestResponse, BacktestTuningCandidate, StrategyMode, TicketMode } from "../lib/types";

interface BacktestPanelProps {
  result: BacktestResponse | null;
  loading: boolean;
  job: BacktestJobResponse | null;
  jobs: BacktestJobResponse[];
  error: string | null;
  recentIssues: number;
  schemeCount: number;
  strategyMode: StrategyMode;
  ticketMode: TicketMode;
  aiReplayMode: AIReplayMode;
  compareModes: boolean;
  onRecentIssuesChange: (value: number) => void;
  onSchemeCountChange: (value: number) => void;
  onStrategyModeChange: (value: StrategyMode) => void;
  onTicketModeChange: (value: TicketMode) => void;
  onAIReplayModeChange: (value: AIReplayMode) => void;
  onCompareModesChange: (value: boolean) => void;
  onRun: (tuningProfileOverride?: string | null) => void;
  onCancelJob: () => void;
  onOpenJob: (job: BacktestJobResponse) => void;
  aiEnabled?: boolean;
}

function exportBacktest(result: BacktestResponse) {
  const lines = [
    "\u671f\u53f7,\u5f00\u5956\u65e5\u671f,\u65b9\u6848\u7ec4\u6570,\u6295\u6ce8\u7c7b\u578b,\u8c03\u53c2\u65b9\u6848,\u51b3\u7b56\u7b56\u7565,\u51b3\u7b56\u5c42\u7ea7,\u539f\u59cb\u7f6e\u4fe1,\u6821\u51c6\u7f6e\u4fe1,\u5b9e\u6218\u9608\u503c,\u524d\u533a\u539f\u59cb\u7f6e\u4fe1,\u524d\u533a\u6821\u51c6\u7f6e\u4fe1,\u524d\u533a\u95e8\u69db,\u540e\u533a\u539f\u59cb\u7f6e\u4fe1,\u540e\u533a\u6821\u51c6\u7f6e\u4fe1,\u540e\u533a\u95e8\u69db,\u662f\u5426\u6df1\u641c,\u662f\u5426\u89c2\u671b,\u547d\u4e2d\u65b9\u6848\u6570,\u6700\u9ad8\u5956\u7ea7,\u6700\u9ad8\u5956\u91d1,\u6d88\u8d39\u91d1\u989d,\u51c0\u76c8\u4e8f,\u524d\u533a\u5e73\u5747\u91cd\u53e0,\u540e\u533a\u5e73\u5747\u91cd\u53e0,\u540e\u533a\u5bf9\u5b50\u590d\u7528\u7387,\u540e\u533a\u65b0\u53f7\u8986\u76d6\u7387,\u547d\u4e2d\u65b9\u6848,\u51b3\u7b56\u539f\u56e0",
    ...result.issues.map((item) =>
      [
        item.issue,
        item.draw_date,
        item.scheme_count,
        ticketModeLabel(item.ticket_mode ?? result.ticket_mode),
        item.tuning_profile ?? "",
        item.count_policy ?? "",
        item.decision_tier ?? "",
        item.issue_confidence ?? 0,
        item.calibrated_confidence ?? 0,
        item.applied_threshold ?? 0,
        item.front_confidence ?? "",
        item.front_calibrated_confidence ?? "",
        item.front_gate ?? "",
        item.back_confidence ?? "",
        item.back_calibrated_confidence ?? "",
        item.back_gate ?? "",
        item.deep_search_triggered ? "yes" : "no",
        item.should_observe ? "yes" : "no",
        item.won_count,
        item.best_prize_level ?? "",
        item.best_prize_amount ?? 0,
        item.cost ?? 0,
        (item.best_prize_amount ?? 0) - (item.cost ?? 0),
        item.front_pairwise_overlap_avg ?? 0,
        item.back_pairwise_overlap_avg ?? 0,
        item.back_pair_reuse_rate ?? 0,
        item.fresh_back_number_rate ?? 0,
        item.winning_scheme_labels.join(" / "),
        `"${(item.decision_reason ?? "").replace(/"/g, '""')}"`,
      ].join(","),
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `dlt-backtest-${Date.now()}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function modeLabel(mode: StrategyMode) {
  return mode === "single_hit" ? "\u5355\u6ce8\u4f18\u5148" : "\u591a\u6ce8\u8986\u76d6";
}

function ticketModeLabel(mode: TicketMode | undefined) {
  return mode === "additional" ? "\u8ffd\u52a0\u6295\u6ce8" : "\u57fa\u672c\u6295\u6ce8";
}

function aiReplayModeLabel(mode: AIReplayMode | undefined) {
  return mode === "external_rerank" ? "AI 重排" : "仅本地";
}

function rateLabel(value: number | undefined) {
  return `${(((value ?? 0) as number) * 100).toFixed(1)}%`;
}

function fixedNumber(value: number | null | undefined, digits = 2) {
  return (value ?? 0).toFixed(digits);
}

function compactScore(value: number | null | undefined) {
  return (value ?? 0).toFixed(3);
}

function stabilityBreakdownLabel(
  breakdown:
    | {
        base_score: number;
        adjusted_score: number;
        range_penalty: number;
        drawdown_penalty: number;
        miss_streak_penalty: number;
      }
    | null
    | undefined,
) {
  if (!breakdown) {
    return "";
  }
  return `原始 ${breakdown.base_score.toFixed(4)} / 分差 -${breakdown.range_penalty.toFixed(4)} / 回撤 -${breakdown.drawdown_penalty.toFixed(4)} / 空窗 -${breakdown.miss_streak_penalty.toFixed(4)}`;
}

function isSameThreshold(left: number | null | undefined, right: number | null | undefined) {
  return Math.abs((left ?? 0) - (right ?? 0)) < 0.0001;
}

function signedCompactScore(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}`;
}

function coverageDeltaClass(value: number) {
  if (value > 0.0005) {
    return "text-emerald-700";
  }
  if (value < -0.0005) {
    return "text-rose-600";
  }
  return "text-slate-500";
}

function comparisonDimensionLabel(value: "train" | "validation" | "walk_forward") {
  if (value === "validation") {
    return "验证";
  }
  if (value === "walk_forward") {
    return "滚动";
  }
  return "训练";
}

function buildComparisonSummary(
  dimension: "train" | "validation" | "walk_forward",
  targetDisplayName: string,
  performanceComparison: Array<{ key: string; label: string; value: number }>,
  coverageComparison: Array<{ key: string; label: string; value: number }>,
) {
  const combined = [...performanceComparison, ...coverageComparison];
  if (!combined.length) {
    return null;
  }
  const sorted = [...combined].sort((left, right) => Math.abs(right.value) - Math.abs(left.value));
  const strongestGain = sorted.find((item) => item.value > 0.0005) ?? null;
  const strongestLoss = sorted.find((item) => item.value < -0.0005) ?? null;
  if (!strongestGain && !strongestLoss) {
    return `${comparisonDimensionLabel(dimension)}对比 ${targetDisplayName} 差异不明显`;
  }
  if (strongestGain && strongestLoss) {
    return `${comparisonDimensionLabel(dimension)}对比 ${targetDisplayName}，优势是 ${strongestGain.label} ${signedCompactScore(strongestGain.value)}，短板是 ${strongestLoss.label} ${signedCompactScore(strongestLoss.value)}`;
  }
  if (strongestGain) {
    return `${comparisonDimensionLabel(dimension)}对比 ${targetDisplayName}，主要优势是 ${strongestGain.label} ${signedCompactScore(strongestGain.value)}`;
  }
  return `${comparisonDimensionLabel(dimension)}对比 ${targetDisplayName}，主要短板是 ${strongestLoss?.label ?? "-"} ${signedCompactScore(strongestLoss?.value ?? 0)}`;
}

function getComparisonSummaryTone(
  performanceComparison: Array<{ key: string; label: string; value: number }>,
  coverageComparison: Array<{ key: string; label: string; value: number }>,
) {
  const combined = [...performanceComparison, ...coverageComparison];
  if (!combined.length) {
    return "neutral" as const;
  }
  const strongest = [...combined].sort((left, right) => Math.abs(right.value) - Math.abs(left.value))[0] ?? null;
  if (!strongest || Math.abs(strongest.value) <= 0.0005) {
    return "neutral" as const;
  }
  return strongest.value > 0 ? ("positive" as const) : ("negative" as const);
}

function getPerformanceMetricsByDimension(
  candidate: BacktestTuningCandidate | null | undefined,
  dimension: "train" | "validation" | "walk_forward",
) {
  if (!candidate) {
    return null;
  }
  if (dimension === "validation") {
    if ((candidate.validation_performance_score ?? null) === null) {
      return null;
    }
    return {
      performanceScore: candidate.validation_performance_score ?? 0,
      overallWinRate: candidate.validation_overall_win_rate ?? 0,
      issueHitRate: candidate.validation_issue_hit_rate ?? 0,
    };
  }
  if (dimension === "walk_forward") {
    if ((candidate.walk_forward_performance_score ?? null) === null) {
      return null;
    }
    return {
      performanceScore: candidate.walk_forward_performance_score ?? 0,
      overallWinRate: candidate.walk_forward_overall_win_rate ?? 0,
      issueHitRate: candidate.walk_forward_issue_hit_rate ?? 0,
    };
  }
  return {
    performanceScore: candidate.performance_score ?? 0,
    overallWinRate: candidate.overall_win_rate ?? 0,
    issueHitRate: candidate.issue_hit_rate ?? 0,
  };
}

function jobStatusLabel(status: BacktestJobResponse["status"]) {
  if (status === "queued") return "排队中";
  if (status === "running") return "运行中";
  if (status === "canceling") return "取消中";
  if (status === "completed") return "已完成";
  if (status === "canceled") return "已取消";
  return "失败";
}

function exportComparison(result: BacktestResponse) {
  const rows = result.issue_comparison ?? [];
  const lines = [
    "\u671f\u53f7,\u5f00\u5956\u65e5\u671f,\u4e3b\u6a21\u5f0f,\u4e3b\u6a21\u5f0f\u547d\u4e2d\u6570,\u4e3b\u6a21\u5f0f\u6700\u9ad8\u5956\u7ea7,\u4e3b\u6a21\u5f0f\u6700\u9ad8\u5956\u91d1,\u5bf9\u7167\u6a21\u5f0f,\u5bf9\u7167\u6a21\u5f0f\u547d\u4e2d\u6570,\u5bf9\u7167\u6a21\u5f0f\u6700\u9ad8\u5956\u7ea7,\u5bf9\u7167\u6a21\u5f0f\u6700\u9ad8\u5956\u91d1,\u547d\u4e2d\u6570\u5dee\u989d,\u5956\u91d1\u5dee\u989d",
    ...rows.map((row) =>
      [
        row.issue,
        row.draw_date,
        modeLabel(row.primary.strategy_mode),
        row.primary.won_count,
        row.primary.best_prize_level ?? "",
        row.primary.best_prize_amount ?? 0,
        modeLabel(row.secondary.strategy_mode),
        row.secondary.won_count,
        row.secondary.best_prize_level ?? "",
        row.secondary.best_prize_amount ?? 0,
        row.won_count_delta,
        row.prize_amount_delta,
      ].join(","),
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `dlt-backtest-compare-${Date.now()}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function BacktestPanel({
  result,
  loading,
  job,
  jobs,
  error,
  recentIssues,
  schemeCount,
  strategyMode,
  ticketMode,
  aiReplayMode,
  compareModes,
  onRecentIssuesChange,
  onSchemeCountChange,
  onStrategyModeChange,
  onTicketModeChange,
  onAIReplayModeChange,
  onCompareModesChange,
  onRun,
  onCancelJob,
  onOpenJob,
  aiEnabled = false,
}: BacktestPanelProps) {
  const [resultFilter, setResultFilter] = useState<"all" | "won" | "not_won">("all");
  const [comparisonFilter, setComparisonFilter] = useState<"all" | "primary" | "secondary" | "same">("all");
  const [comparisonThreshold, setComparisonThreshold] = useState(0);
  const [comparisonSort, setComparisonSort] = useState<"prize_delta" | "won_delta" | "date_desc" | "date_asc">("prize_delta");
  const [tuningView, setTuningView] = useState<"selected" | "compare">("selected");
  const [tuningCompareDimension, setTuningCompareDimension] = useState<"train" | "validation" | "walk_forward">("train");

  const visibleIssues = useMemo(() => {
    if (!result) {
      return [];
    }
    return result.issues.filter((item) => {
      if (resultFilter === "won") {
        return item.won_count > 0;
      }
      if (resultFilter === "not_won") {
        return item.won_count === 0;
      }
      return true;
    });
  }, [result, resultFilter]);

  const benchmarks = result?.benchmarks ?? [];
  const windowSummaries = result?.window_summaries ?? [];
  const thresholdScan = useMemo(() => {
    const rows = [...(result?.threshold_scan ?? [])];
    rows.sort((left, right) => {
      const scoreGap = (right.selection_score ?? 0) - (left.selection_score ?? 0);
      if (Math.abs(scoreGap) > 0.0001) {
        return scoreGap;
      }
      const hitRateGap = (right.issue_hit_rate ?? 0) - (left.issue_hit_rate ?? 0);
      if (Math.abs(hitRateGap) > 0.0001) {
        return hitRateGap;
      }
      return (left.threshold ?? 0) - (right.threshold ?? 0);
    });
    return rows;
  }, [result?.threshold_scan]);
  const activeThresholdRow = useMemo(
    () => thresholdScan.find((item) => isSameThreshold(item.threshold, result?.confidence_threshold)) ?? null,
    [thresholdScan, result?.confidence_threshold],
  );
  const bestThresholdRow = thresholdScan[0] ?? null;
  const thresholdTradeoffSummary = useMemo(() => {
    if (!activeThresholdRow || !bestThresholdRow || isSameThreshold(activeThresholdRow.threshold, bestThresholdRow.threshold)) {
      return null;
    }
    const scoreGap = (bestThresholdRow.selection_score ?? 0) - (activeThresholdRow.selection_score ?? 0);
    const drawdownDelta = (bestThresholdRow.max_drawdown ?? 0) - (activeThresholdRow.max_drawdown ?? 0);
    const missDelta = (bestThresholdRow.max_miss_streak ?? 0) - (activeThresholdRow.max_miss_streak ?? 0);
    return {
      scoreGap,
      drawdownDelta,
      missDelta,
    };
  }, [activeThresholdRow, bestThresholdRow]);
  const tuningSummary = result?.tuning_summary ?? null;
  const tuningProfiles = tuningSummary?.profiles ?? [];
  const hasValidationComparison = tuningProfiles.some((item) => item.validation_coverage_components);
  const hasWalkForwardComparison = tuningProfiles.some((item) => item.walk_forward_coverage_components);
  useEffect(() => {
    if (tuningSummary?.applied_is_override && tuningSummary.compare_profile === tuningSummary.applied_profile) {
      setTuningView("compare");
      return;
    }
    setTuningView("selected");
  }, [tuningSummary?.selected_profile, tuningSummary?.compare_profile, tuningSummary?.applied_is_override, tuningSummary?.applied_profile]);
  useEffect(() => {
    if (hasValidationComparison) {
      setTuningCompareDimension("validation");
      return;
    }
    if (hasWalkForwardComparison) {
      setTuningCompareDimension("walk_forward");
      return;
    }
    setTuningCompareDimension("train");
  }, [hasValidationComparison, hasWalkForwardComparison, tuningSummary?.selected_profile]);
  const activeTuningProfileName =
    tuningView === "compare" && tuningSummary?.compare_profile ? tuningSummary.compare_profile : tuningSummary?.selected_profile;
  const activeTuningCandidate =
    tuningProfiles.find((item) => item.name === activeTuningProfileName) ?? null;
  const leadTuningCandidate = tuningProfiles[0] ?? null;
  const runnerUpTuningCandidate = tuningProfiles[1] ?? null;
  const getCoverageComponentsByDimension = (
    candidate: BacktestTuningCandidate | null | undefined,
    dimension: "train" | "validation" | "walk_forward",
  ) => {
    if (!candidate) {
      return null;
    }
    if (dimension === "validation") {
      return candidate.validation_coverage_components ?? null;
    }
    if (dimension === "walk_forward") {
      return candidate.walk_forward_coverage_components ?? null;
    }
    return candidate.coverage_components ?? null;
  };
  const activeComparisonTarget =
    activeTuningCandidate?.name === leadTuningCandidate?.name ? runnerUpTuningCandidate : leadTuningCandidate;
  const activePerformanceMetrics = getPerformanceMetricsByDimension(activeTuningCandidate, tuningCompareDimension);
  const targetPerformanceMetrics = getPerformanceMetricsByDimension(activeComparisonTarget, tuningCompareDimension);
  const activeCoverageComponents = getCoverageComponentsByDimension(activeTuningCandidate, tuningCompareDimension);
  const targetCoverageComponents = getCoverageComponentsByDimension(activeComparisonTarget, tuningCompareDimension);
  const activePerformanceComparison =
    activePerformanceMetrics && targetPerformanceMetrics
      ? [
          {
            key: "performance",
            label: "表现",
            value: activePerformanceMetrics.performanceScore - targetPerformanceMetrics.performanceScore,
          },
          {
            key: "win",
            label: "方案",
            value: activePerformanceMetrics.overallWinRate - targetPerformanceMetrics.overallWinRate,
          },
          {
            key: "issue",
            label: "期号",
            value: activePerformanceMetrics.issueHitRate - targetPerformanceMetrics.issueHitRate,
          },
        ]
      : [];
  const activeCoverageComparison =
    activeCoverageComponents && targetCoverageComponents
      ? [
          {
            key: "front",
            label: "前区",
            value: activeCoverageComponents.front_diversity - targetCoverageComponents.front_diversity,
          },
          {
            key: "back",
            label: "后区",
            value: activeCoverageComponents.back_diversity - targetCoverageComponents.back_diversity,
          },
          {
            key: "pair",
            label: "对子",
            value: activeCoverageComponents.back_pair_diversity - targetCoverageComponents.back_pair_diversity,
          },
          {
            key: "fresh",
            label: "新号",
            value: activeCoverageComponents.fresh_back - targetCoverageComponents.fresh_back,
          },
        ]
      : [];
  const activeComparisonSummary = activeComparisonTarget
    ? buildComparisonSummary(
        tuningCompareDimension,
        activeComparisonTarget.display_name,
        activePerformanceComparison,
        activeCoverageComparison,
      )
    : null;
  const activeComparisonTone = getComparisonSummaryTone(activePerformanceComparison, activeCoverageComparison);
  const activeWalkForwardDetail =
    tuningSummary?.walk_forward_details?.find((item) => item.name === activeTuningProfileName) ?? null;
  const visibleWalkForwardDetails = useMemo(() => {
    const details = tuningSummary?.walk_forward_details ?? [];
    if (!activeTuningProfileName) {
      return details;
    }
    return [...details].sort((left, right) => {
      if (left.name === activeTuningProfileName) {
        return -1;
      }
      if (right.name === activeTuningProfileName) {
        return 1;
      }
      return left.display_name.localeCompare(right.display_name);
    });
  }, [activeTuningProfileName, tuningSummary?.walk_forward_details]);
  const modeComparison = result?.mode_comparison ?? [];
  const issueComparison = result?.issue_comparison ?? [];
  const filteredIssueComparison = useMemo(() => {
    const filtered = issueComparison.filter((row) => {
      const absDelta = Math.abs(row.prize_amount_delta);
      if (absDelta < comparisonThreshold) {
        return false;
      }
      if (comparisonFilter === "primary") {
        return row.prize_amount_delta > 0;
      }
      if (comparisonFilter === "secondary") {
        return row.prize_amount_delta < 0;
      }
      if (comparisonFilter === "same") {
        return row.prize_amount_delta === 0;
      }
      return true;
    });

    filtered.sort((left, right) => {
      if (comparisonSort === "won_delta") {
        return Math.abs(right.won_count_delta) - Math.abs(left.won_count_delta) || right.issue.localeCompare(left.issue);
      }
      if (comparisonSort === "date_desc") {
        return right.issue.localeCompare(left.issue);
      }
      if (comparisonSort === "date_asc") {
        return left.issue.localeCompare(right.issue);
      }
      return Math.abs(right.prize_amount_delta) - Math.abs(left.prize_amount_delta) || right.issue.localeCompare(left.issue);
    });

    return filtered;
  }, [comparisonFilter, comparisonSort, comparisonThreshold, issueComparison]);
  const comparisonInsight = useMemo(() => {
    if (issueComparison.length === 0) {
      return null;
    }
    const primaryMode = issueComparison[0].primary.strategy_mode;
    const secondaryMode = issueComparison[0].secondary.strategy_mode;
    const primaryWinCount = issueComparison.filter((row) => row.prize_amount_delta > 0).length;
    const secondaryWinCount = issueComparison.filter((row) => row.prize_amount_delta < 0).length;
    const tieCount = issueComparison.length - primaryWinCount - secondaryWinCount;
    const avgDelta =
      issueComparison.reduce((sum, row) => sum + row.prize_amount_delta, 0) / issueComparison.length;
    const strongestPrimary = issueComparison.reduce((best, row) => {
      if (row.prize_amount_delta <= 0) {
        return best;
      }
      if (!best || row.prize_amount_delta > best.prize_amount_delta) {
        return row;
      }
      return best;
    }, null as (typeof issueComparison)[number] | null);
    const strongestSecondary = issueComparison.reduce((best, row) => {
      if (row.prize_amount_delta >= 0) {
        return best;
      }
      if (!best || row.prize_amount_delta < best.prize_amount_delta) {
        return row;
      }
      return best;
    }, null as (typeof issueComparison)[number] | null);
    return {
      primaryMode,
      secondaryMode,
      primaryWinCount,
      secondaryWinCount,
      tieCount,
      avgDelta,
      strongestPrimary,
      strongestSecondary,
    };
  }, [issueComparison]);

  return (
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,0.06)]">
      {job ? (
        <div
          className={`mb-4 rounded-2xl border px-4 py-3 ${
            job.status === "failed" ? "border-rose-200 bg-rose-50" : job.status === "completed" ? "border-emerald-200 bg-emerald-50" : "border-cyan-200 bg-cyan-50"
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-slate-900">
                {job.status === "failed" ? "回测失败" : job.status === "completed" ? "回测完成" : "回测进行中"}
              </p>
              <p className="mt-1 text-xs text-slate-600">{job.error ?? job.message ?? "正在准备回测任务"}</p>
            </div>
            <div className="text-right">
              <p className="text-sm font-semibold text-slate-900">{`${(job.progress * 100).toFixed(1)}%`}</p>
              <p className="mt-1 text-xs text-slate-500">{`${job.processed_issues}/${job.total_issues || recentIssues} 期`}</p>
            </div>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/70">
            <div
              className={`h-full rounded-full ${job.status === "failed" ? "bg-rose-500" : job.status === "completed" ? "bg-emerald-500" : "bg-cyan-500"}`}
              style={{ width: `${Math.max(job.progress * 100, job.status === "running" ? 3 : 0)}%` }}
            />
          </div>
        </div>
      ) : null}
      {error ? (
        <div className="mb-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>
      ) : null}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs tracking-[0.3em] text-cyan-700/70">{"\u5386\u53f2\u56de\u6d4b"}</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">{"\u5386\u53f2\u547d\u4e2d\u7387\u6d4b\u8bd5"}</h2>
          <p className="mt-2 text-sm text-slate-600">{"\u6309\u5386\u53f2\u671f\u53f7\u9010\u671f\u56de\u653e\u63a8\u6f14\uff0c\u53ea\u4f7f\u7528\u5f53\u65f6\u4e4b\u524d\u7684\u5386\u53f2\u6570\u636e\u3002"}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {result ? (
            <button
              onClick={() => exportBacktest(result)}
              className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-700"
            >
              {"\u5bfc\u51fa\u56de\u6d4b"}
            </button>
          ) : null}
          {result && (result.issue_comparison?.length ?? 0) > 0 ? (
            <button
              onClick={() => exportComparison(result)}
              className="rounded-2xl border border-violet-200 bg-violet-50 px-4 py-2 text-sm font-medium text-violet-700"
            >
              {"\u5bfc\u51fa\u5bf9\u6bd4"}
            </button>
          ) : null}
          <button
            onClick={() => onRun()}
            disabled={loading}
            className="rounded-2xl border border-cyan-200 bg-cyan-50 px-4 py-2 text-sm font-medium text-cyan-700 disabled:opacity-60"
          >
            {loading ? "\u56de\u6d4b\u4e2d..." : "\u5f00\u59cb\u56de\u6d4b"}
          </button>
          {job && (job.status === "queued" || job.status === "running" || job.status === "canceling") ? (
            <button
              onClick={onCancelJob}
              disabled={job.status === "canceling"}
              className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-medium text-rose-700 disabled:opacity-60"
            >
              {job.status === "canceling" ? "取消中..." : "取消回测"}
            </button>
          ) : null}
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(320px,0.78fr)_minmax(0,1.22fr)]">
        <div className="min-w-0 space-y-4 xl:sticky xl:top-4 xl:self-start">
          <div className="rounded-[24px] border border-cyan-200 bg-cyan-50/70 p-4">
            <p className="text-sm font-medium text-slate-900">使用建议</p>
            <div className="mt-3 grid gap-3">
              <div className="rounded-2xl border border-cyan-100 bg-white/90 px-4 py-3">
                <p className="text-xs tracking-[0.18em] text-cyan-700">建议起步</p>
                <p className="mt-1 text-sm text-slate-800">建议先用较小样本试跑，确认趋势后再逐步放大期数和方案组数。</p>
              </div>
              <div className="rounded-2xl border border-sky-100 bg-white/90 px-4 py-3">
                <p className="text-xs tracking-[0.18em] text-sky-700">结果解读</p>
                <p className="mt-1 text-sm text-slate-800">重点关注命中率、净收益、最大回撤和最长空窗，不要只看单次高奖。</p>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm font-medium text-slate-900">{"\u56de\u6d4b\u63a7\u5236\u533a"}</p>
            <div className="mt-4 grid gap-3 xl:grid-cols-1 2xl:grid-cols-3">
              <label className="grid gap-2 rounded-2xl border border-slate-200 bg-white p-4">
                <span className="text-xs text-slate-500">{"\u56de\u6d4b\u671f\u6570"}</span>
                <input
                  type="number"
                  min={5}
                  value={recentIssues}
                  onChange={(event) => onRecentIssuesChange(Math.max(5, Number(event.target.value) || 5))}
                  className="h-11 rounded-xl border border-slate-200 bg-slate-50 px-4 text-sm text-slate-900 outline-none"
                />
              </label>
              <label className="grid gap-2 rounded-2xl border border-slate-200 bg-white p-4">
                <span className="text-xs text-slate-500">{"\u6bcf\u671f\u65b9\u6848\u7ec4\u6570"}</span>
                <input
                  type="number"
                  min={1}
                  value={schemeCount}
                  onChange={(event) => onSchemeCountChange(Math.max(1, Number(event.target.value) || 1))}
                  className="h-11 rounded-xl border border-slate-200 bg-slate-50 px-4 text-sm text-slate-900 outline-none"
                />
              </label>
              <div className="grid gap-2 rounded-2xl border border-slate-200 bg-white p-4">
                <span className="text-xs text-slate-500">{"\u6295\u6ce8\u7c7b\u578b"}</span>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { value: "basic" as const, label: "\u57fa\u672c", description: "2 \u5143/\u6ce8" },
                    { value: "additional" as const, label: "\u8ffd\u52a0", description: "3 \u5143/\u6ce8" },
                  ].map((mode) => (
                    <button
                      key={mode.value}
                      onClick={() => onTicketModeChange(mode.value)}
                      className={`rounded-xl border px-3 py-2 text-left transition ${
                        ticketMode === mode.value ? "border-cyan-300 bg-cyan-50 text-cyan-800" : "border-slate-200 bg-slate-50 text-slate-700"
                      }`}
                    >
                      <p className="text-sm font-medium">{mode.label}</p>
                      <p className={`mt-1 text-xs ${ticketMode === mode.value ? "text-cyan-700" : "text-slate-500"}`}>{mode.description}</p>
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid gap-2 rounded-2xl border border-slate-200 bg-white p-4">
                <span className="text-xs text-slate-500">{"回放引擎"}</span>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { value: "local_only" as const, label: "仅本地", description: "只跑确定性本地链路" },
                    {
                      value: "external_rerank" as const,
                      label: "AI 重排",
                      description: aiEnabled ? "逐期调用外部 AI 微调组合" : "需先完成 AI 配置",
                    },
                  ].map((mode) => {
                    const disabled = mode.value === "external_rerank" && !aiEnabled;
                    return (
                      <button
                        key={mode.value}
                        onClick={() => !disabled && onAIReplayModeChange(mode.value)}
                        disabled={disabled}
                        className={`rounded-xl border px-3 py-2 text-left transition ${
                          aiReplayMode === mode.value
                            ? "border-violet-300 bg-violet-50 text-violet-800"
                            : disabled
                              ? "border-slate-200 bg-slate-50 text-slate-400"
                              : "border-slate-200 bg-slate-50 text-slate-700"
                        }`}
                      >
                        <p className="text-sm font-medium">{mode.label}</p>
                        <p className={`mt-1 text-xs ${
                          aiReplayMode === mode.value ? "text-violet-700" : disabled ? "text-slate-400" : "text-slate-500"
                        }`}>
                          {mode.description}
                        </p>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            <p className="mt-3 text-xs text-slate-500">
              {"期数越多耗时越久，超过 200 期时建议分批运行，便于观察不同区间表现。"}
            </p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {[
                { value: "multi_cover" as const, label: "\u591a\u6ce8\u8986\u76d6", description: "\u4f18\u5148\u63d0\u5347\u591a\u6ce8\u8054\u5408\u547d\u4e2d" },
                { value: "single_hit" as const, label: "\u5355\u6ce8\u4f18\u5148", description: "\u4f18\u5148\u96c6\u4e2d\u9ad8\u5206\u53f7\u7801" },
              ].map((mode) => (
                <button
                  key={mode.value}
                  onClick={() => onStrategyModeChange(mode.value)}
                  className={`rounded-2xl border px-4 py-3 text-left transition ${
                    strategyMode === mode.value
                      ? "border-cyan-300 bg-cyan-50 text-cyan-800"
                      : "border-slate-200 bg-white text-slate-700"
                  }`}
                >
                  <p className="text-sm font-medium">{mode.label}</p>
                  <p className={`mt-1 text-xs leading-5 ${strategyMode === mode.value ? "text-cyan-700" : "text-slate-500"}`}>{mode.description}</p>
                </button>
              ))}
            </div>
            <label className="mt-3 flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <input
                type="checkbox"
                checked={compareModes}
                onChange={(event) => onCompareModesChange(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-cyan-600"
              />
              <div>
                <p className="text-sm font-medium text-slate-900">{"\u540c\u65f6\u5bf9\u6bd4\u4e24\u79cd\u6a21\u5f0f"}</p>
                <p className="mt-1 text-xs text-slate-500">{"\u4fdd\u7559\u5f53\u524d\u6a21\u5f0f\u660e\u7ec6\uff0c\u989d\u5916\u8fd4\u56de\u53e6\u4e00\u79cd\u6a21\u5f0f\u6458\u8981"}</p>
              </div>
            </label>
            {jobs.length > 0 ? (
              <div className="mt-3 rounded-2xl border border-slate-200 bg-white p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-slate-900">最近任务</p>
                  <p className="text-xs text-slate-500">点击可切换查看结果</p>
                </div>
                <div className="mt-3 max-h-[320px] space-y-2 overflow-y-auto pr-1">
                  {jobs.map((item) => {
                    const isActive = item.job_id === job?.job_id;
                    const jobResult = item.result;
                    const issueCount = jobResult?.recent_issues ?? (item.total_issues || recentIssues);
                    const strategyLabel = modeLabel(jobResult?.strategy_mode ?? item.strategy_mode);
                    const ticketLabel = ticketModeLabel(jobResult?.ticket_mode ?? item.ticket_mode);
                    const replayLabel = aiReplayModeLabel(jobResult?.ai_replay_mode ?? item.ai_replay_mode);
                    const schemeCountLabel = `${item.scheme_count} 注`;
                    const netProfit = jobResult?.net_profit;
                    return (
                      <button
                        key={item.job_id}
                        onClick={() => onOpenJob(item)}
                        className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                          isActive ? "border-cyan-300 bg-cyan-50" : "border-slate-200 bg-slate-50 hover:bg-slate-100"
                        }`}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-medium text-slate-900">{`${issueCount} 期 / ${strategyLabel}`}</p>
                          <span className="text-xs text-slate-500">{jobStatusLabel(item.status)}</span>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                          <span>{ticketLabel}</span>
                          <span>{replayLabel}</span>
                          <span>{schemeCountLabel}</span>
                          {netProfit != null ? (
                            <span className={netProfit >= 0 ? "text-emerald-700" : "text-rose-600"}>
                              {`${netProfit >= 0 ? "+" : ""}${netProfit.toFixed(2)}`}
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 text-xs text-slate-500">
                          {item.message ?? item.error ?? `${item.processed_issues}/${item.total_issues || recentIssues} 期`}
                        </p>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}
            <div className="mt-4 rounded-2xl border border-cyan-200 bg-cyan-50 px-4 py-3">
              <p className="text-sm font-medium text-cyan-800">{"\u56de\u6d4b\u8bf4\u660e"}</p>
              <p className="mt-1 text-xs leading-6 text-cyan-700">{"\u7cfb\u7edf\u4f1a\u7528\u5f53\u671f\u4e4b\u524d\u53ef\u5f97\u7684\u6837\u672c\u9010\u671f\u91cd\u8dd1\u63a8\u6f14\uff0c\u7528\u4e8e\u89c2\u5bdf\u7b56\u7565\u7684\u7a33\u5b9a\u6027\u3002\u57fa\u672c\u6295\u6ce8 2 \u5143/\u6ce8\uff0c\u8ffd\u52a0\u6295\u6ce8 3 \u5143/\u6ce8\uff0c\u6d88\u8d39\u91d1\u989d\u4f1a\u968f\u7968\u79cd\u81ea\u52a8\u53d8\u5316\u3002"}</p>
              <p className="mt-2 rounded-xl bg-white/70 px-3 py-2 text-xs leading-6 text-cyan-700">
                {aiReplayMode === "external_rerank"
                  ? aiEnabled
                    ? "当前已切到 AI 重排回放：每一期都会先跑本地候选号，再调用外部 AI 做最终确认或微调，耗时和调用成本会明显上升。"
                    : "AI 重排需要先在设置中启用并完整配置外部 AI，未配置时只能使用本地回放。"
                  : "当前使用仅本地回放：逐期复现确定性本地链路，更适合做稳定性和成本可控的历史对比。"}
              </p>
              {result?.ai_engine ? (
                <p className="mt-2 text-xs leading-6 text-slate-600">
                  {"\u672c\u6b21\u56de\u6d4b\u5f15\u64ce\uff1a"}
                  <span className="font-medium text-slate-800">{result.ai_engine}</span>
                </p>
              ) : null}
              {result?.ai_replay_mode ? (
                <p className="mt-1 text-xs leading-6 text-slate-600">
                  {"回放模式："}
                  <span className="font-medium text-slate-800">{aiReplayModeLabel(result.ai_replay_mode)}</span>
                </p>
              ) : null}
              {result?.strategy_mode ? (
                <p className="mt-1 text-xs leading-6 text-slate-600">
                  {"\u5f53\u524d\u76ee\u6807\uff1a"}
                  <span className="font-medium text-slate-800">
                    {result.strategy_mode === "single_hit" ? "\u5355\u6ce8\u4f18\u5148" : "\u591a\u6ce8\u8986\u76d6"}
                  </span>
                  {result?.count_policy ? <span className="ml-2 text-slate-500">{`策略 ${result.count_policy}`}</span> : null}
                </p>
              ) : null}
              {result?.ticket_mode ? (
                <p className="mt-1 text-xs leading-6 text-slate-600">
                  {"\u5f53\u524d\u7968\u79cd\uff1a"}
                  <span className="font-medium text-slate-800">{ticketModeLabel(result.ticket_mode)}</span>
                </p>
              ) : null}
            </div>
          </div>

        <div className="min-w-0 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs text-slate-500">{"\u65b9\u6848\u603b\u4e2d\u5956\u7387"}</p>
              <p className="mt-2 text-2xl font-semibold text-emerald-700">{((result?.overall_win_rate ?? 0) * 100).toFixed(2)}%</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs text-slate-500">{"\u671f\u53f7\u547d\u4e2d\u7387"}</p>
              <p className="mt-2 text-2xl font-semibold text-cyan-700">{((result?.issue_hit_rate ?? 0) * 100).toFixed(2)}%</p>
            </div>
          </div>

          {result?.coverage_metrics ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <p className="text-xs text-slate-500">{"\u524d\u533a\u5e73\u5747\u91cd\u53e0"}</p>
                <p className="mt-2 text-2xl font-semibold text-slate-900">{fixedNumber(result.coverage_metrics.front_pairwise_overlap_avg)}</p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <p className="text-xs text-slate-500">{"\u540e\u533a\u5e73\u5747\u91cd\u53e0"}</p>
                <p className="mt-2 text-2xl font-semibold text-slate-900">{fixedNumber(result.coverage_metrics.back_pairwise_overlap_avg)}</p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <p className="text-xs text-slate-500">{"\u540e\u533a\u5bf9\u5b50\u590d\u7528\u7387"}</p>
                <p className="mt-2 text-2xl font-semibold text-slate-900">{rateLabel(result.coverage_metrics.back_pair_reuse_rate)}</p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                <p className="text-xs text-slate-500">{"\u540e\u533a\u65b0\u53f7\u8986\u76d6\u7387"}</p>
                <p className="mt-2 text-2xl font-semibold text-slate-900">{rateLabel(result.coverage_metrics.fresh_back_number_rate)}</p>
              </div>
            </div>
          ) : null}

          {windowSummaries.length > 0 ? (
            <div className="min-w-0 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-slate-900">{"\u5206\u7a97\u53e3\u8868\u73b0"}</p>
                <span className="text-xs text-slate-500">{"\u89c2\u5bdf\u8fd1\u671f / \u4e2d\u671f / \u957f\u7a97\u53e3\u662f\u5426\u4e00\u81f4"}</span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {windowSummaries.map((item) => (
                  <div key={item.label} className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <p className="text-sm font-medium text-slate-900">{item.label}</p>
                    <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <p className="text-xs text-slate-500">{"\u65b9\u6848\u4e2d\u5956\u7387"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{(item.overall_win_rate * 100).toFixed(2)}%</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u671f\u53f7\u547d\u4e2d\u7387"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{(item.issue_hit_rate * 100).toFixed(2)}%</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u4e2d\u5956\u65b9\u6848"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{item.won_schemes}</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u76c8\u4e8f"}</p>
                        <p className={`mt-1 font-semibold ${(item.net_profit ?? 0) >= 0 ? "text-emerald-700" : "text-rose-600"}`}>
                          {`${(item.net_profit ?? 0) >= 0 ? "+" : ""}${(item.net_profit ?? 0).toFixed(2)}`}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {tuningSummary?.enabled ? (
            <div className="min-w-0 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-900">{"\u81ea\u52a8\u8c03\u53c2"}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {`\u8c03\u53c2\u6837\u672c ${tuningSummary.sample_issues} \u671f \u00b7 \u8bad\u7ec3 ${
                      tuningSummary.training_sample_issues ?? tuningSummary.sample_issues
                    } \u671f${
                      (tuningSummary.validation_sample_issues ?? 0) > 0
                        ? ` \u00b7 \u9a8c\u8bc1 ${tuningSummary.validation_sample_issues} \u671f`
                        : ""
                    } \u00b7 \u81ea\u52a8\u9009\u4e2d ${tuningSummary.selected_display_name ?? tuningSummary.selected_profile ?? "-"}${
                      tuningSummary.applied_display_name ? ` \u00b7 \u672c\u6b21\u5e94\u7528 ${tuningSummary.applied_display_name}` : ""
                    }${
                      activeTuningCandidate ? ` \u00b7 \u5f53\u524d\u67e5\u770b ${activeTuningCandidate.display_name}` : ""
                    }`}
                  </p>
                  {tuningSummary.applied_reason ? (
                    <p className="mt-1 text-xs text-slate-500">{tuningSummary.applied_reason}</p>
                  ) : null}
                  {tuningSummary.applied_is_override && tuningSummary.applied_delta_summary ? (
                    <div className="mt-2 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-3">
                      <p className="text-xs font-medium text-amber-800">{tuningSummary.applied_delta_summary}</p>
                      <p className="mt-1 text-xs text-amber-700">
                        {`总奖金 ${((tuningSummary.applied_total_prize_delta ?? 0) >= 0 ? "+" : "")}${(tuningSummary.applied_total_prize_delta ?? 0).toFixed(2)} · 命中率 ${((tuningSummary.applied_issue_hit_rate_delta ?? 0) >= 0 ? "+" : "")}${(((tuningSummary.applied_issue_hit_rate_delta ?? 0) * 100)).toFixed(2)}% · ROI ${((tuningSummary.applied_roi_delta ?? 0) >= 0 ? "+" : "")}${(((tuningSummary.applied_roi_delta ?? 0) * 100)).toFixed(2)}%`}
                      </p>
                    </div>
                  ) : null}
                  {tuningSummary.compare_profile && tuningSummary.compare_display_name ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        onClick={() => setTuningView("selected")}
                        className={`rounded-2xl border px-3 py-1 text-xs font-medium ${
                          tuningView === "selected"
                            ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                            : "border-slate-200 bg-white text-slate-600"
                        }`}
                      >
                        {"\u67e5\u770b\u5df2\u9009\u65b9\u6848"}
                      </button>
                      <button
                        onClick={() => setTuningView("compare")}
                        className={`rounded-2xl border px-3 py-1 text-xs font-medium ${
                          tuningView === "compare"
                            ? "border-amber-300 bg-amber-50 text-amber-700"
                            : "border-slate-200 bg-white text-slate-600"
                        }`}
                      >
                        {`\u67e5\u770b\u66f4\u7a33\u6b21\u4f18\uff1a${tuningSummary.compare_display_name}`}
                      </button>
                      <button
                        onClick={() => onRun(tuningSummary.compare_profile)}
                        disabled={loading}
                        className="rounded-2xl border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700 disabled:opacity-60"
                      >
                        {"\u7528\u66f4\u7a33\u6b21\u4f18\u91cd\u7b97"}
                      </button>
                      {tuningSummary.applied_is_override ? (
                        <button
                          onClick={() => onRun()}
                          disabled={loading}
                          className="rounded-2xl border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 disabled:opacity-60"
                        >
                          {"\u6062\u590d\u81ea\u52a8\u65b9\u6848\u91cd\u7b97"}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                  {tuningSummary.selected_reason ? (
                    <p className="mt-1 text-xs text-slate-500">{tuningSummary.selected_reason}</p>
                  ) : null}
                  {tuningSummary.selection_warning ? (
                    <p className="mt-1 text-xs text-amber-700">{tuningSummary.selection_warning}</p>
                  ) : null}
                  {tuningView === "compare" && tuningSummary.compare_reason ? (
                    <p className="mt-1 text-xs text-amber-700">{tuningSummary.compare_reason}</p>
                  ) : null}
                  {activeComparisonSummary ? (
                    <p
                      className={`mt-1 text-xs ${
                        activeComparisonTone === "positive"
                          ? "text-emerald-700"
                          : activeComparisonTone === "negative"
                            ? "text-rose-600"
                            : "text-slate-600"
                      }`}
                    >
                      {activeComparisonSummary}
                    </p>
                  ) : null}
                  {(activeTuningCandidate?.validation_score ?? tuningSummary.validation_score ?? null) !== null ? (
                    <p className="mt-1 text-xs text-slate-500">
                      {`\u6837\u672c\u5916\u9a8c\u8bc1\u5206 ${((activeTuningCandidate?.validation_score ?? tuningSummary.validation_score) ?? 0).toFixed(4)} \u00b7 \u65b9\u6848\u4e2d\u5956\u7387 ${(
                        ((activeTuningCandidate?.validation_overall_win_rate ?? tuningSummary.validation_overall_win_rate ?? 0) * 100)
                      ).toFixed(2)}% \u00b7 \u671f\u53f7\u547d\u4e2d\u7387 ${(
                        ((activeTuningCandidate?.validation_issue_hit_rate ?? tuningSummary.validation_issue_hit_rate ?? 0) * 100)
                      ).toFixed(2)}%${
                        (activeTuningCandidate?.validation_stability_adjusted_score ?? tuningSummary.validation_stability_adjusted_score ?? null) !== null
                          ? ` \u00b7 \u7a33\u5b9a\u4fee\u6b63 ${((activeTuningCandidate?.validation_stability_adjusted_score ?? tuningSummary.validation_stability_adjusted_score) ?? 0).toFixed(4)}`
                          : ""
                      }${
                        (activeTuningCandidate?.validation_performance_score ?? null) !== null
                          ? ` \u00b7 \u8868\u73b0 ${(activeTuningCandidate?.validation_performance_score ?? 0).toFixed(4)}`
                          : ""
                      }${
                        (activeTuningCandidate?.validation_coverage_score ?? null) !== null
                          ? ` \u00b7 \u8986\u76d6 ${(activeTuningCandidate?.validation_coverage_score ?? 0).toFixed(4)}`
                          : ""
                      }${
                        activeTuningCandidate?.validation_coverage_components
                          ? ` \u00b7 \u524d ${compactScore(activeTuningCandidate.validation_coverage_components.front_diversity)} / \u540e ${compactScore(activeTuningCandidate.validation_coverage_components.back_diversity)} / \u5bf9 ${compactScore(activeTuningCandidate.validation_coverage_components.back_pair_diversity)} / \u65b0 ${compactScore(activeTuningCandidate.validation_coverage_components.fresh_back)}`
                          : ""
                      }${
                        (activeTuningCandidate?.validation_max_drawdown ?? tuningSummary.validation_max_drawdown ?? null) !== null
                          ? ` \u00b7 \u56de\u64a4 ${((activeTuningCandidate?.validation_max_drawdown ?? tuningSummary.validation_max_drawdown) ?? 0).toFixed(2)}`
                          : ""
                      }${
                        (activeTuningCandidate?.validation_max_miss_streak ?? tuningSummary.validation_max_miss_streak ?? null) !== null
                          ? ` \u00b7 \u7a7a\u7a97 ${((activeTuningCandidate?.validation_max_miss_streak ?? tuningSummary.validation_max_miss_streak) ?? 0)}`
                          : ""
                      }${
                        stabilityBreakdownLabel(activeTuningCandidate?.validation_stability_breakdown ?? tuningSummary.validation_stability_breakdown)
                          ? ` \u00b7 ${stabilityBreakdownLabel(activeTuningCandidate?.validation_stability_breakdown ?? tuningSummary.validation_stability_breakdown)}`
                          : ""
                      }`}
                    </p>
                  ) : null}
                  {(activeTuningCandidate?.walk_forward_score ?? tuningSummary.walk_forward_score ?? null) !== null ? (
                    <p className="mt-1 text-xs text-slate-500">
                      {`Walk-forward ${activeTuningCandidate?.walk_forward_windows ?? tuningSummary.walk_forward_window_count ?? 0} \u7a97\u53e3 \u00b7 \u5206 ${((activeTuningCandidate?.walk_forward_score ?? tuningSummary.walk_forward_score) ?? 0).toFixed(
                        4,
                      )}${
                        (activeTuningCandidate?.walk_forward_stability_adjusted_score ?? tuningSummary.walk_forward_stability_adjusted_score ?? null) !== null
                          ? ` \u00b7 \u7a33\u5b9a\u4fee\u6b63 ${((activeTuningCandidate?.walk_forward_stability_adjusted_score ?? tuningSummary.walk_forward_stability_adjusted_score) ?? 0).toFixed(4)}`
                          : ""
                      } \u00b7 \u65b9\u6848\u4e2d\u5956\u7387 ${((((activeTuningCandidate?.walk_forward_overall_win_rate ?? tuningSummary.walk_forward_overall_win_rate ?? 0) * 100))).toFixed(
                        2,
                      )}% \u00b7 \u671f\u53f7\u547d\u4e2d\u7387 ${((((activeTuningCandidate?.walk_forward_issue_hit_rate ?? tuningSummary.walk_forward_issue_hit_rate ?? 0) * 100))).toFixed(2)}%${
                        (activeTuningCandidate?.walk_forward_performance_score ?? null) !== null
                          ? ` \u00b7 \u8868\u73b0 ${(activeTuningCandidate?.walk_forward_performance_score ?? 0).toFixed(4)}`
                          : ""
                      }${
                        (activeTuningCandidate?.walk_forward_coverage_score ?? null) !== null
                          ? ` \u00b7 \u8986\u76d6 ${(activeTuningCandidate?.walk_forward_coverage_score ?? 0).toFixed(4)}`
                          : ""
                      }${
                        activeTuningCandidate?.walk_forward_coverage_components
                          ? ` \u00b7 \u524d ${compactScore(activeTuningCandidate.walk_forward_coverage_components.front_diversity)} / \u540e ${compactScore(activeTuningCandidate.walk_forward_coverage_components.back_diversity)} / \u5bf9 ${compactScore(activeTuningCandidate.walk_forward_coverage_components.back_pair_diversity)} / \u65b0 ${compactScore(activeTuningCandidate.walk_forward_coverage_components.fresh_back)}`
                          : ""
                      }${
                        (activeTuningCandidate?.walk_forward_stability ?? tuningSummary.walk_forward_stability)
                          ? ` \u00b7 ${activeTuningCandidate?.walk_forward_stability ?? tuningSummary.walk_forward_stability} \u00b7 \u5206\u5dee ${((activeTuningCandidate?.walk_forward_score_range ?? tuningSummary.walk_forward_score_range) ?? 0).toFixed(4)}`
                          : ""
                      }${
                        (activeTuningCandidate?.walk_forward_max_drawdown ?? tuningSummary.walk_forward_max_drawdown ?? null) !== null
                          ? ` \u00b7 \u56de\u64a4 ${((activeTuningCandidate?.walk_forward_max_drawdown ?? tuningSummary.walk_forward_max_drawdown) ?? 0).toFixed(2)}`
                          : ""
                      }${
                        (activeTuningCandidate?.walk_forward_max_miss_streak ?? tuningSummary.walk_forward_max_miss_streak ?? null) !== null
                          ? ` \u00b7 \u7a7a\u7a97 ${((activeTuningCandidate?.walk_forward_max_miss_streak ?? tuningSummary.walk_forward_max_miss_streak) ?? 0)}`
                          : ""
                      }${
                        stabilityBreakdownLabel(activeTuningCandidate?.walk_forward_stability_breakdown ?? tuningSummary.walk_forward_stability_breakdown)
                          ? ` \u00b7 ${stabilityBreakdownLabel(activeTuningCandidate?.walk_forward_stability_breakdown ?? tuningSummary.walk_forward_stability_breakdown)}`
                          : ""
                      }`}
                    </p>
                  ) : null}
                </div>
              </div>
              <div className="mt-4 rounded-2xl border border-slate-200 bg-white px-4 py-4">
                <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  {Object.entries(tuningSummary.weights ?? {}).map(([key, value]) => (
                    <div key={key}>
                      <p className="text-xs text-slate-500">{key}</p>
                      <p className="mt-1 font-semibold text-slate-900">{value.toFixed(2)}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="text-xs text-slate-500">覆盖对比维度</span>
                <button
                  type="button"
                  onClick={() => setTuningCompareDimension("train")}
                  className={`rounded-2xl border px-3 py-1 text-xs font-medium ${
                    tuningCompareDimension === "train"
                      ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                      : "border-slate-200 bg-white text-slate-600"
                  }`}
                >
                  {"训练"}
                </button>
                {hasValidationComparison ? (
                  <button
                    type="button"
                    onClick={() => setTuningCompareDimension("validation")}
                    className={`rounded-2xl border px-3 py-1 text-xs font-medium ${
                      tuningCompareDimension === "validation"
                        ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                        : "border-slate-200 bg-white text-slate-600"
                    }`}
                  >
                    {"验证"}
                  </button>
                ) : null}
                {hasWalkForwardComparison ? (
                  <button
                    type="button"
                    onClick={() => setTuningCompareDimension("walk_forward")}
                    className={`rounded-2xl border px-3 py-1 text-xs font-medium ${
                      tuningCompareDimension === "walk_forward"
                        ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                        : "border-slate-200 bg-white text-slate-600"
                    }`}
                  >
                    {"滚动"}
                  </button>
                ) : null}
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {tuningProfiles.map((item) => (
                  (() => {
                    const comparisonTarget =
                      item.name === leadTuningCandidate?.name ? runnerUpTuningCandidate : leadTuningCandidate;
                    const itemPerformanceMetrics = getPerformanceMetricsByDimension(item, tuningCompareDimension);
                    const targetPerformanceMetrics = getPerformanceMetricsByDimension(comparisonTarget, tuningCompareDimension);
                    const itemCoverageComponents = getCoverageComponentsByDimension(item, tuningCompareDimension);
                    const targetCoverageComponents = getCoverageComponentsByDimension(comparisonTarget, tuningCompareDimension);
                    const performanceComparison =
                      itemPerformanceMetrics && targetPerformanceMetrics
                        ? [
                            {
                              key: "performance",
                              label: "表现",
                              value: itemPerformanceMetrics.performanceScore - targetPerformanceMetrics.performanceScore,
                            },
                            {
                              key: "win",
                              label: "方案",
                              value: itemPerformanceMetrics.overallWinRate - targetPerformanceMetrics.overallWinRate,
                            },
                            {
                              key: "issue",
                              label: "期号",
                              value: itemPerformanceMetrics.issueHitRate - targetPerformanceMetrics.issueHitRate,
                            },
                          ]
                        : [];
                    const coverageComparison =
                      itemCoverageComponents && targetCoverageComponents
                        ? [
                            {
                              key: "front",
                              label: "前区",
                              value: itemCoverageComponents.front_diversity - targetCoverageComponents.front_diversity,
                            },
                            {
                              key: "back",
                              label: "后区",
                              value: itemCoverageComponents.back_diversity - targetCoverageComponents.back_diversity,
                            },
                            {
                              key: "pair",
                              label: "对子",
                              value: itemCoverageComponents.back_pair_diversity - targetCoverageComponents.back_pair_diversity,
                            },
                            {
                              key: "fresh",
                              label: "新号",
                              value: itemCoverageComponents.fresh_back - targetCoverageComponents.fresh_back,
                            },
                          ]
                        : [];
                    const comparisonSummary = comparisonTarget
                      ? buildComparisonSummary(
                          tuningCompareDimension,
                          comparisonTarget.display_name,
                          performanceComparison,
                          coverageComparison,
                        )
                      : null;
                    const comparisonSummaryTone = getComparisonSummaryTone(performanceComparison, coverageComparison);
                    return (
                      <div
                        key={item.name}
                        className={`rounded-2xl border px-4 py-4 ${
                          item.name === activeTuningProfileName
                            ? tuningView === "compare"
                              ? "border-amber-300 bg-amber-50"
                              : "border-cyan-300 bg-cyan-50"
                            : item.name === tuningSummary.selected_profile
                              ? "border-cyan-200 bg-cyan-50/50"
                              : "border-slate-200 bg-white"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-medium text-slate-900">{item.display_name}</p>
                          <span className="text-xs font-medium text-slate-500">{item.score.toFixed(4)}</span>
                        </div>
                        {comparisonTarget && (performanceComparison.length > 0 || coverageComparison.length > 0) ? (
                          <div className="mt-3">
                            {comparisonSummary ? (
                              <p
                                className={`mb-2 text-[11px] ${
                                  comparisonSummaryTone === "positive"
                                    ? "text-emerald-700"
                                    : comparisonSummaryTone === "negative"
                                      ? "text-rose-600"
                                      : "text-slate-600"
                                }`}
                              >
                                {comparisonSummary}
                              </p>
                            ) : null}
                            <div className="grid gap-2 sm:grid-cols-2">
                            {performanceComparison.length > 0 ? (
                              <div className="rounded-xl border border-slate-200/80 bg-slate-50 px-3 py-2">
                                <p className="text-[11px] text-slate-500">{`${comparisonDimensionLabel(tuningCompareDimension)}表现对比 ${comparisonTarget.display_name}`}</p>
                                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
                                  {performanceComparison.map((part) => (
                                    <span key={part.key} className={coverageDeltaClass(part.value)}>
                                      {`${part.label} ${signedCompactScore(part.value)}`}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                            {coverageComparison.length > 0 ? (
                              <div className="rounded-xl border border-slate-200/80 bg-slate-50 px-3 py-2">
                                <p className="text-[11px] text-slate-500">{`${comparisonDimensionLabel(tuningCompareDimension)}覆盖对比 ${comparisonTarget.display_name}`}</p>
                                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
                                  {coverageComparison.map((part) => (
                                    <span key={part.key} className={coverageDeltaClass(part.value)}>
                                      {`${part.label} ${signedCompactScore(part.value)}`}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                            </div>
                          </div>
                        ) : null}
                        <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <p className="text-xs text-slate-500">{"\u8bad\u7ec3-\u8868\u73b0\u5206"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{(item.performance_score ?? 0).toFixed(4)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u8bad\u7ec3-\u8986\u76d6\u5206"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{(item.coverage_score ?? 0).toFixed(4)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u8bad\u7ec3-\u524d/\u540e/\u5bf9/\u65b0"}</p>
                        <p className="mt-1 font-semibold text-slate-900">
                          {item.coverage_components
                            ? `${compactScore(item.coverage_components.front_diversity)} / ${compactScore(item.coverage_components.back_diversity)} / ${compactScore(item.coverage_components.back_pair_diversity)} / ${compactScore(item.coverage_components.fresh_back)}`
                            : "-"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u8bad\u7ec3-\u65b9\u6848\u4e2d\u5956\u7387"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{(item.overall_win_rate * 100).toFixed(2)}%</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u8bad\u7ec3-\u671f\u53f7\u547d\u4e2d\u7387"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{(item.issue_hit_rate * 100).toFixed(2)}%</p>
                      </div>
                      {(item.validation_score ?? null) !== null ? (
                        <>
                          <div>
                            <p className="text-xs text-slate-500">{"\u9a8c\u8bc1\u5206"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {(item.validation_stability_adjusted_score ?? item.validation_score ?? 0).toFixed(4)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">{"\u9a8c\u8bc1-\u671f\u53f7\u547d\u4e2d\u7387"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {((item.validation_issue_hit_rate ?? 0) * 100).toFixed(2)}%
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">{"\u9a8c\u8bc1-\u8868\u73b0/\u8986\u76d6"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {`${(item.validation_performance_score ?? 0).toFixed(4)} / ${(item.validation_coverage_score ?? 0).toFixed(4)}`}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">{"\u9a8c\u8bc1-\u56de\u64a4/\u7a7a\u7a97"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {`${(item.validation_max_drawdown ?? 0).toFixed(2)} / ${item.validation_max_miss_streak ?? 0}`}
                            </p>
                            <p className="mt-1 text-[11px] leading-5 text-slate-500">
                              {stabilityBreakdownLabel(item.validation_stability_breakdown)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">{"\u9a8c\u8bc1-\u524d/\u540e/\u5bf9/\u65b0"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {item.validation_coverage_components
                                ? `${compactScore(item.validation_coverage_components.front_diversity)} / ${compactScore(item.validation_coverage_components.back_diversity)} / ${compactScore(item.validation_coverage_components.back_pair_diversity)} / ${compactScore(item.validation_coverage_components.fresh_back)}`
                                : "-"}
                            </p>
                          </div>
                        </>
                      ) : null}
                      {(item.walk_forward_score ?? null) !== null ? (
                        <>
                          <div>
                            <p className="text-xs text-slate-500">{"Walk-forward"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {(item.walk_forward_stability_adjusted_score ?? item.walk_forward_score ?? 0).toFixed(4)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">{"\u6eda\u52a8-\u671f\u53f7\u547d\u4e2d\u7387"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {((item.walk_forward_issue_hit_rate ?? 0) * 100).toFixed(2)}%
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">{"\u6eda\u52a8-\u7a33\u5b9a\u6027"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {item.walk_forward_stability
                                ? `${item.walk_forward_stability} / ${(item.walk_forward_score_range ?? 0).toFixed(4)}`
                                : "-"}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">{"\u6eda\u52a8-\u8868\u73b0/\u8986\u76d6"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {`${(item.walk_forward_performance_score ?? 0).toFixed(4)} / ${(item.walk_forward_coverage_score ?? 0).toFixed(4)}`}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">{"\u6eda\u52a8-\u56de\u64a4/\u7a7a\u7a97"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {`${(item.walk_forward_max_drawdown ?? 0).toFixed(2)} / ${item.walk_forward_max_miss_streak ?? 0}`}
                            </p>
                            <p className="mt-1 text-[11px] leading-5 text-slate-500">
                              {stabilityBreakdownLabel(item.walk_forward_stability_breakdown)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">{"\u6eda\u52a8-\u524d/\u540e/\u5bf9/\u65b0"}</p>
                            <p className="mt-1 font-semibold text-slate-900">
                              {item.walk_forward_coverage_components
                                ? `${compactScore(item.walk_forward_coverage_components.front_diversity)} / ${compactScore(item.walk_forward_coverage_components.back_diversity)} / ${compactScore(item.walk_forward_coverage_components.back_pair_diversity)} / ${compactScore(item.walk_forward_coverage_components.fresh_back)}`
                                : "-"}
                            </p>
                          </div>
                        </>
                      ) : null}
                        </div>
                      </div>
                    );
                  })()
                ))}
              </div>
              {(tuningSummary.walk_forward_details?.length ?? 0) > 0 ? (
                <div className="mt-4 rounded-2xl border border-slate-200 bg-white px-4 py-4">
                  <p className="text-sm font-medium text-slate-900">{"Walk-forward \u660e\u7ec6"}</p>
                  {activeWalkForwardDetail ? (
                    <p className="mt-1 text-xs text-slate-500">{`\u5df2\u7f6e\u9876\u5f53\u524d\u67e5\u770b\u65b9\u6848\uff1a${activeWalkForwardDetail.display_name}`}</p>
                  ) : null}
                  <div className="mt-4 space-y-4">
                    {visibleWalkForwardDetails.map((detail) => (
                      <div
                        key={detail.name}
                        className={`overflow-hidden rounded-2xl border ${
                          detail.name === activeTuningProfileName
                            ? tuningView === "compare"
                              ? "border-amber-300"
                              : "border-cyan-300"
                            : "border-slate-200"
                        }`}
                      >
                        <div
                          className={`border-b px-4 py-3 ${
                            detail.name === activeTuningProfileName
                              ? tuningView === "compare"
                                ? "border-amber-200 bg-amber-50"
                                : "border-cyan-200 bg-cyan-50"
                              : "border-slate-200 bg-slate-50"
                          }`}
                        >
                          <p className="text-sm font-medium text-slate-900">{detail.display_name}</p>
                          {detail.stability ? (
                            <p className="mt-1 text-xs text-slate-500">
                              {`${detail.stability} \u00b7 \u5206\u5dee ${(detail.score_range ?? 0).toFixed(4)}`}
                            </p>
                          ) : null}
                        </div>
                        <div className="overflow-x-auto">
                          <table className="min-w-full text-sm">
                            <thead className="bg-white text-slate-500">
                              <tr>
                                <th className="px-4 py-3 text-left font-medium">{"\u7a97\u53e3"}</th>
                                <th className="px-4 py-3 text-left font-medium">{"\u8bad\u7ec3\u533a\u95f4"}</th>
                                <th className="px-4 py-3 text-left font-medium">{"\u6d4b\u8bd5\u533a\u95f4"}</th>
                                <th className="px-4 py-3 text-left font-medium">{"\u5206\u6570"}</th>
                                <th className="px-4 py-3 text-left font-medium">{"\u65b9\u6848\u4e2d\u5956\u7387"}</th>
                                <th className="px-4 py-3 text-left font-medium">{"\u671f\u53f7\u547d\u4e2d\u7387"}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {detail.windows.map((window) => (
                                <tr key={`${detail.name}-${window.label}`} className="border-t border-slate-200">
                                  <td className="px-4 py-3 font-medium text-slate-900">{window.label}</td>
                                  <td className="px-4 py-3 text-slate-600">{`${window.train_start_issue} - ${window.train_end_issue}`}</td>
                                  <td className="px-4 py-3 text-slate-600">{`${window.test_start_issue} - ${window.test_end_issue}`}</td>
                                  <td className="px-4 py-3 font-medium text-slate-900">{window.score.toFixed(4)}</td>
                                  <td className="px-4 py-3 text-slate-600">{(window.overall_win_rate * 100).toFixed(2)}%</td>
                                  <td className="px-4 py-3 text-slate-600">{(window.issue_hit_rate * 100).toFixed(2)}%</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              {(tuningSummary.applied_issue_comparison?.length ?? 0) > 0 ? (
                <div className="mt-4 rounded-2xl border border-slate-200 bg-white px-4 py-4">
                  <p className="text-sm font-medium text-slate-900">{"逐期差异"}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {`${tuningSummary.applied_display_name ?? "当前方案"} 对比 ${tuningSummary.selected_display_name ?? "自动方案"}，按单期奖金差排序`}
                  </p>
                  <div className="mt-4 overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead className="bg-white text-slate-500">
                        <tr>
                          <th className="px-4 py-3 text-left font-medium">{"期号"}</th>
                          <th className="px-4 py-3 text-left font-medium">{"当前方案"}</th>
                          <th className="px-4 py-3 text-left font-medium">{"自动方案"}</th>
                          <th className="px-4 py-3 text-left font-medium">{"奖金差"}</th>
                          <th className="px-4 py-3 text-left font-medium">{"命中差"}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(tuningSummary.applied_issue_comparison ?? []).map((row) => (
                          <tr key={row.issue} className="border-t border-slate-200">
                            <td className="px-4 py-3 font-medium text-slate-900">{row.issue}</td>
                            <td className="px-4 py-3 text-slate-600">
                              {`${row.applied.best_prize_amount ?? 0} / ${row.applied.won_count}`}
                            </td>
                            <td className="px-4 py-3 text-slate-600">
                              {`${row.selected.best_prize_amount ?? 0} / ${row.selected.won_count}`}
                            </td>
                            <td className={`px-4 py-3 font-medium ${row.prize_amount_delta >= 0 ? "text-emerald-700" : "text-rose-600"}`}>
                              {`${row.prize_amount_delta >= 0 ? "+" : ""}${row.prize_amount_delta.toFixed(2)}`}
                            </td>
                            <td className={`px-4 py-3 font-medium ${row.won_count_delta >= 0 ? "text-emerald-700" : "text-rose-600"}`}>
                              {`${row.won_count_delta >= 0 ? "+" : ""}${row.won_count_delta}`}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {modeComparison.length > 0 ? (
            <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm font-medium text-slate-900">{"\u6a21\u5f0f\u5bf9\u6bd4"}</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {modeComparison.map((item) => (
                  <div key={item.strategy_mode} className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <p className="text-sm font-medium text-slate-900">
                      {item.strategy_mode === "single_hit" ? "\u5355\u6ce8\u4f18\u5148" : "\u591a\u6ce8\u8986\u76d6"}
                    </p>
                    <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <p className="text-xs text-slate-500">{"\u65b9\u6848\u4e2d\u5956\u7387"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{(item.overall_win_rate * 100).toFixed(2)}%</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u671f\u53f7\u547d\u4e2d\u7387"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{(item.issue_hit_rate * 100).toFixed(2)}%</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u4e2d\u5956\u65b9\u6848"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{item.won_schemes}</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u76c8\u4e8f"}</p>
                        <p className={`mt-1 font-semibold ${(item.net_profit ?? 0) >= 0 ? "text-emerald-700" : "text-rose-600"}`}>
                          {`${(item.net_profit ?? 0) >= 0 ? "+" : ""}${(item.net_profit ?? 0).toFixed(2)}`}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u540e\u533a\u5e73\u5747\u91cd\u53e0"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{fixedNumber(item.coverage_metrics?.back_pairwise_overlap_avg)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">{"\u540e\u533a\u590d\u7528\u7387"}</p>
                        <p className="mt-1 font-semibold text-slate-900">{rateLabel(item.coverage_metrics?.back_pair_reuse_rate)}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {issueComparison.length > 0 ? (
            <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-slate-900">{"\u6309\u671f\u5206\u6b67"}</p>
                <span className="text-xs text-slate-500">{`\u7b5b\u9009\u540e ${filteredIssueComparison.length} / ${issueComparison.length} \u671f`}</span>
              </div>
              {comparisonInsight ? (
                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <p className="text-xs text-slate-500">{`${modeLabel(comparisonInsight.primaryMode)}\u5360\u4f18`}</p>
                    <p className="mt-2 text-2xl font-semibold text-slate-900">{comparisonInsight.primaryWinCount}</p>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <p className="text-xs text-slate-500">{`${modeLabel(comparisonInsight.secondaryMode)}\u5360\u4f18`}</p>
                    <p className="mt-2 text-2xl font-semibold text-slate-900">{comparisonInsight.secondaryWinCount}</p>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <p className="text-xs text-slate-500">{"\u5956\u91d1\u6301\u5e73"}</p>
                    <p className="mt-2 text-2xl font-semibold text-slate-900">{comparisonInsight.tieCount}</p>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <p className="text-xs text-slate-500">{`${modeLabel(comparisonInsight.primaryMode)}\u5e73\u5747\u5dee\u989d`}</p>
                    <p className={`mt-2 text-2xl font-semibold ${comparisonInsight.avgDelta >= 0 ? "text-emerald-700" : "text-rose-600"}`}>
                      {`${comparisonInsight.avgDelta >= 0 ? "+" : ""}${comparisonInsight.avgDelta.toFixed(2)}`}
                    </p>
                  </div>
                </div>
              ) : null}
              {comparisonInsight ? (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <p className="text-xs text-slate-500">{`${modeLabel(comparisonInsight.primaryMode)}\u6700\u5927\u5355\u671f\u4f18\u52bf`}</p>
                    <p className="mt-2 text-sm font-medium text-slate-900">
                      {comparisonInsight.strongestPrimary
                        ? `\u7b2c ${comparisonInsight.strongestPrimary.issue} \u671f / +${comparisonInsight.strongestPrimary.prize_amount_delta.toFixed(2)}`
                        : "\u6682\u65e0"}
                    </p>
                  </div>
                  <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <p className="text-xs text-slate-500">{`${modeLabel(comparisonInsight.secondaryMode)}\u6700\u5927\u5355\u671f\u4f18\u52bf`}</p>
                    <p className="mt-2 text-sm font-medium text-slate-900">
                      {comparisonInsight.strongestSecondary
                        ? `\u7b2c ${comparisonInsight.strongestSecondary.issue} \u671f / +${Math.abs(comparisonInsight.strongestSecondary.prize_amount_delta).toFixed(2)}`
                        : "\u6682\u65e0"}
                    </p>
                  </div>
                </div>
              ) : null}
              <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_180px_180px]">
                <div className="flex flex-wrap gap-2">
                  {[
                    { value: "all", label: "\u5168\u90e8" },
                    { value: "primary", label: "\u53ea\u770b\u5f53\u524d\u6a21\u5f0f\u5360\u4f18" },
                    { value: "secondary", label: "\u53ea\u770b\u5bf9\u7167\u6a21\u5f0f\u5360\u4f18" },
                    { value: "same", label: "\u53ea\u770b\u5956\u91d1\u6301\u5e73" },
                  ].map((option) => (
                    <button
                      key={option.value}
                      onClick={() => setComparisonFilter(option.value as "all" | "primary" | "secondary" | "same")}
                      className={`rounded-full border px-3 py-1.5 text-xs ${
                        comparisonFilter === option.value
                          ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                          : "border-slate-200 bg-white text-slate-500"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <label className="grid gap-1 rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <span className="text-xs text-slate-500">{"\u6700\u5c0f\u5956\u91d1\u5dee\u989d"}</span>
                  <input
                    type="number"
                    min={0}
                    step={5}
                    value={comparisonThreshold}
                    onChange={(event) => setComparisonThreshold(Math.max(0, Number(event.target.value) || 0))}
                    className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-900 outline-none"
                  />
                </label>
                <label className="grid gap-1 rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <span className="text-xs text-slate-500">{"\u6392\u5e8f\u65b9\u5f0f"}</span>
                  <select
                    value={comparisonSort}
                    onChange={(event) => setComparisonSort(event.target.value as "prize_delta" | "won_delta" | "date_desc" | "date_asc")}
                    className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-900 outline-none"
                  >
                    <option value="prize_delta">{"\u6309\u5956\u91d1\u5dee\u989d"}</option>
                    <option value="won_delta">{"\u6309\u547d\u4e2d\u6570\u5dee\u989d"}</option>
                    <option value="date_desc">{"\u6309\u65e5\u671f\u7531\u65b0\u5230\u65e7"}</option>
                    <option value="date_asc">{"\u6309\u65e5\u671f\u7531\u65e7\u5230\u65b0"}</option>
                  </select>
                </label>
              </div>
              <div className="mt-4 grid gap-3">
                {filteredIssueComparison.slice(0, 12).map((row) => (
                  <div key={row.issue} className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{`\u7b2c ${row.issue} \u671f`}</p>
                        <p className="mt-1 text-xs text-slate-500">{row.draw_date}</p>
                      </div>
                      <div className={`rounded-full px-3 py-1 text-xs font-medium ${
                        row.prize_amount_delta > 0
                          ? "bg-emerald-50 text-emerald-700"
                          : row.prize_amount_delta < 0
                            ? "bg-rose-50 text-rose-600"
                            : "bg-slate-100 text-slate-600"
                      }`}>
                        {`\u5956\u91d1\u5dee\u989d ${row.prize_amount_delta > 0 ? "+" : ""}${row.prize_amount_delta.toFixed(2)}`}
                      </div>
                    </div>
                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      {[row.primary, row.secondary].map((item) => {
                        const amount = item.best_prize_amount ?? 0;
                        return (
                          <div key={item.strategy_mode} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
                            <p className="text-xs text-slate-500">
                              {modeLabel(item.strategy_mode)}
                            </p>
                            <p className="mt-2 text-sm font-medium text-slate-900">
                              {item.best_prize_level ? `${item.best_prize_level} / ${amount.toFixed(2)}` : "\u672a\u4e2d\u5956"}
                            </p>
                            <p className="mt-1 text-xs text-slate-500">{`\u547d\u4e2d ${item.won_count} / ${result?.scheme_count ?? 0}`}</p>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
                {filteredIssueComparison.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-8 text-sm text-slate-500">
                    {"\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u4e0b\u6682\u65e0\u5206\u6b67\u671f\u53f7\u3002"}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}

          {result ? (
            <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm font-medium text-slate-900">{"\u57fa\u7ebf\u5bf9\u7167"}</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                  <p className="text-xs text-slate-500">{"\u7406\u8bba\u5355\u6ce8\u4e2d\u5956\u7387"}</p>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">
                    {((result.theoretical_single_win_rate ?? 0) * 100).toFixed(2)}%
                  </p>
                </div>
                {benchmarks.map((benchmark) => {
                  const delta = (result.overall_win_rate ?? 0) - benchmark.overall_win_rate;
                  return (
                    <div key={benchmark.name} className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                      <p className="text-xs text-slate-500">{benchmark.display_name}</p>
                      <p className="mt-2 text-2xl font-semibold text-slate-900">
                        {(benchmark.overall_win_rate * 100).toFixed(2)}%
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {`\u671f\u53f7\u547d\u4e2d ${(benchmark.issue_hit_rate * 100).toFixed(2)}%`}
                        {benchmark.sample_runs && benchmark.sample_runs > 1 ? ` / ${benchmark.sample_runs} \u6b21\u5747\u503c` : ""}
                      </p>
                      <p className={`mt-2 text-sm font-medium ${delta >= 0 ? "text-emerald-700" : "text-rose-600"}`}>
                        {`\u5f53\u524d\u7b56\u7565 ${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(2)}%`}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {result ? (
            <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm font-medium text-slate-900">{"\u5956\u7ea7\u5206\u5e03"}</p>
              <div className="mt-4 space-y-3">
                {result.prize_rates.map((item) => (
                  <div key={item.level} className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-sm font-medium text-slate-900">{item.level}</span>
                      <span className="text-sm text-slate-600">{(item.rate * 100).toFixed(2)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs text-slate-500">{"\u5b9e\u9645\u4e0b\u6ce8\u671f\u6570"}</p>
              <p className="mt-2 text-2xl font-semibold text-slate-900">{result?.total_issues ?? 0}</p>
              <p className="mt-1 text-xs text-slate-500">
                {`${result?.requested_issues ?? result?.recent_issues ?? 0} 期样本`}
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs text-slate-500">{"\u751f\u6210\u65b9\u6848"}</p>
              <p className="mt-2 text-2xl font-semibold text-slate-900">{result?.total_generated_schemes ?? 0}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs text-slate-500">{"\u4e2d\u5956\u65b9\u6848"}</p>
              <p className="mt-2 text-2xl font-semibold text-emerald-700">{result?.won_schemes ?? 0}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs text-slate-500">{"\u8df3\u8fc7\u4f4e\u7f6e\u4fe1\u671f\u6570"}</p>
              <p className="mt-2 text-2xl font-semibold text-slate-900">{result?.skipped_issues ?? 0}</p>
            </div>
            <div className="rounded-2xl border border-cyan-200 bg-cyan-50 px-4 py-4">
              <p className="text-xs text-cyan-700">{"\u7f6e\u4fe1\u5ea6\u9608\u503c"}</p>
              <p className="mt-2 text-2xl font-semibold text-cyan-700">
                {fixedNumber((result?.confidence_threshold ?? 0) * 100)}%
              </p>
              {result?.threshold_selection_reason ? (
                <p className="mt-1 text-xs leading-5 text-cyan-800">{result.threshold_selection_reason}</p>
              ) : null}
            </div>
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-4">
              <p className="text-xs text-rose-700">{"\u6d88\u8d39\u91d1\u989d\uff08\u5143\uff09"}</p>
              <p className="mt-2 text-2xl font-semibold text-rose-700">{result ? (result.total_cost ?? 0).toFixed(2) : "0.00"}</p>
            </div>
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4">
              <p className="text-xs text-amber-700">{"\u7d2f\u8ba1\u5956\u91d1\uff08\u5143\uff09"}</p>
              <p className="mt-2 text-2xl font-semibold text-amber-700">{result ? result.total_prize_amount.toFixed(2) : "0.00"}</p>
            </div>
            <div className="rounded-2xl border border-violet-200 bg-violet-50 px-4 py-4">
              <p className="text-xs text-violet-700">{"\u6700\u5927\u56de\u64a4\uff08\u5143\uff09"}</p>
              <p className="mt-2 text-2xl font-semibold text-violet-700">{result ? (result.max_drawdown ?? 0).toFixed(2) : "0.00"}</p>
            </div>
            <div className="rounded-2xl border border-slate-300 bg-white px-4 py-4">
              <p className="text-xs text-slate-500">{"\u6700\u957f\u7a7a\u7a97"}</p>
              <p className="mt-2 text-2xl font-semibold text-slate-900">{String(result?.max_miss_streak ?? 0) + " 期"}</p>
              {result?.stability_breakdown ? (
                <p className="mt-2 text-[11px] leading-5 text-slate-500">{stabilityBreakdownLabel(result.stability_breakdown)}</p>
              ) : null}
            </div>
            <div className={`rounded-2xl border px-4 py-4 ${
              (result?.net_profit ?? 0) >= 0
                ? "border-emerald-200 bg-emerald-50"
                : "border-slate-200 bg-slate-50"
            }`}>
              <p className={`text-xs ${(result?.net_profit ?? 0) >= 0 ? "text-emerald-700" : "text-slate-500"}`}>{"\u76c8\u4e8f\uff08\u5143\uff09"}</p>
              <p className={`mt-2 text-2xl font-semibold ${
                (result?.net_profit ?? 0) >= 0 ? "text-emerald-700" : "text-rose-600"
              }`}>
                {result ? `${(result.net_profit ?? 0) >= 0 ? "+" : ""}${(result.net_profit ?? 0).toFixed(2)}` : "0.00"}
              </p>
              {result?.policy_selection_reason ? (
                <p className="mt-1 text-xs leading-5 text-slate-600">{result.policy_selection_reason}</p>
              ) : null}
            </div>
          </div>

          <div className="min-w-0 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-900">{"\u56de\u6d4b\u660e\u7ec6"}</p>
              <span className="text-xs text-slate-500">{result ? `\u7b5b\u9009\u540e ${visibleIssues.length} / ${result.issues.length} \u671f` : "\u7b49\u5f85\u751f\u6210"}</span>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {[
                { value: "all", label: "\u5168\u90e8" },
                { value: "won", label: "\u53ea\u770b\u4e2d\u5956\u671f" },
                { value: "not_won", label: "\u53ea\u770b\u672a\u4e2d\u5956\u671f" },
              ].map((option) => (
                <button
                  key={option.value}
                  onClick={() => setResultFilter(option.value as "all" | "won" | "not_won")}
                  className={`rounded-full border px-3 py-1.5 text-xs ${
                    resultFilter === option.value
                      ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                      : "border-slate-200 bg-white text-slate-500"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="mt-4 grid gap-3">
              {!result ? (
                <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-8 text-sm text-slate-500">
                  {"\u8bbe\u5b9a\u671f\u6570\u548c\u65b9\u6848\u7ec4\u6570\u540e\uff0c\u5728\u8fd9\u91cc\u67e5\u770b\u56de\u6d4b\u660e\u7ec6\u3002"}
                </div>
              ) : (
                visibleIssues.map((item) => {
                  const prize = item.best_prize_amount ?? 0;
                  const cost = item.cost ?? 0;
                  const net = prize - cost;
                  return (
                    <div key={item.issue} className="min-w-0 rounded-2xl border border-slate-200 bg-white px-4 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-slate-900">{`\u7b2c ${item.issue} \u671f`}</p>
                          <p className="mt-1 text-xs text-slate-500">{item.draw_date}</p>
                        </div>
                        <div className="text-right">
                          <p className="text-sm text-slate-700">
                            {item.best_prize_level ? `${item.best_prize_level} / ${prize.toFixed(2)}` : "\u672a\u4e2d\u5956"}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">{`\u547d\u4e2d ${item.won_count} / ${item.scheme_count}`}</p>
                        </div>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-2 text-xs">
                        <span className="text-rose-600">{`\u6d88\u8d39 ${cost.toFixed(2)} \u5143`}</span>
                        <span className="text-amber-600">{`\u5956\u91d1 ${prize.toFixed(2)} \u5143`}</span>
                        <span className={net >= 0 ? "font-medium text-emerald-700" : "font-medium text-rose-600"}>
                          {`\u76c8\u4e8f ${net >= 0 ? "+" : ""}${net.toFixed(2)} \u5143`}
                        </span>
                        <span className="text-slate-500">{`\u539f\u59cb\u7f6e\u4fe1 ${fixedNumber((item.issue_confidence ?? 0) * 100)}%`}</span>
                        <span className="text-slate-500">{`\u6821\u51c6\u7f6e\u4fe1 ${fixedNumber((item.calibrated_confidence ?? 0) * 100)}%`}</span>
                        <span className="text-slate-500">{`\u9608\u503c ${fixedNumber((item.applied_threshold ?? 0) * 100)}%`}</span>
                        <span className="text-slate-500">{`\u524d\u91cd\u53e0 ${((item.front_pairwise_overlap_avg ?? 0)).toFixed(2)}`}</span>
                        <span className="text-slate-500">{`\u540e\u91cd\u53e0 ${((item.back_pairwise_overlap_avg ?? 0)).toFixed(2)}`}</span>
                        <span className="text-slate-500">{`\u540e\u533a\u590d\u7528 ${rateLabel(item.back_pair_reuse_rate)}`}</span>
                        <span className="text-slate-500">{`\u65b0\u540e\u53f7 ${rateLabel(item.fresh_back_number_rate)}`}</span>
                      </div>
                      {(item.tuning_profile || item.decision_reason || item.front_confidence != null || item.back_confidence != null) ? (
                        <div className="mt-3 min-w-0 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-600">
                          <div className="flex flex-wrap gap-2">
                            {item.tuning_profile ? (
                              <span className="rounded-full border border-slate-200 bg-white px-3 py-1">{`调参 ${item.tuning_profile}`}</span>
                            ) : null}
                            {item.count_policy ? (
                              <span className="rounded-full border border-slate-200 bg-white px-3 py-1">{`策略 ${item.count_policy}`}</span>
                            ) : null}
                            {item.decision_tier ? (
                              <span className="rounded-full border border-slate-200 bg-white px-3 py-1">{`层级 ${item.decision_tier}`}</span>
                            ) : null}
                            {item.front_calibrated_confidence != null && item.front_gate != null ? (
                              <span className="rounded-full border border-slate-200 bg-white px-3 py-1">
                                {`前区 ${item.front_calibrated_confidence.toFixed(3)} / ${item.front_gate.toFixed(3)}`}
                              </span>
                            ) : null}
                            {item.back_calibrated_confidence != null && item.back_gate != null ? (
                              <span className="rounded-full border border-slate-200 bg-white px-3 py-1">
                                {`后区 ${item.back_calibrated_confidence.toFixed(3)} / ${item.back_gate.toFixed(3)}`}
                              </span>
                            ) : null}
                            <span className="rounded-full border border-slate-200 bg-white px-3 py-1">
                              {item.deep_search_triggered ? "已深搜" : "未深搜"}
                            </span>
                            <span className="rounded-full border border-slate-200 bg-white px-3 py-1">
                              {item.should_observe ? "观察中" : "未观察"}
                            </span>
                          </div>
                          {item.decision_reason ? <p className="mt-2 leading-6 text-slate-500">{item.decision_reason}</p> : null}
                          {item.deep_search_reason ? <p className="mt-1 leading-6 text-slate-400">{item.deep_search_reason}</p> : null}
                        </div>
                      ) : null}
                    </div>
                  );
                })
              )}
            </div>
          </div>
          {result ? (
            <div className="min-w-0 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-slate-900">{"\u9608\u503c\u626b\u63cf"}</p>
                <span className="text-xs text-slate-500">{"\u9ed8\u8ba4\u6309\u4fee\u6b63\u540e\u5206\u6392\u5e8f\uff0c\u5f53\u524d\u91c7\u7528\u9608\u503c\u4f1a\u9ad8\u4eae"}</span>
              </div>
              {thresholdTradeoffSummary && activeThresholdRow && bestThresholdRow ? (
                <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  {`当前采用 ${fixedNumber((activeThresholdRow.threshold ?? 0) * 100)}%，最高分阈值是 ${fixedNumber((bestThresholdRow.threshold ?? 0) * 100)}%。当前方案少 ${thresholdTradeoffSummary.scoreGap.toFixed(4)} 分，但回撤改善 ${Math.max(0, thresholdTradeoffSummary.drawdownDelta).toFixed(2)}，空窗改善 ${Math.max(0, thresholdTradeoffSummary.missDelta)} 期。`}
                </div>
              ) : null}
              <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200 bg-white">
                <table className="min-w-[1120px] text-sm">
                  <thead className="bg-slate-50 text-left text-slate-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">{"\u9608\u503c"}</th>
                      <th className="px-4 py-3 font-medium">{"\u5b9e\u9645\u4e0b\u6ce8\u671f\u6570"}</th>
                      <th className="px-4 py-3 font-medium">{"\u8df3\u8fc7"}</th>
                      <th className="px-4 py-3 font-medium">{"\u5e73\u5747\u6bcf\u671f\u6ce8\u6570"}</th>
                      <th className="px-4 py-3 font-medium">{"\u65b9\u6848\u4e2d\u5956\u7387"}</th>
                      <th className="px-4 py-3 font-medium">{"\u671f\u53f7\u547d\u4e2d\u7387"}</th>
                      <th className="px-4 py-3 font-medium">{"\u6210\u672c"}</th>
                      <th className="px-4 py-3 font-medium">{"\u4fee\u6b63\u540e\u5206"}</th>
                      <th className="px-4 py-3 font-medium">{"\u539f\u59cb\u5206"}</th>
                      <th className="px-4 py-3 font-medium">{"\u5206\u5dee/\u7a97\u53e3"}</th>
                      <th className="px-4 py-3 font-medium">{"\u56de\u64a4/\u60e9\u7f5a"}</th>
                      <th className="px-4 py-3 font-medium">{"\u7a7a\u7a97/\u60e9\u7f5a"}</th>
                      <th className="px-4 py-3 font-medium">{"\u7a33\u5b9a\u6807\u7b7e"}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {thresholdScan.map((item) => {
                      const isActiveThreshold = isSameThreshold(item.threshold, result?.confidence_threshold);
                      return (
                      <tr
                        key={item.threshold}
                        className={isActiveThreshold ? "border-t border-cyan-200 bg-cyan-50/70" : "border-t border-slate-100"}
                      >
                        <td className="px-4 py-3 text-slate-900">
                          <div className="flex items-center gap-2">
                            <span>{fixedNumber(item.threshold * 100)}%</span>
                            {isActiveThreshold ? (
                              <span className="rounded-full border border-cyan-200 bg-white px-2 py-0.5 text-[11px] font-medium text-cyan-700">
                                {"\u5f53\u524d"}
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-slate-600">{item.total_issues}</td>
                        <td className="px-4 py-3 text-slate-600">{item.skipped_issues ?? 0}</td>
                        <td className="px-4 py-3 text-slate-600">{fixedNumber(item.avg_scheme_count ?? 0)}</td>
                        <td className="px-4 py-3 font-medium text-slate-900">{fixedNumber(item.overall_win_rate * 100)}%</td>
                        <td className="px-4 py-3 text-slate-600">{fixedNumber(item.issue_hit_rate * 100)}%</td>
                        <td className="px-4 py-3 text-slate-600">{fixedNumber(item.total_cost ?? 0)}</td>
                        <td className="px-4 py-3 font-medium text-slate-900">{item.selection_score != null ? item.selection_score.toFixed(4) : "-"}</td>
                        <td className="px-4 py-3 text-slate-600">{item.stability_breakdown ? item.stability_breakdown.base_score.toFixed(4) : "-"}</td>
                        <td className="px-4 py-3 text-slate-600">
                          {item.score_range != null ? `${item.score_range.toFixed(4)} / -${(item.stability_breakdown?.range_penalty ?? 0).toFixed(4)}` : "-"}
                        </td>
                        <td className="px-4 py-3 text-slate-600">
                          {item.max_drawdown != null ? `${item.max_drawdown.toFixed(2)} / -${(item.stability_breakdown?.drawdown_penalty ?? 0).toFixed(4)}` : "-"}
                        </td>
                        <td className="px-4 py-3 text-slate-600">
                          {item.max_miss_streak != null ? `${item.max_miss_streak} / -${(item.stability_breakdown?.miss_streak_penalty ?? 0).toFixed(4)}` : "-"}
                        </td>
                        <td className="px-4 py-3 text-slate-600">{item.stability ?? "-"}</td>
                      </tr>
                    )})}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
      </div>
        </div>
      </div>
    </section>
  );
}

