import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import type { ManualDrawResultInput, ManualScheme } from "../lib/api";
import type { SavedScheme, SavedSchemeStats } from "../lib/types";
import { LottoBall } from "./LottoBall";
import { ManualDrawResultForm } from "./ManualDrawResultForm";
import { ManualSchemeForm } from "./ManualSchemeForm";

interface SavedSchemePanelProps {
  items: SavedScheme[];
  stats: SavedSchemeStats | null;
  onDelete?: (savedId: number) => void;
  onDeleteIssue?: (issue: string, savedIds: number[]) => Promise<void> | void;
  deletingIds?: number[];
  onAddManual?: (input: ManualScheme) => Promise<void> | void;
  manualSubmitting?: boolean;
  onSaveManualResult?: (input: ManualDrawResultInput) => Promise<void>;
  onDeleteManualResult?: (issue: string) => Promise<void>;
  manualResultSubmittingIssue?: string | null;
  nextIssue?: string | null;
}

type StatusFilter = "all" | "pending" | "won" | "not_won";
type TicketTypeFilter = "all" | "basic" | "additional";

function statusText(item: SavedScheme) {
  if (item.evaluation.status === "pending") {
    return "\u7b49\u5f85\u5f00\u5956";
  }
  if (item.evaluation.status === "won") {
    return item.evaluation.prize_level ?? "\u5df2\u4e2d\u5956";
  }
  return "\u672a\u4e2d\u5956";
}

function statusTone(item: SavedScheme) {
  if (item.evaluation.status === "pending") {
    return "border-slate-200 bg-slate-50 text-slate-600";
  }
  if (item.evaluation.status === "won") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-500";
}

const statusOptions: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "\u5168\u90e8" },
  { value: "pending", label: "\u5f85\u5f00\u5956" },
  { value: "won", label: "\u5df2\u4e2d\u5956" },
  { value: "not_won", label: "\u672a\u4e2d\u5956" },
];

const ticketTypeOptions: { value: TicketTypeFilter; label: string }[] = [
  { value: "all", label: "\u5168\u90e8\u7968\u578b" },
  { value: "basic", label: "\u53ea\u770b\u57fa\u672c\u7968" },
  { value: "additional", label: "\u53ea\u770b\u8ffd\u52a0\u7968" },
];

function exportSavedSchemes(items: SavedScheme[]) {
  const lines = [
    "\u76ee\u6807\u671f\u53f7,\u65b9\u6848\u6807\u7b7e,\u500d\u6570,\u662f\u5426\u8ffd\u52a0,\u524d\u533a,\u540e\u533a,\u8c03\u53c2\u65b9\u6848,\u539f\u59cb\u7f6e\u4fe1,\u6821\u51c6\u7f6e\u4fe1,\u5b9e\u6218\u9608\u503c,\u524d\u533a\u7f6e\u4fe1,\u524d\u533a\u95e8\u69db,\u540e\u533a\u7f6e\u4fe1,\u540e\u533a\u95e8\u69db,\u662f\u5426\u6df1\u641c,\u662f\u5426\u89c2\u671b,\u51b3\u7b56\u539f\u56e0,\u5b98\u65b9\u524d\u533a,\u5b98\u65b9\u540e\u533a,\u72b6\u6001,\u5956\u7ea7,\u57fa\u7840\u5956\u91d1,\u8ffd\u52a0\u5956\u91d1,\u6d3e\u5956\u5956\u91d1,\u603b\u5956\u91d1,\u521b\u5efa\u65f6\u95f4",
    ...items.map((item) =>
      [
        item.target_issue,
        item.label,
        item.multiple,
        item.is_additional ? "yes" : "no",
        item.front_numbers.join(" "),
        item.back_numbers.join(" "),
        item.tuning_profile ?? "",
        item.issue_confidence ?? "",
        item.calibrated_confidence ?? "",
        item.applied_threshold ?? "",
        item.front_confidence ?? "",
        item.front_gate ?? "",
        item.back_confidence ?? "",
        item.back_gate ?? "",
        item.deep_search_triggered ? "yes" : "no",
        item.should_observe ? "yes" : "no",
        `"${(item.decision_reason ?? "").replace(/"/g, '""')}"`,
        item.evaluation.winning_front_numbers.join(" "),
        item.evaluation.winning_back_numbers.join(" "),
        item.evaluation.status,
        item.evaluation.prize_level ?? "",
        item.evaluation.base_prize_amount ?? 0,
        item.evaluation.additional_prize_amount ?? 0,
        item.evaluation.bonus_prize_amount ?? 0,
        item.evaluation.prize_amount ?? 0,
        item.created_at,
      ].join(","),
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `dlt-saved-schemes-${Date.now()}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function buildFilteredStats(items: SavedScheme[]) {
  const totalSaved = items.length;
  const evaluatedItems = items.filter((item) => item.evaluation.status !== "pending");
  const wonItems = evaluatedItems.filter((item) => item.evaluation.status === "won");
  const totalCost = items.reduce((sum, item) => sum + item.evaluation.cost_amount, 0);
  const totalPrizeAmount = wonItems.reduce((sum, item) => sum + (item.evaluation.prize_amount ?? 0), 0);
  const evaluatedCount = evaluatedItems.length;
  const wonCount = wonItems.length;
  return {
    totalSaved,
    evaluatedCount,
    pendingCount: totalSaved - evaluatedCount,
    wonCount,
    totalCost,
    totalPrizeAmount,
    overallWinRate: evaluatedCount ? wonCount / evaluatedCount : 0,
    roi: totalCost ? (totalPrizeAmount - totalCost) / totalCost : 0,
  };
}

export function SavedSchemePanel({
  items,
  stats,
  onDelete,
  onDeleteIssue,
  deletingIds = [],
  onAddManual,
  manualSubmitting = false,
  onSaveManualResult,
  onDeleteManualResult,
  manualResultSubmittingIssue = null,
  nextIssue,
}: SavedSchemePanelProps) {
  const [issueQuery, setIssueQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [ticketTypeFilter, setTicketTypeFilter] = useState<TicketTypeFilter>("all");
  const [expandedIssues, setExpandedIssues] = useState<string[]>([]);
  const [topFormOpen, setTopFormOpen] = useState(false);
  const [addingIssue, setAddingIssue] = useState<string | null>(null);
  const [editingManualResultIssue, setEditingManualResultIssue] = useState<string | null>(null);
  const deletingIdSet = useMemo(() => new Set(deletingIds), [deletingIds]);
  const expandedIssueSet = useMemo(() => new Set(expandedIssues), [expandedIssues]);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (issueQuery.trim() && !item.target_issue.includes(issueQuery.trim())) {
        return false;
      }
      if (statusFilter !== "all" && item.evaluation.status !== statusFilter) {
        return false;
      }
      if (ticketTypeFilter === "basic" && item.is_additional) {
        return false;
      }
      if (ticketTypeFilter === "additional" && !item.is_additional) {
        return false;
      }
      return true;
    });
  }, [issueQuery, items, statusFilter, ticketTypeFilter]);

  const groupedItems = useMemo(() => {
    const groups = new Map<string, SavedScheme[]>();
    filteredItems.forEach((item) => {
      const current = groups.get(item.target_issue) ?? [];
      current.push(item);
      groups.set(item.target_issue, current);
    });
    return Array.from(groups.entries());
  }, [filteredItems]);

  const filteredStats = useMemo(() => buildFilteredStats(filteredItems), [filteredItems]);

  const wonItems = filteredItems.filter((item) => item.evaluation.status === "won").length;
  const pendingItems = filteredItems.filter((item) => item.evaluation.status === "pending").length;

  function toggleIssue(issue: string) {
    setExpandedIssues((current) => (current.includes(issue) ? current.filter((item) => item !== issue) : [...current, issue]));
  }

  return (
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,0.06)]">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs tracking-[0.3em] text-cyan-700/70">{"\u4fdd\u5b58\u65b9\u6848"}</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">{"\u5df2\u4fdd\u5b58\u7684\u63a8\u6f14\u8bb0\u5f55"}</h2>
          <p className="mt-2 text-sm text-slate-600">{"\u5f00\u5956\u540e\u7cfb\u7edf\u4f1a\u81ea\u52a8\u5bf9\u5e94\u76ee\u6807\u671f\u53f7\uff0c\u8865\u5168\u5b98\u65b9\u53f7\u7801\u3001\u5956\u7ea7\u4e0e\u5956\u91d1\u7ed3\u679c\u3002"}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {onAddManual ? (
            <button
              onClick={() => setTopFormOpen((current) => !current)}
              className="inline-flex items-center gap-1.5 rounded-2xl border border-cyan-200 bg-cyan-50 px-4 py-2 text-sm font-medium text-cyan-700 hover:bg-cyan-100"
            >
              <Plus className="h-4 w-4" />
              {topFormOpen ? "\u6536\u8d77\u6dfb\u52a0" : "\u6dfb\u52a0\u8d2d\u4e70\u53f7\u7801"}
            </button>
          ) : null}
          {filteredItems.length > 0 ? (
            <button
              onClick={() => exportSavedSchemes(filteredItems)}
              className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-700"
            >
              {"\u5bfc\u51fa\u4fdd\u5b58\u8bb0\u5f55"}
            </button>
          ) : null}
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs text-slate-500">{"\u5df2\u4fdd\u5b58\u65b9\u6848"}</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900">{stats?.total_saved ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs text-slate-500">{"\u5df2\u5f00\u5956\u5df2\u68c0\u9a8c"}</p>
          <p className="mt-2 text-2xl font-semibold text-cyan-700">{stats?.evaluated_count ?? 0}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs text-slate-500">{"\u603b\u4e2d\u5956\u7387"}</p>
          <p className="mt-2 text-2xl font-semibold text-emerald-700">{((stats?.overall_win_rate ?? 0) * 100).toFixed(2)}%</p>
        </div>
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-4">
          <p className="text-xs text-slate-500">{"\u7d2f\u8ba1\u5956\u91d1"}</p>
          <p className="mt-2 text-2xl font-semibold text-rose-700">{(stats?.total_prize_amount ?? 0).toFixed(2)}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p className="text-xs text-slate-500">{"\u6295\u8d44\u56de\u62a5\u7387"}</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900">{((stats?.roi ?? 0) * 100).toFixed(2)}%</p>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-slate-900">基本票统计</p>
            <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600">
              {`${stats?.basic.total_saved ?? 0} 张`}
            </span>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">累计成本</p>
              <p className="mt-1.5 text-lg font-semibold text-slate-900">{(stats?.basic.total_cost ?? 0).toFixed(2)}</p>
            </div>
            <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3">
              <p className="text-xs text-slate-500">累计奖金</p>
              <p className="mt-1.5 text-lg font-semibold text-rose-700">{(stats?.basic.total_prize_amount ?? 0).toFixed(2)}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">ROI</p>
              <p className="mt-1.5 text-lg font-semibold text-slate-900">{((stats?.basic.roi ?? 0) * 100).toFixed(2)}%</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">已检验</p>
              <p className="mt-1.5 text-lg font-semibold text-cyan-700">{stats?.basic.evaluated_count ?? 0}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">中奖张数</p>
              <p className="mt-1.5 text-lg font-semibold text-emerald-700">{stats?.basic.won_count ?? 0}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">中奖率</p>
              <p className="mt-1.5 text-lg font-semibold text-emerald-700">{((stats?.basic.overall_win_rate ?? 0) * 100).toFixed(2)}%</p>
            </div>
          </div>
        </div>

        <div className="rounded-[24px] border border-cyan-200 bg-cyan-50/50 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-slate-900">追加票统计</p>
            <span className="rounded-full border border-cyan-200 bg-white px-3 py-1 text-xs text-cyan-700">
              {`${stats?.additional.total_saved ?? 0} 张`}
            </span>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-2xl border border-cyan-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">累计成本</p>
              <p className="mt-1.5 text-lg font-semibold text-slate-900">{(stats?.additional.total_cost ?? 0).toFixed(2)}</p>
            </div>
            <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3">
              <p className="text-xs text-slate-500">累计奖金</p>
              <p className="mt-1.5 text-lg font-semibold text-rose-700">{(stats?.additional.total_prize_amount ?? 0).toFixed(2)}</p>
            </div>
            <div className="rounded-2xl border border-cyan-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">ROI</p>
              <p className="mt-1.5 text-lg font-semibold text-slate-900">{((stats?.additional.roi ?? 0) * 100).toFixed(2)}%</p>
            </div>
            <div className="rounded-2xl border border-cyan-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">已检验</p>
              <p className="mt-1.5 text-lg font-semibold text-cyan-700">{stats?.additional.evaluated_count ?? 0}</p>
            </div>
            <div className="rounded-2xl border border-cyan-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">中奖张数</p>
              <p className="mt-1.5 text-lg font-semibold text-emerald-700">{stats?.additional.won_count ?? 0}</p>
            </div>
            <div className="rounded-2xl border border-cyan-200 bg-white px-4 py-3">
              <p className="text-xs text-slate-500">中奖率</p>
              <p className="mt-1.5 text-lg font-semibold text-emerald-700">{((stats?.additional.overall_win_rate ?? 0) * 100).toFixed(2)}%</p>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[0.78fr_1.22fr]">
        <div className="space-y-4">
          <div className="rounded-[24px] border border-emerald-200 bg-emerald-50/50 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-900">当前筛选结果统计</p>
              <span className="rounded-full border border-emerald-200 bg-white px-3 py-1 text-xs text-emerald-700">
                {`${filteredStats.totalSaved} 条`}
              </span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <div className="rounded-2xl border border-emerald-200 bg-white px-4 py-3">
                <p className="text-xs text-slate-500">累计成本</p>
                <p className="mt-1.5 text-lg font-semibold text-slate-900">{filteredStats.totalCost.toFixed(2)}</p>
              </div>
              <div className="rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3">
                <p className="text-xs text-slate-500">累计奖金</p>
                <p className="mt-1.5 text-lg font-semibold text-rose-700">{filteredStats.totalPrizeAmount.toFixed(2)}</p>
              </div>
              <div className="rounded-2xl border border-emerald-200 bg-white px-4 py-3">
                <p className="text-xs text-slate-500">ROI</p>
                <p className="mt-1.5 text-lg font-semibold text-slate-900">{(filteredStats.roi * 100).toFixed(2)}%</p>
              </div>
              <div className="rounded-2xl border border-emerald-200 bg-white px-4 py-3">
                <p className="text-xs text-slate-500">已检验</p>
                <p className="mt-1.5 text-lg font-semibold text-cyan-700">{filteredStats.evaluatedCount}</p>
              </div>
              <div className="rounded-2xl border border-emerald-200 bg-white px-4 py-3">
                <p className="text-xs text-slate-500">待开奖</p>
                <p className="mt-1.5 text-lg font-semibold text-slate-900">{filteredStats.pendingCount}</p>
              </div>
              <div className="rounded-2xl border border-emerald-200 bg-white px-4 py-3">
                <p className="text-xs text-slate-500">中奖率</p>
                <p className="mt-1.5 text-lg font-semibold text-emerald-700">{(filteredStats.overallWinRate * 100).toFixed(2)}%</p>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm font-medium text-slate-900">{"\u6863\u6848\u5de5\u4f5c\u533a"}</p>
            <div className="mt-4 grid gap-3">
              <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                <p className="text-xs text-slate-500">{"\u5f53\u524d\u7968\u578b\u7b5b\u9009"}</p>
                <p className="mt-1.5 text-lg font-semibold text-slate-900">
                  {ticketTypeOptions.find((option) => option.value === ticketTypeFilter)?.label ?? "\u5168\u90e8\u7968\u578b"}
                </p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                <p className="text-xs text-slate-500">{"\u5f53\u524d\u7b5b\u9009\u7ed3\u679c"}</p>
                <p className="mt-1.5 text-lg font-semibold text-slate-900">{filteredItems.length}</p>
                <p className="mt-1 text-xs text-slate-500">{"\u53ef\u6309\u76ee\u6807\u671f\u53f7\u548c\u5f00\u5956\u72b6\u6001\u7ee7\u7eed\u7f29\u5c0f\u8303\u56f4"}</p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3">
                  <p className="text-xs text-emerald-700/80">{"\u5df2\u4e2d\u5956\u65b9\u6848"}</p>
                  <p className="mt-1.5 text-lg font-semibold text-emerald-700">{wonItems}</p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <p className="text-xs text-slate-500">{"\u5f85\u5f00\u5956\u65b9\u6848"}</p>
                  <p className="mt-1.5 text-lg font-semibold text-slate-900">{pendingItems}</p>
                </div>
              </div>
              <div className="rounded-2xl border border-cyan-200 bg-cyan-50 px-4 py-3">
                <p className="text-sm font-medium text-cyan-800">{"\u4f7f\u7528\u5efa\u8bae"}</p>
                <p className="mt-1 text-xs leading-6 text-cyan-700">{"\u5148\u6309\u671f\u53f7\u5c55\u5f00\u5355\u671f\u65b9\u6848\uff0c\u5f00\u5956\u540e\u4f18\u5148\u67e5\u770b\u5b98\u65b9\u53f7\u7801\u5bf9\u6bd4\u3001\u547d\u4e2d\u7801\u6570\u548c\u5956\u91d1\u7ed3\u679c\u3002"}</p>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm font-medium text-slate-900">{"\u5404\u5956\u7ea7\u547d\u4e2d\u7387"}</p>
            <div className="mt-4 space-y-3">
              {(stats?.prize_rates ?? []).map((item) => (
                <div key={item.level} className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-slate-900">{item.level}</span>
                    <span className="text-sm text-slate-600">{(item.rate * 100).toFixed(2)}%</span>
                  </div>
                  <div className="mt-2 h-2 rounded-full bg-slate-200">
                    <div
                      className="h-2 rounded-full bg-[linear-gradient(90deg,_#0ea5e9,_#10b981)]"
                      style={{ width: `${Math.min(item.rate * 100, 100)}%` }}
                    />
                  </div>
                  <p className="mt-2 text-xs text-slate-500">{`\u547d\u4e2d ${item.wins} \u6b21`}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-medium text-slate-900">{"\u4fdd\u5b58\u65b9\u6848\u6863\u6848"}</p>
            <span className="text-xs text-slate-500">{`\u7b5b\u9009\u540e ${filteredItems.length} / ${items.length} \u6761`}</span>
          </div>

          {onAddManual && topFormOpen ? (
            <div className="mt-4">
              <ManualSchemeForm
                defaultIssue={nextIssue ?? undefined}
                submitting={manualSubmitting}
                onSubmit={async (input) => {
                  void onAddManual(input);
                  setExpandedIssues((current) =>
                    current.includes(input.targetIssue) ? current : [...current, input.targetIssue],
                  );
                  setTopFormOpen(false);
                }}
                onCancel={() => setTopFormOpen(false)}
              />
            </div>
          ) : null}

          <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
            <input
              value={issueQuery}
              onChange={(event) => setIssueQuery(event.target.value)}
              placeholder={"\u6309\u76ee\u6807\u671f\u53f7\u68c0\u7d22\uff0c\u4f8b\u5982 26051"}
              className="h-11 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none"
            />
            <div className="flex flex-wrap gap-2">
              {statusOptions.map((option) => (
                <button
                  key={option.value}
                  onClick={() => setStatusFilter(option.value)}
                  className={`rounded-full border px-3 py-1.5 text-xs ${
                    statusFilter === option.value
                      ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                      : "border-slate-200 bg-white text-slate-500"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {ticketTypeOptions.map((option) => (
              <button
                key={option.value}
                onClick={() => setTicketTypeFilter(option.value)}
                className={`rounded-full border px-3 py-1.5 text-xs ${
                  ticketTypeFilter === option.value
                    ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                    : "border-slate-200 bg-white text-slate-500"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="mt-4 grid gap-3">
            {groupedItems.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-8 text-sm text-slate-500">
                {"\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u4e0b\u6682\u65e0\u4fdd\u5b58\u65b9\u6848\u3002"}
              </div>
            ) : (
              groupedItems.map(([issue, issueItems]) => {
                const expanded = expandedIssueSet.has(issue);
                const wonCount = issueItems.filter((item) => item.evaluation.status === "won").length;
                const totalPrizeAmount = issueItems.reduce((sum, item) => sum + (item.evaluation.prize_amount ?? 0), 0);
                const issueEvaluation = issueItems[0]?.evaluation;
                const hasResolvedResult = !!issueEvaluation && issueEvaluation.status !== "pending";
                const isManualResult = issueEvaluation?.result_source === "manual";
                const issueDeleting = issueItems.some((item) => deletingIdSet.has(item.id));
                const issueItemIds = issueItems.map((item) => item.id);
                const issueWinningFrontSet = new Set(issueEvaluation?.winning_front_numbers ?? []);
                const issueWinningBackSet = new Set(issueEvaluation?.winning_back_numbers ?? []);

                return (
                  <div key={issue} className="rounded-2xl border border-slate-200 bg-white shadow-sm">
                    <div className="flex items-start justify-between gap-3 px-4 py-4">
                      <button
                        type="button"
                        onClick={() => toggleIssue(issue)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <p className="text-sm font-semibold text-slate-900">{`目标期号 ${issue}`}</p>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-600">
                            {`共 ${issueItems.length} 组`}
                          </span>
                          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-emerald-700">
                            {`已中 ${wonCount} 组`}
                          </span>
                          <span className="rounded-full border border-rose-200 bg-rose-50 px-2.5 py-1 font-semibold text-rose-700">
                            {`总奖金 ${totalPrizeAmount.toFixed(2)} 元`}
                          </span>
                          {isManualResult ? (
                            <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-amber-700">手动开奖号</span>
                          ) : hasResolvedResult ? (
                            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-emerald-700">官方开奖号</span>
                          ) : (
                            <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-500">待开奖</span>
                          )}
                        </div>
                      </button>
                      <div className="flex shrink-0 items-center gap-2">
                        {onDeleteIssue ? (
                          <button
                            type="button"
                            onClick={() => void onDeleteIssue(issue, issueItemIds)}
                            disabled={issueDeleting}
                            className="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-xs font-medium text-rose-700 disabled:opacity-60"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            {issueDeleting ? "删除中..." : "整期删除"}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => toggleIssue(issue)}
                          className={`rounded-full border px-3 py-1 text-xs ${
                            expanded ? "border-cyan-200 bg-cyan-50 text-cyan-700" : "border-slate-200 bg-slate-50 text-slate-500"
                          }`}
                        >
                          {expanded ? "收起" : "展开"}
                        </button>
                      </div>
                    </div>

                    {expanded ? (
                      <div className="grid gap-3 border-t border-slate-200 px-4 py-4">
                        {hasResolvedResult && issueEvaluation ? (
                          <div className="rounded-2xl border border-emerald-200 bg-emerald-50/60 px-4 py-3">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <p className="text-xs font-medium text-emerald-800">
                                {isManualResult ? "当期手动录入开奖号码" : "当期官方开奖号码"}
                              </p>
                              <span
                                className={`rounded-full border px-2.5 py-1 text-[11px] ${
                                  isManualResult
                                    ? "border-amber-200 bg-white text-amber-700"
                                    : "border-emerald-200 bg-white text-emerald-700"
                                }`}
                              >
                                {isManualResult ? "手动" : "官方"}
                              </span>
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-2">
                              {issueEvaluation.winning_front_numbers.map((number) => (
                                <LottoBall key={`${issue}-issue-winning-front-${number}`} number={number} tone="front" size="sm" />
                              ))}
                              <span className="px-1 text-slate-400">+</span>
                              {issueEvaluation.winning_back_numbers.map((number) => (
                                <LottoBall key={`${issue}-issue-winning-back-${number}`} number={number} tone="back" size="sm" />
                              ))}
                            </div>
                            <p className="mt-2 text-[11px] text-emerald-700/80">
                              {`开奖期号 ${issueEvaluation.draw_issue ?? issue}`}
                              {issueEvaluation.draw_date ? ` · ${issueEvaluation.draw_date}` : ""}
                            </p>
                          </div>
                        ) : null}

                        {onSaveManualResult ? (
                          editingManualResultIssue === issue ? (
                            <ManualDrawResultForm
                              issue={issue}
                              initialFrontNumbers={issueEvaluation?.winning_front_numbers ?? []}
                              initialBackNumbers={issueEvaluation?.winning_back_numbers ?? []}
                              initialDrawDate={issueEvaluation?.draw_date ?? null}
                              submitting={manualResultSubmittingIssue === issue}
                              onSubmit={async (input) => {
                                await onSaveManualResult(input);
                                setEditingManualResultIssue(null);
                              }}
                              onCancel={() => setEditingManualResultIssue(null)}
                            />
                          ) : (
                            <div className="flex flex-wrap items-center gap-2">
                              <button
                                onClick={() => setEditingManualResultIssue(issue)}
                                className="inline-flex items-center gap-1.5 self-start rounded-xl border border-dashed border-amber-300 bg-amber-50/60 px-3 py-2 text-xs font-medium text-amber-700 hover:bg-amber-50"
                              >
                                <Plus className="h-3.5 w-3.5" />
                                {isManualResult ? `修改第 ${issue} 期开奖号码` : `为第 ${issue} 期录入开奖号码`}
                              </button>
                              {isManualResult && onDeleteManualResult ? (
                                <button
                                  onClick={() => void onDeleteManualResult(issue)}
                                  disabled={manualResultSubmittingIssue === issue}
                                  className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700 disabled:opacity-60"
                                >
                                  {manualResultSubmittingIssue === issue ? "处理中..." : "删除手动开奖号"}
                                </button>
                              ) : null}
                            </div>
                          )
                        ) : null}

                        {onAddManual ? (
                          addingIssue === issue ? (
                            <ManualSchemeForm
                              fixedIssue={issue}
                              submitting={manualSubmitting}
                              onSubmit={async (input) => {
                                void onAddManual(input);
                                setAddingIssue(null);
                              }}
                              onCancel={() => setAddingIssue(null)}
                            />
                          ) : (
                            <button
                              onClick={() => setAddingIssue(issue)}
                              className="inline-flex items-center gap-1.5 self-start rounded-xl border border-dashed border-cyan-300 bg-cyan-50/50 px-3 py-2 text-xs font-medium text-cyan-700 hover:bg-cyan-50"
                            >
                              <Plus className="h-3.5 w-3.5" />
                              {`为第 ${issue} 期添加购买号码`}
                            </button>
                          )
                        ) : null}

                        <div className="grid gap-3">
                          {issueItems.map((item) => {
                            const evaluated = item.evaluation.status !== "pending";
                            const prizeAmount = item.evaluation.prize_amount ?? 0;
                            const showDetails =
                              item.calibrated_confidence != null ||
                              !!item.tuning_profile ||
                              !!item.decision_reason ||
                              !!item.evaluation.prize_level;

                            return (
                              <div key={item.id} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                                <div className="flex flex-wrap items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <p className="truncate text-sm font-semibold text-slate-900">{item.label}</p>
                                    <p className="mt-1 text-xs text-slate-500">{item.strategy}</p>
                                  </div>
                                  <div className="flex shrink-0 items-center gap-2">
                                    <span className={`rounded-full border px-3 py-1 text-xs ${statusTone(item)}`}>{statusText(item)}</span>
                                    {onDelete ? (
                                      <button
                                        type="button"
                                        onClick={() => void onDelete(item.id)}
                                        disabled={deletingIdSet.has(item.id)}
                                        className="inline-flex items-center gap-1 rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-xs font-medium text-rose-700 disabled:opacity-60"
                                      >
                                        <Trash2 className="h-3.5 w-3.5" />
                                        {deletingIdSet.has(item.id) ? "删除中..." : "删除"}
                                      </button>
                                    ) : null}
                                  </div>
                                </div>

                                <div className="mt-3 flex flex-wrap items-center gap-2">
                                  <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600">
                                    {`${item.is_additional ? "追加" : "基本"} / ${item.multiple} 倍 / 投注 ${item.evaluation.cost_amount.toFixed(2)} 元`}
                                  </span>
                                  {item.front_numbers.map((number) => (
                                    <LottoBall
                                      key={`${item.id}-front-${number}`}
                                      number={number}
                                      tone="front"
                                      size="sm"
                                      highlight={evaluated && issueWinningFrontSet.has(number)}
                                    />
                                  ))}
                                  <span className="px-1 text-slate-400">+</span>
                                  {item.back_numbers.map((number) => (
                                    <LottoBall
                                      key={`${item.id}-back-${number}`}
                                      number={number}
                                      tone="back"
                                      size="sm"
                                      highlight={evaluated && issueWinningBackSet.has(number)}
                                    />
                                  ))}
                                </div>

                                {evaluated ? (
                                  <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                                    <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-slate-600">
                                      {`前区命中 ${item.evaluation.front_match_count} 码`}
                                    </span>
                                    <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-slate-600">
                                      {`后区命中 ${item.evaluation.back_match_count} 码`}
                                    </span>
                                    <span
                                      className={`rounded-full border px-3 py-1 font-medium ${
                                        item.evaluation.prize_level
                                          ? "border-rose-200 bg-rose-50 text-rose-700"
                                          : "border-slate-200 bg-white text-slate-600"
                                      }`}
                                    >
                                      {item.evaluation.prize_level
                                        ? `${item.evaluation.prize_level} · 奖金 ${prizeAmount.toFixed(2)} 元`
                                        : "未达到中奖条件"}
                                    </span>
                                  </div>
                                ) : (
                                  <p className="mt-3 text-xs text-slate-500">
                                    {`当前目标期号 ${item.target_issue} 尚未开奖，开奖后会自动补全官方号码与兑奖结果。`}
                                  </p>
                                )}

                                {showDetails ? (
                                  <details className="mt-3 rounded-xl border border-dashed border-slate-200 bg-white px-3 py-2">
                                    <summary className="cursor-pointer list-none text-xs font-medium text-slate-600">
                                      查看方案细节
                                    </summary>
                                    <div className="mt-2 grid gap-2 text-xs text-slate-600">
                                      <div className="flex flex-wrap gap-2">
                                        {item.tuning_profile ? (
                                          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">{`调参 ${item.tuning_profile}`}</span>
                                        ) : null}
                                        {item.calibrated_confidence != null && item.applied_threshold != null ? (
                                          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">
                                            {`校准 ${item.calibrated_confidence.toFixed(3)} / 阈值 ${item.applied_threshold.toFixed(3)}`}
                                          </span>
                                        ) : null}
                                        {item.front_confidence != null && item.front_gate != null ? (
                                          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">
                                            {`前区 ${item.front_confidence.toFixed(3)} / ${item.front_gate.toFixed(3)}`}
                                          </span>
                                        ) : null}
                                        {item.back_confidence != null && item.back_gate != null ? (
                                          <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">
                                            {`后区 ${item.back_confidence.toFixed(3)} / ${item.back_gate.toFixed(3)}`}
                                          </span>
                                        ) : null}
                                        <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">
                                          {item.deep_search_triggered ? "已触发深搜" : "未触发深搜"}
                                        </span>
                                        <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">
                                          {item.should_observe ? "建议观望" : "允许出手"}
                                        </span>
                                        {item.evaluation.prize_level ? (
                                          <span className="rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-rose-700">
                                            {`基础 ${item.evaluation.base_prize_amount?.toFixed(2) ?? "--"} / 追加 ${item.evaluation.additional_prize_amount?.toFixed(2) ?? "0.00"} / 派奖 ${item.evaluation.bonus_prize_amount?.toFixed(2) ?? "0.00"}`}
                                          </span>
                                        ) : null}
                                      </div>
                                      {item.evaluation.prize_level ? (
                                        <div className="grid gap-2 sm:grid-cols-2">
                                          <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
                                            {item.is_additional ? "追加票：仅一二等奖享追加奖金" : "基本票：不含追加奖金"}
                                          </div>
                                          <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
                                            {item.evaluation.promotion_eligible
                                              ? `已参与 ${item.evaluation.promotion_label ?? "派奖"}`
                                              : item.evaluation.promotion_active
                                                ? `未触发派奖（单张单期需满 ${item.evaluation.promotion_min_ticket_amount?.toFixed(0) ?? "18"} 元）`
                                                : "未触发派奖"}
                                          </div>
                                        </div>
                                      ) : null}
                                      {item.decision_reason ? <p className="leading-6 text-slate-500">{item.decision_reason}</p> : null}
                                    </div>
                                  </details>
                                ) : null}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
