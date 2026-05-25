import type {
  AIReplayMode,
  BacktestStrategyMode,
  BacktestJobResponse,
  BacktestPrizeLevelSummary,
  BacktestResponse,
  TicketMode,
} from "../lib/types";

interface BacktestPanelProps {
  result: BacktestResponse | null;
  loading: boolean;
  job: BacktestJobResponse | null;
  jobs: BacktestJobResponse[];
  error: string | null;
  recentIssues: number;
  schemeCount: number;
  strategyMode: BacktestStrategyMode;
  ticketMode: TicketMode;
  aiReplayMode: AIReplayMode;
  compareModes: boolean;
  multiple: number;
  onRecentIssuesChange: (value: number) => void;
  onSchemeCountChange: (value: number) => void;
  onStrategyModeChange: (value: BacktestStrategyMode) => void;
  onTicketModeChange: (value: TicketMode) => void;
  onAIReplayModeChange: (value: AIReplayMode) => void;
  onCompareModesChange: (value: boolean) => void;
  onMultipleChange: (value: number) => void;
  onRun: (tuningProfileOverride?: string | null) => void;
  onCancelJob: () => void;
  onOpenJob: (job: BacktestJobResponse) => void;
  aiEnabled?: boolean;
}

const PRIZE_LEVEL_ORDER = ["一等奖", "二等奖", "三等奖", "四等奖", "五等奖", "六等奖", "七等奖"];

function modeLabel(mode: BacktestStrategyMode) {
  if (mode === "smart_balance") return "智能平衡";
  return mode === "single_hit" ? "单注优先" : "多注覆盖";
}

function ticketModeLabel(mode: TicketMode | undefined) {
  return mode === "additional" ? "追加投注" : "基本投注";
}

function aiReplayModeLabel(mode: AIReplayMode | undefined) {
  return mode === "external_rerank" ? "AI 重排" : "仅本地";
}

function rateLabel(value: number | undefined | null, digits = 2) {
  return `${((value ?? 0) * 100).toFixed(digits)}%`;
}

function fixedAmount(value: number | null | undefined, digits = 2) {
  return (value ?? 0).toFixed(digits);
}

function jobStatusLabel(status: BacktestJobResponse["status"]) {
  if (status === "queued") return "排队中";
  if (status === "running") return "运行中";
  if (status === "canceling") return "取消中";
  if (status === "completed") return "已完成";
  if (status === "canceled") return "已取消";
  return "失败";
}

function sortPrizeLevels(items: BacktestPrizeLevelSummary[]): BacktestPrizeLevelSummary[] {
  const indexOf = (level: string) => {
    const idx = PRIZE_LEVEL_ORDER.indexOf(level);
    return idx === -1 ? PRIZE_LEVEL_ORDER.length : idx;
  };
  return [...items].sort((left, right) => indexOf(left.level) - indexOf(right.level));
}

function exportSummary(result: BacktestResponse) {
  const totalIssues = result.total_issues ?? result.recent_issues ?? 0;
  const summaryLines: string[] = [
    "指标,数值",
    `回测期数,${totalIssues}`,
    `生成方案,${result.total_generated_schemes ?? 0}`,
    `中奖方案,${result.won_schemes ?? 0}`,
    `综合中奖率(方案),${rateLabel(result.overall_win_rate)}`,
    `期命中率,${rateLabel(result.issue_hit_rate)}`,
    `消费金额,${fixedAmount(result.total_cost)}`,
    `中奖金额,${fixedAmount(result.total_prize_amount)}`,
    `盈亏金额,${fixedAmount(result.net_profit)}`,
  ];

  const modeRows = result.mode_comparison ?? [];
  if (modeRows.length > 0) {
    summaryLines.push("", "模式,方案中奖率,期命中率,中奖方案,中奖金额,盈亏");
    modeRows.forEach((item) => {
      summaryLines.push(
        [
          modeLabel(item.strategy_mode),
          rateLabel(item.overall_win_rate),
          rateLabel(item.issue_hit_rate),
          item.won_schemes,
          fixedAmount(item.total_prize_amount),
          fixedAmount(item.net_profit),
        ].join(","),
      );
    });
  }

  const breakdown = result.prize_level_breakdown ?? [];
  if (breakdown.length > 0) {
    summaryLines.push("", "奖级,中奖注数,方案中奖率,命中期数,期命中率,中奖金额");
    sortPrizeLevels(breakdown).forEach((item) => {
      summaryLines.push(
        [
          item.level,
          item.wins,
          rateLabel(item.scheme_rate),
          item.issue_hits,
          rateLabel(item.issue_rate),
          fixedAmount(item.total_prize_amount),
        ].join(","),
      );
    });
  }

  const blob = new Blob([summaryLines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `dlt-backtest-summary-${Date.now()}.csv`;
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
  multiple,
  onRecentIssuesChange,
  onSchemeCountChange,
  onStrategyModeChange,
  onTicketModeChange,
  onAIReplayModeChange,
  onCompareModesChange,
  onMultipleChange,
  onRun,
  onCancelJob,
  onOpenJob,
  aiEnabled = false,
}: BacktestPanelProps) {
  const modeComparison = result?.mode_comparison ?? [];
  const prizeLevelBreakdown = sortPrizeLevels(result?.prize_level_breakdown ?? []);
  const netProfit = result?.net_profit ?? 0;
  const unitPrice = ticketMode === "additional" ? 3 : 2;
  const costPerIssue = unitPrice * schemeCount * multiple;
  const estimatedTotalCost = costPerIssue * recentIssues;

  return (
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,0.06)]">
      {job ? (
        <div
          className={`mb-4 rounded-2xl border px-4 py-3 ${
            job.status === "failed"
              ? "border-rose-200 bg-rose-50"
              : job.status === "completed"
                ? "border-emerald-200 bg-emerald-50"
                : "border-cyan-200 bg-cyan-50"
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
              className={`h-full rounded-full ${
                job.status === "failed"
                  ? "bg-rose-500"
                  : job.status === "completed"
                    ? "bg-emerald-500"
                    : "bg-cyan-500"
              }`}
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
          <p className="text-xs tracking-[0.3em] text-cyan-700/70">历史回测</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">历史命中率测试</h2>
          <p className="mt-2 text-sm text-slate-600">仅展示汇总指标：综合中奖率、模式中奖率、累计奖金、盈亏与各奖级中奖明细。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {result ? (
            <button
              onClick={() => exportSummary(result)}
              className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-700"
            >
              导出汇总
            </button>
          ) : null}
          <button
            onClick={() => onRun()}
            disabled={loading}
            className="rounded-2xl border border-cyan-200 bg-cyan-50 px-4 py-2 text-sm font-medium text-cyan-700 disabled:opacity-60"
          >
            {loading ? "回测中..." : "开始回测"}
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
          <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-slate-900">回测控制区</p>
                <p className="mt-1 text-xs text-slate-500">把范围、投注、策略和引擎拆开设置，读起来更清楚。</p>
              </div>
              <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] text-slate-500">
                投注倍数可自由填写
              </span>
            </div>

            <div className="mt-4 grid gap-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-1.5 rounded-2xl border border-slate-200 bg-white px-3 py-3">
                  <span className="text-[11px] text-slate-500">回测期数</span>
                  <input
                    type="number"
                    min={5}
                    value={recentIssues}
                    onChange={(event) => onRecentIssuesChange(Math.max(5, Number(event.target.value) || 5))}
                    className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm font-medium text-slate-900 outline-none focus:border-cyan-300"
                  />
                </label>
                <label className="grid gap-1.5 rounded-2xl border border-slate-200 bg-white px-3 py-3">
                  <span className="text-[11px] text-slate-500">每期方案组数</span>
                  <input
                    type="number"
                    min={1}
                    value={schemeCount}
                    onChange={(event) => onSchemeCountChange(Math.max(1, Number(event.target.value) || 1))}
                    className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm font-medium text-slate-900 outline-none focus:border-cyan-300"
                  />
                </label>
              </div>

              <div className="grid gap-3 xl:grid-cols-2">
                <div className="rounded-2xl border border-cyan-200 bg-white px-4 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[11px] font-medium text-cyan-700">投注类型</p>
                    <span className="text-[11px] text-slate-400">倍数可直接填写</span>
                  </div>
                  <div className="mt-2 grid gap-2 sm:grid-cols-[minmax(0,1fr)_132px]">
                    <div className="grid grid-cols-2 gap-2">
                      {[
                        { value: "basic" as const, label: "基本", description: "2 元/注" },
                        { value: "additional" as const, label: "追加", description: "3 元/注" },
                      ].map((mode) => (
                        <button
                          key={mode.value}
                          onClick={() => onTicketModeChange(mode.value)}
                          className={`rounded-xl border px-3 py-2 text-left transition ${
                            ticketMode === mode.value
                              ? "border-cyan-300 bg-cyan-50 text-cyan-800"
                              : "border-slate-200 bg-slate-50 text-slate-700"
                          }`}
                        >
                          <p className="text-sm font-medium">{mode.label}</p>
                          <p className={`mt-0.5 text-[11px] ${ticketMode === mode.value ? "text-cyan-700" : "text-slate-500"}`}>
                            {mode.description}
                          </p>
                        </button>
                      ))}
                    </div>
                    <label className="grid gap-1.5 rounded-xl border border-cyan-200 bg-cyan-50/70 px-3 py-2">
                      <span className="text-[11px] font-medium text-cyan-700">投注倍数</span>
                      <input
                        type="number"
                        min={1}
                        max={99}
                        value={multiple}
                        onChange={(event) =>
                          onMultipleChange(Math.max(1, Math.min(99, Math.round(Number(event.target.value) || 1))))
                        }
                        className="h-9 rounded-lg border border-cyan-200 bg-white px-3 text-sm font-semibold text-cyan-800 outline-none focus:border-cyan-400"
                      />
                    </label>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                  <p className="text-[11px] text-slate-500">回放引擎</p>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    {[
                      { value: "local_only" as const, label: "仅本地", description: "只跑确定性本地链路" },
                      {
                        value: "external_rerank" as const,
                        label: "AI 重排",
                        description: aiEnabled ? "逐期调用外部 AI" : "需先完成 AI 配置",
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
                          <p
                            className={`mt-0.5 text-[11px] ${
                              aiReplayMode === mode.value
                                ? "text-violet-700"
                                : disabled
                                  ? "text-slate-400"
                                  : "text-slate-500"
                            }`}
                          >
                            {mode.description}
                          </p>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[11px] text-slate-500">回测策略</p>
                  <span className="text-[11px] text-slate-400">逐期按当前推演逻辑重跑</span>
                </div>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  {[
                    { value: "multi_cover" as const, label: "多注覆盖", description: "提升多注联合命中" },
                    { value: "single_hit" as const, label: "单注优先", description: "集中高分号码" },
                    { value: "smart_balance" as const, label: "智能平衡", description: "60/420双窗口" },
                  ].map((mode) => (
                    <button
                      key={mode.value}
                      onClick={() => onStrategyModeChange(mode.value)}
                      className={`rounded-xl border px-3 py-2 text-left transition ${
                        strategyMode === mode.value
                          ? "border-cyan-300 bg-cyan-50 text-cyan-800"
                          : "border-slate-200 bg-slate-50 text-slate-700"
                      }`}
                    >
                      <p className="text-sm font-medium">{mode.label}</p>
                      <p className={`mt-0.5 text-[11px] leading-5 ${strategyMode === mode.value ? "text-cyan-700" : "text-slate-500"}`}>
                        {mode.description}
                      </p>
                    </button>
                  ))}
                </div>
                <label className="mt-3 flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                  <input
                    type="checkbox"
                    checked={strategyMode === "smart_balance" ? false : compareModes}
                    disabled={strategyMode === "smart_balance"}
                    onChange={(event) => onCompareModesChange(event.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 text-cyan-600"
                  />
                  <div>
                    <p className="text-xs font-medium text-slate-900">同时对比两种模式</p>
                    <p className="mt-0.5 text-[11px] text-slate-500">额外返回另一种模式的汇总数据</p>
                  </div>
                </label>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <p className="text-[11px] text-slate-500">单注价格</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">{unitPrice} 元</p>
                  </div>
                  <div>
                    <p className="text-[11px] text-slate-500">单期预计成本</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">{fixedAmount(costPerIssue)} 元</p>
                  </div>
                  <div>
                    <p className="text-[11px] text-slate-500">本次预计总成本</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">{fixedAmount(estimatedTotalCost)} 元</p>
                  </div>
                </div>
                <p className="mt-3 text-[11px] leading-5 text-slate-500">
                  成本 = 回测期数 × 每期组数 × 单注价格 × 倍数。期数越多耗时越久，超过 200 期建议分批运行。
                </p>
              </div>
            </div>
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
                    const jobNetProfit = jobResult?.net_profit;
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
                          {jobNetProfit != null ? (
                            <span className={jobNetProfit >= 0 ? "text-emerald-700" : "text-rose-600"}>
                              {`${jobNetProfit >= 0 ? "+" : ""}${jobNetProfit.toFixed(2)}`}
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
              <p className="text-sm font-medium text-cyan-800">回测说明</p>
              <p className="mt-1 text-xs leading-6 text-cyan-700">
                系统会用当期之前可得的样本逐期重跑推演，用于观察策略的稳定性。基本投注 2 元/注，追加投注 3 元/注，消费金额会随票种自动变化。
              </p>
              {result?.strategy_mode ? (
                <p className="mt-2 text-xs leading-6 text-slate-600">
                  当前目标：<span className="font-medium text-slate-800">{modeLabel(result.strategy_mode)}</span>
                  {result.ticket_mode ? (
                    <span className="ml-2 text-slate-500">{ticketModeLabel(result.ticket_mode)}</span>
                  ) : null}
                  {result.ai_replay_mode ? (
                    <span className="ml-2 text-slate-500">{aiReplayModeLabel(result.ai_replay_mode)}</span>
                  ) : null}
                </p>
              ) : null}
            </div>
          </div>
        </div>

        <div className="min-w-0 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs text-slate-500">综合中奖率（方案级）</p>
              <p className="mt-2 text-2xl font-semibold text-emerald-700">{rateLabel(result?.overall_win_rate)}</p>
              <p className="mt-1 text-xs text-slate-500">
                {`中奖方案 ${result?.won_schemes ?? 0} / 生成方案 ${result?.total_generated_schemes ?? 0}`}
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p className="text-xs text-slate-500">期命中率（综合）</p>
              <p className="mt-2 text-2xl font-semibold text-cyan-700">{rateLabel(result?.issue_hit_rate)}</p>
              <p className="mt-1 text-xs text-slate-500">{`实际回测 ${result?.total_issues ?? 0} 期`}</p>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4">
              <p className="text-xs text-amber-700">累计中奖金额（元）</p>
              <p className="mt-2 text-2xl font-semibold text-amber-700">{fixedAmount(result?.total_prize_amount)}</p>
            </div>
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-4">
              <p className="text-xs text-rose-700">消费金额（元）</p>
              <p className="mt-2 text-2xl font-semibold text-rose-700">{fixedAmount(result?.total_cost)}</p>
            </div>
            <div
              className={`rounded-2xl border px-4 py-4 ${
                netProfit >= 0 ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-slate-50"
              }`}
            >
              <p className={`text-xs ${netProfit >= 0 ? "text-emerald-700" : "text-slate-500"}`}>盈亏金额（元）</p>
              <p className={`mt-2 text-2xl font-semibold ${netProfit >= 0 ? "text-emerald-700" : "text-rose-600"}`}>
                {`${netProfit >= 0 ? "+" : ""}${fixedAmount(netProfit)}`}
              </p>
            </div>
          </div>

          {modeComparison.length > 0 ? (
            <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm font-medium text-slate-900">不同模式中奖率</p>
              <p className="mt-1 text-xs text-slate-500">勾选「同时对比两种模式」后展示两种策略的关键指标。</p>
              <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200 bg-white">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-left text-slate-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">模式</th>
                      <th className="px-4 py-3 font-medium">方案中奖率</th>
                      <th className="px-4 py-3 font-medium">期命中率</th>
                      <th className="px-4 py-3 font-medium">中奖方案</th>
                      <th className="px-4 py-3 font-medium">中奖金额（元）</th>
                      <th className="px-4 py-3 font-medium">盈亏（元）</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modeComparison.map((item) => {
                      const profit = item.net_profit ?? 0;
                      return (
                        <tr key={item.strategy_mode} className="border-t border-slate-100">
                          <td className="px-4 py-3 font-medium text-slate-900">{modeLabel(item.strategy_mode)}</td>
                          <td className="px-4 py-3 text-slate-900">{rateLabel(item.overall_win_rate)}</td>
                          <td className="px-4 py-3 text-slate-700">{rateLabel(item.issue_hit_rate)}</td>
                          <td className="px-4 py-3 text-slate-700">{item.won_schemes}</td>
                          <td className="px-4 py-3 text-amber-700">{fixedAmount(item.total_prize_amount)}</td>
                          <td className={`px-4 py-3 font-medium ${profit >= 0 ? "text-emerald-700" : "text-rose-600"}`}>
                            {`${profit >= 0 ? "+" : ""}${fixedAmount(profit)}`}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-900">各奖级中奖明细</p>
              <span className="text-xs text-slate-500">中奖次数 · 中奖概率 · 中奖金额</span>
            </div>
            {prizeLevelBreakdown.length > 0 ? (
              <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200 bg-white">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-left text-slate-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">奖级</th>
                      <th className="px-4 py-3 font-medium">中奖注数</th>
                      <th className="px-4 py-3 font-medium">方案中奖率</th>
                      <th className="px-4 py-3 font-medium">命中期数</th>
                      <th className="px-4 py-3 font-medium">期命中率</th>
                      <th className="px-4 py-3 font-medium">中奖金额（元）</th>
                    </tr>
                  </thead>
                  <tbody>
                    {prizeLevelBreakdown.map((item) => (
                      <tr key={item.level} className="border-t border-slate-100">
                        <td className="px-4 py-3 font-medium text-slate-900">{item.level}</td>
                        <td className="px-4 py-3 text-slate-900">{item.wins}</td>
                        <td className="px-4 py-3 text-slate-700">{rateLabel(item.scheme_rate, 4)}</td>
                        <td className="px-4 py-3 text-slate-700">{item.issue_hits}</td>
                        <td className="px-4 py-3 text-slate-700">{rateLabel(item.issue_rate, 4)}</td>
                        <td className="px-4 py-3 font-medium text-amber-700">{fixedAmount(item.total_prize_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-8 text-sm text-slate-500">
                设定期数和方案组数后开始回测，奖级明细会在这里汇总。
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
