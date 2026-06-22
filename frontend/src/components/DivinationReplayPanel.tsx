import { useMemo, useState } from "react";
import type { DivinationRun, DivinationRunStats } from "../lib/types";
import { LottoBall } from "./LottoBall";

interface DivinationReplayPanelProps {
  items: DivinationRun[];
  stats: DivinationRunStats | null;
}

type ReplayFilter = "all" | "evaluated" | "pending" | "hit";

const replayFilterOptions: { value: ReplayFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "evaluated", label: "已开奖" },
  { value: "pending", label: "待开奖" },
  { value: "hit", label: "命中过" },
];

function formatDateTime(value?: string | null) {
  if (!value) {
    return "--";
  }
  const parsed = new Date(value.replace(" ", "T"));
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function evaluationLabel(run: DivinationRun) {
  if (!run.schemes.length || run.schemes.every((scheme) => scheme.evaluation.status === "pending")) {
    return "待开奖";
  }
  if (run.schemes.some((scheme) => scheme.evaluation.status === "won")) {
    return "本期命中";
  }
  return "未命中";
}

function evaluationTone(run: DivinationRun) {
  if (!run.schemes.length || run.schemes.every((scheme) => scheme.evaluation.status === "pending")) {
    return "border-slate-200 bg-slate-50 text-slate-600";
  }
  if (run.schemes.some((scheme) => scheme.evaluation.status === "won")) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  return "border-rose-200 bg-rose-50 text-rose-700";
}

function schemeStatusText(run: DivinationRun, schemeIndex: number) {
  const scheme = run.schemes[schemeIndex];
  if (!scheme) {
    return "--";
  }
  if (scheme.evaluation.status === "pending") {
    return "待开奖";
  }
  if (scheme.evaluation.status === "won") {
    return scheme.evaluation.prize_level ?? "已中奖";
  }
  return "未中奖";
}

function schemeStatusTone(run: DivinationRun, schemeIndex: number) {
  const scheme = run.schemes[schemeIndex];
  if (!scheme || scheme.evaluation.status === "pending") {
    return "border-slate-200 bg-slate-50 text-slate-600";
  }
  if (scheme.evaluation.status === "won") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  return "border-slate-200 bg-white text-slate-500";
}

export function DivinationReplayPanel({ items, stats }: DivinationReplayPanelProps) {
  const [issueQuery, setIssueQuery] = useState("");
  const [filter, setFilter] = useState<ReplayFilter>("all");

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      const issue = item.target_issue ?? "";
      const query = issueQuery.trim();
      if (query && !issue.includes(query)) {
        return false;
      }
      if (filter === "evaluated" && item.schemes.every((scheme) => scheme.evaluation.status === "pending")) {
        return false;
      }
      if (filter === "pending" && item.schemes.some((scheme) => scheme.evaluation.status !== "pending")) {
        return false;
      }
      if (filter === "hit" && item.schemes.every((scheme) => scheme.evaluation.status !== "won")) {
        return false;
      }
      return true;
    });
  }, [filter, issueQuery, items]);

  return (
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,0.06)]">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs tracking-[0.3em] text-cyan-700/70">实盘复盘</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">每次展示给你的推演结果，都在这里对账</h2>
          <p className="mt-2 text-sm text-slate-600">这部分只记录每次实际推演展示出的号码，不会混入手动保存或购买记录。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={issueQuery}
            onChange={(event) => setIssueQuery(event.target.value)}
            placeholder="筛选期号"
            className="h-10 min-w-[10rem] rounded-2xl border border-slate-200 bg-slate-50 px-3 text-sm text-slate-700 outline-none transition focus:border-slate-400 focus:bg-white"
          />
          <div className="flex flex-wrap gap-2">
            {replayFilterOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setFilter(option.value)}
                className={`rounded-2xl border px-3 py-2 text-sm transition ${
                  filter === option.value
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs text-slate-500">累计推演次数</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900">{stats?.total_runs ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs text-slate-500">已开奖期次</p>
          <p className="mt-2 text-2xl font-semibold text-cyan-700">{stats?.evaluated_runs ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-4">
          <p className="text-xs text-emerald-700/80">命中期次</p>
          <p className="mt-2 text-2xl font-semibold text-emerald-700">{stats?.hit_issue_count ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs text-slate-500">方案中奖率</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900">{((stats?.scheme_win_rate ?? 0) * 100).toFixed(2)}%</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs text-slate-500">期次命中率</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900">{((stats?.issue_hit_rate ?? 0) * 100).toFixed(2)}%</p>
        </div>
      </div>

      <div className="mt-5 space-y-4">
        {filteredItems.length === 0 ? (
          <div className="rounded-[24px] border border-dashed border-slate-300 bg-slate-50 px-5 py-8 text-center text-sm text-slate-500">
            还没有可复盘的推演记录。
          </div>
        ) : (
          filteredItems.map((run) => {
            const winningFrontSet = new Set(
              run.schemes.find((scheme) => scheme.evaluation.status !== "pending")?.evaluation.winning_front_numbers ?? [],
            );
            const winningBackSet = new Set(
              run.schemes.find((scheme) => scheme.evaluation.status !== "pending")?.evaluation.winning_back_numbers ?? [],
            );
            const evaluation = run.schemes.find((scheme) => scheme.evaluation.status !== "pending")?.evaluation ?? null;
            const hasHit = run.schemes.some((scheme) => scheme.evaluation.status === "won");
            return (
              <article key={run.id} className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600">
                        {`目标期号 ${run.target_issue ?? "--"}`}
                      </span>
                      <span className={`rounded-full border px-3 py-1 text-xs font-medium ${evaluationTone(run)}`}>
                        {evaluationLabel(run)}
                      </span>
                      <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-500">
                        {`${run.visible_scheme_count}/${run.requested_scheme_count} 组`}
                      </span>
                    </div>
                    <p className="mt-2 text-lg font-semibold text-slate-900">
                      {run.requested_strategy_mode === "single_hit"
                        ? "单注优先"
                        : run.requested_strategy_mode === "multi_cover"
                          ? "多注覆盖"
                          : "智能平衡"}
                      {run.requested_strategy_mode !== run.effective_strategy_mode
                        ? ` -> ${run.effective_strategy_mode === "single_hit" ? "单注优先" : run.effective_strategy_mode === "multi_cover" ? "多注覆盖" : "智能平衡"}`
                        : ""}
                    </p>
                    <p className="mt-1 text-sm text-slate-500">
                      {`推演时间 ${formatDateTime(run.created_at)} · 起卦 ${run.divination_datetime} · 开奖 ${run.target_draw_datetime}`}
                    </p>
                  </div>
                  <div className="grid gap-2 text-right text-xs text-slate-500 sm:text-sm">
                    <div>{`AI ${run.ai_enabled ? "已启用" : "未启用"} · ${run.ai_engine}`}</div>
                    <div>{run.tuning_profile ?? "未记录调参档位"}</div>
                    <div className={hasHit ? "font-medium text-emerald-700" : "text-slate-500"}>
                      {hasHit ? "本期至少一组命中" : "本期未命中"}
                    </div>
                  </div>
                </div>

                {evaluation ? (
                  <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50/70 px-4 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-medium text-emerald-800">
                        {evaluation.result_source === "manual" ? "实际开奖（手动录入）" : "实际开奖（官方）"}
                      </p>
                      <span className="rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-[11px] text-emerald-700">
                        {evaluation.draw_date ?? evaluation.draw_issue ?? "--"}
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {evaluation.winning_front_numbers.map((number) => (
                        <LottoBall key={`${run.id}-winning-front-${number}`} number={number} tone="front" size="sm" />
                      ))}
                      <span className="px-1 text-slate-400">+</span>
                      {evaluation.winning_back_numbers.map((number) => (
                        <LottoBall key={`${run.id}-winning-back-${number}`} number={number} tone="back" size="sm" />
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="mt-4 grid gap-3 xl:grid-cols-3">
                  {run.schemes.map((scheme, index) => (
                    <div key={scheme.id} className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-slate-900">{scheme.label}</p>
                          <p className="mt-1 text-xs text-slate-500">{scheme.strategy}</p>
                        </div>
                        <span className={`rounded-full border px-3 py-1 text-xs ${schemeStatusTone(run, index)}`}>
                          {schemeStatusText(run, index)}
                        </span>
                      </div>

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        {scheme.front_numbers.map((number) => (
                          <LottoBall
                            key={`${scheme.id}-front-${number}`}
                            number={number}
                            tone="front"
                            size="sm"
                            highlight={winningFrontSet.has(number)}
                          />
                        ))}
                        <span className="px-1 text-slate-400">+</span>
                        {scheme.back_numbers.map((number) => (
                          <LottoBall
                            key={`${scheme.id}-back-${number}`}
                            number={number}
                            tone="back"
                            size="sm"
                            highlight={winningBackSet.has(number)}
                          />
                        ))}
                      </div>

                      <div className="mt-3 flex flex-wrap gap-2 text-xs">
                        <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600">
                          {`前区 ${scheme.evaluation.front_match_count} 命中`}
                        </span>
                        <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600">
                          {`后区 ${scheme.evaluation.back_match_count} 命中`}
                        </span>
                        <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600">
                          {`置信 ${scheme.confidence.toFixed(3)}`}
                        </span>
                      </div>

                      {scheme.rationale ? (
                        <p className="mt-3 text-xs leading-6 text-slate-500">{scheme.rationale}</p>
                      ) : null}
                    </div>
                  ))}
                </div>

                {(run.decision_reason || run.summary_explanation) ? (
                  <div className="mt-4 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-xs leading-6 text-slate-600">
                    {run.decision_reason ? <p>{run.decision_reason}</p> : null}
                    {run.summary_explanation ? <p className={run.decision_reason ? "mt-2" : ""}>{run.summary_explanation}</p> : null}
                  </div>
                ) : null}
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
