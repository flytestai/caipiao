import { Component, type ErrorInfo, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  CalendarClock,
  PanelsTopLeft,
  RefreshCw,
  Settings2,
  Sparkles,
  X,
} from "lucide-react";
import { AIConfigPanel } from "../components/AIConfigPanel";
import { BacktestPanel } from "../components/BacktestPanel";
import { DivinationAnimator } from "../components/DivinationAnimator";
import { HistoryTable } from "../components/HistoryTable";
import { RecommendationPanel } from "../components/RecommendationPanel";
import { SavedSchemePanel } from "../components/SavedSchemePanel";
import { cancelBacktestJob, createBacktestJob, deleteManualDrawResult, deleteSavedIssue, deleteSavedScheme, fetchBacktestJob, fetchBacktestJobs, fetchHistory, fetchSavedSchemes, fetchSyncStatus, isAIConfigReady, runBacktestNow, runSync, saveGeneratedScheme, saveGeneratedSchemes, saveManualDrawResult, saveManualScheme, startDivination, type ManualDrawResultInput, type ManualScheme } from "../lib/api";
import { normalizeDeep } from "../lib/text";
import type { AIConfig, AIReplayMode, BacktestJobResponse, BacktestResponse, BacktestStrategyMode, DivinationResponse, FinalScheme, LottoDraw, SavedScheme, SavedSchemeStats, StrategyMode, SyncStatus, TicketMode } from "../lib/types";

const STORAGE_KEY = "dlt-ai-last-result-v4";
const COUNT_KEY = "dlt-ai-last-count";
const AI_CONFIG_KEY = "dlt-ai-config";
const BACKTEST_OPTIONS_KEY = "dlt-backtest-options-v2";
const OBSOLETE_CACHE_KEYS = [
  "dlt-backtest-last-result-v1",
  "dlt-backtest-last-result-v2",
  "dlt-backtest-last-job-v1",
  "dlt-backtest-last-job-v2",
];

const defaultAIConfig: AIConfig = {
  enabled: false,
  baseUrl: "",
  apiKey: "",
  model: "",
  selectedModels: [],
  systemPrompt: "",
};

function normalizeStoredAIConfig(value: unknown): AIConfig {
  const raw = (value && typeof value === "object" ? value : {}) as Partial<AIConfig>;
  return {
    enabled: !!raw.enabled,
    baseUrl: typeof raw.baseUrl === "string" ? raw.baseUrl : "",
    apiKey: typeof raw.apiKey === "string" ? raw.apiKey : "",
    model: typeof raw.model === "string" ? raw.model : "",
    selectedModels: Array.isArray(raw.selectedModels) ? raw.selectedModels.filter((item): item is string => typeof item === "string") : [],
    systemPrompt: typeof raw.systemPrompt === "string" ? raw.systemPrompt : "",
  };
}

function safeStorageGet(key: string) {
  try {
    return window.localStorage.getItem(key);
  } catch (error) {
    console.warn(`localStorage get failed: ${key}`, error);
    return null;
  }
}

function safeStorageRemove(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch (error) {
    console.warn(`localStorage remove failed: ${key}`, error);
  }
}

function safeStorageSet(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch (error) {
    console.warn(`localStorage set failed: ${key}`, error);
    return false;
  }
}

function clearObsoleteCacheKeys() {
  OBSOLETE_CACHE_KEYS.forEach(safeStorageRemove);
}

const inputPresets = [3, 5, 8, 10];
const strategyModes: Array<{ value: StrategyMode; label: string; description: string }> = [
  { value: "multi_cover", label: "多注覆盖", description: "优先提高多注至少中一注的概率" },
  { value: "single_hit", label: "单注优先", description: "优先集中高分号码，强化单注表现" },
];

const pageTabs = [
  { key: "oracle", label: "\u63a8\u6f14\u4e2d\u5fc3" },
  { key: "saved", label: "\u4fdd\u5b58\u65b9\u6848" },
  { key: "backtest", label: "\u5386\u53f2\u56de\u6d4b" },
  { key: "history", label: "\u5386\u53f2\u6570\u636e" },
] as const;

function PurchaseConfigModal({
  scheme,
  schemes,
  issue,
  saving,
  initialMultiple,
  initialAdditional,
  onClose,
  onConfirm,
}: {
  scheme: FinalScheme;
  schemes: FinalScheme[];
  issue: string | null;
  saving: boolean;
  initialMultiple: number;
  initialAdditional: boolean;
  onClose: () => void;
  onConfirm: (input: { multiple: number; isAdditional: boolean }) => Promise<void> | void;
}) {
  const [multiple, setMultiple] = useState(initialMultiple);
  const [isAdditional, setIsAdditional] = useState(initialAdditional);
  const unitCost = isAdditional ? 3 : 2;
  const ticketAmount = unitCost * multiple;
  const totalTicketAmount = ticketAmount * schemes.length;
  const promotionEligible = ticketAmount >= 18;
  const estimatedFirstPrizeExtra = isAdditional ? "若命中一二等奖，追加奖金按基础奖金的 80% 另计" : "当前为基本投注，不含一二等奖追加奖金";
  const previewSchemes = schemes.slice(0, 3);
  const remainingSchemeCount = Math.max(0, schemes.length - previewSchemes.length);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 px-4 backdrop-blur-sm">
      <div className="absolute inset-0" onClick={saving ? undefined : onClose} />
      <div className="relative z-10 w-full max-w-2xl rounded-[28px] border border-slate-200 bg-white p-5 shadow-[0_24px_80px_rgba(15,23,42,0.24)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs tracking-[0.2em] text-slate-500">购买设置</p>
            <p className="mt-1 text-lg font-semibold text-slate-900">{`第 ${issue ?? "--"} 期共 ${schemes.length} 组方案`}</p>
            <p className="mt-1 text-sm text-slate-500">确认后会把本次推演的全部号码按相同设置保存到这一期。</p>
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            className="inline-flex h-10 w-10 items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 text-slate-600 transition hover:border-slate-300 hover:bg-white disabled:opacity-60"
            aria-label="关闭购买设置"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-slate-900">本次保存预览</p>
            <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600">
              {`由 ${scheme.label} 发起`}
            </span>
          </div>
          <div className="mt-3 grid gap-3">
            {previewSchemes.map((item) => (
              <div key={`save-preview-${item.label}`} className="rounded-2xl border border-slate-200 bg-white px-3 py-3">
                <p className="text-xs font-medium text-slate-700">{item.label}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {item.front_numbers.map((number) => (
                    <span key={`save-front-${item.label}-${number}`} className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-rose-500 text-xs font-semibold text-white">
                      {String(number).padStart(2, "0")}
                    </span>
                  ))}
                  <span className="px-1 text-slate-400">+</span>
                  {item.back_numbers.map((number) => (
                    <span key={`save-back-${item.label}-${number}`} className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-sky-500 text-xs font-semibold text-white">
                      {String(number).padStart(2, "0")}
                    </span>
                  ))}
                </div>
              </div>
            ))}
            {remainingSchemeCount > 0 ? (
              <p className="text-xs text-slate-500">{`其余 ${remainingSchemeCount} 组号码也会一并保存。`}</p>
            ) : null}
          </div>
        </div>

        <div className="mt-5 grid gap-4">
          <label className="grid gap-1.5">
            <span className="text-sm text-slate-600">购买倍数</span>
            <input
              type="number"
              min={1}
              max={99}
              value={multiple}
              onChange={(event) => setMultiple(Math.max(1, Math.min(99, Number(event.target.value) || 1)))}
              className="h-11 rounded-2xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none transition focus:border-slate-400 focus:bg-white"
            />
          </label>
          <label className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
            <input type="checkbox" checked={isAdditional} onChange={(event) => setIsAdditional(event.target.checked)} />
            追加投注
          </label>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
              <p className="text-[11px] tracking-[0.18em] text-slate-400">单组票面金额</p>
              <p className="mt-1 text-lg font-semibold text-slate-900">{ticketAmount.toFixed(2)} 元</p>
              <p className="mt-1 text-xs text-slate-500">{`${unitCost} 元/注 x ${multiple} 倍`}</p>
            </div>
            <div className={`rounded-2xl border px-3 py-3 ${promotionEligible ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
              <p className={`text-[11px] tracking-[0.18em] ${promotionEligible ? "text-emerald-600" : "text-amber-600"}`}>单组派奖门槛</p>
              <p className={`mt-1 text-lg font-semibold ${promotionEligible ? "text-emerald-900" : "text-amber-900"}`}>
                {promotionEligible ? "已达到" : "未达到"}
              </p>
              <p className={`mt-1 text-xs ${promotionEligible ? "text-emerald-700" : "text-amber-700"}`}>
                {promotionEligible ? "按当前设置，单组已达到 18 元门槛" : "按当前设置，单组需满 18 元才参与派奖"}
              </p>
            </div>
            <div className="rounded-2xl border border-cyan-200 bg-cyan-50 px-3 py-3">
              <p className="text-[11px] tracking-[0.18em] text-cyan-700">本次保存合计</p>
              <p className="mt-1 text-lg font-semibold text-cyan-950">{totalTicketAmount.toFixed(2)} 元</p>
              <p className="mt-1 text-xs text-cyan-800">{`${schemes.length} 组号码统一按${isAdditional ? "追加票" : "基本票"}保存`}</p>
            </div>
          </div>
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-6 text-amber-800">
            <p>{estimatedFirstPrizeExtra}</p>
            <p className="mt-1">派奖期内，三至六等奖派奖为对应固定奖的 50%，七等奖派奖为对应固定奖的 100%。本次会对全部推演方案统一应用上面的倍数与票型。</p>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            disabled={saving}
            className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 transition hover:border-slate-300 disabled:opacity-60"
          >
            取消
          </button>
          <button
            onClick={() => void onConfirm({ multiple, isAdditional })}
            disabled={saving}
            className="rounded-2xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
          >
            {saving ? "保存中..." : `确认保存这 ${schemes.length} 组`}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDateTime(value?: string | null) {
  return value
    ? new Date(value).toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "--";
}

class BacktestPanelErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean; message: string | null }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, message: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("BacktestPanel crashed", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <section className="mt-8">
          <div className="rounded-[28px] border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-700">
            <p className="font-medium text-rose-800">历史回测面板渲染失败</p>
            <p className="mt-1">{this.state.message ?? "未知错误"}</p>
            <p className="mt-2 text-xs text-rose-600">请把这条错误发给我，我继续定位具体字段。</p>
          </div>
        </section>
      );
    }
    return this.props.children;
  }
}

function normalizeMultiple(value?: number) {
  return Math.max(1, Math.min(99, Math.round(Number(value) || 1)));
}

function sortedNumbers(numbers: number[]) {
  return [...numbers].sort((left, right) => left - right);
}

function savedSchemeKeyFromParts(issue: string, frontNumbers: number[], backNumbers: number[]) {
  return `${issue}|${sortedNumbers(frontNumbers).join(",")}|${sortedNumbers(backNumbers).join(",")}`;
}

function savedSchemeKey(item: Pick<SavedScheme, "target_issue" | "front_numbers" | "back_numbers">) {
  return savedSchemeKeyFromParts(item.target_issue, item.front_numbers, item.back_numbers);
}

function buildPendingEvaluation(multiple: number, isAdditional: boolean): SavedScheme["evaluation"] {
  return {
    status: "pending",
    result_source: "none",
    multiple,
    is_additional: isAdditional,
    cost_amount: (isAdditional ? 3 : 2) * multiple,
    front_match_count: 0,
    back_match_count: 0,
    prize_level: null,
    base_prize_amount: null,
    additional_prize_amount: null,
    bonus_prize_amount: null,
    prize_amount: null,
    prize_amount_text: null,
    promotion_active: false,
    promotion_eligible: false,
    promotion_label: null,
    promotion_min_ticket_amount: null,
    draw_issue: null,
    draw_date: null,
    winning_front_numbers: [],
    winning_back_numbers: [],
    evaluated_at: null,
  };
}

function buildOptimisticManualSavedScheme(id: number, input: ManualScheme): SavedScheme {
  const targetIssue = input.targetIssue.trim();
  const now = new Date().toISOString();
  const multiple = normalizeMultiple(input.multiple);
  const isAdditional = !!input.isAdditional;
  return {
    id,
    target_issue: targetIssue,
    seed_mode: "system_time",
    seed_value: now,
    moving_line: 0,
    ai_engine: "manual",
    label: input.label?.trim() || `手动购买 ${targetIssue}`,
    confidence: 0,
    strategy: "手动购买",
    front_numbers: sortedNumbers(input.frontNumbers),
    back_numbers: sortedNumbers(input.backNumbers),
    rationale: input.note?.trim() || "用户自行购买，手动录入",
    tuning_profile: null,
    issue_confidence: null,
    calibrated_confidence: null,
    applied_threshold: null,
    should_observe: false,
    front_confidence: null,
    front_gate: null,
    back_confidence: null,
    back_gate: null,
    deep_search_triggered: false,
    deep_search_reason: null,
    decision_reason: null,
    multiple,
    is_additional: isAdditional,
    created_at: now,
    updated_at: now,
    evaluation: buildPendingEvaluation(multiple, isAdditional),
  };
}

function buildOptimisticGeneratedSavedScheme(
  id: number,
  result: DivinationResponse,
  targetIssue: string,
  scheme: FinalScheme,
  input: { multiple: number; isAdditional: boolean },
): SavedScheme {
  const now = new Date().toISOString();
  const multiple = normalizeMultiple(input.multiple);
  const isAdditional = !!input.isAdditional;
  return {
    id,
    target_issue: targetIssue,
    seed_mode: result.seed_mode,
    seed_value: result.seed_value,
    moving_line: result.moving_line,
    ai_engine: result.ai_analysis.engine,
    label: scheme.label,
    confidence: scheme.confidence,
    strategy: scheme.strategy,
    front_numbers: sortedNumbers(scheme.front_numbers),
    back_numbers: sortedNumbers(scheme.back_numbers),
    rationale: scheme.rationale,
    tuning_profile: result.tuning_profile ?? null,
    issue_confidence: result.issue_confidence ?? null,
    calibrated_confidence: result.calibrated_confidence ?? null,
    applied_threshold: result.applied_threshold ?? null,
    should_observe: result.should_observe ?? false,
    front_confidence: result.front_confidence ?? null,
    front_gate: result.front_gate ?? null,
    back_confidence: result.back_confidence ?? null,
    back_gate: result.back_gate ?? null,
    deep_search_triggered: result.deep_search_triggered ?? false,
    deep_search_reason: result.deep_search_reason ?? null,
    decision_reason: result.decision_reason ?? null,
    multiple,
    is_additional: isAdditional,
    created_at: now,
    updated_at: now,
    evaluation: buildPendingEvaluation(multiple, isAdditional),
  };
}

export function HomePage() {
  const [history, setHistory] = useState<LottoDraw[]>([]);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [schemeCount, setSchemeCount] = useState(3);
  const [strategyMode, setStrategyMode] = useState<StrategyMode>("multi_cover");
  const [result, setResult] = useState<DivinationResponse | null>(null);
  const [divinationError, setDivinationError] = useState<string | null>(null);
  const [lockedSchemes, setLockedSchemes] = useState<string[]>([]);
  const [restored, setRestored] = useState(false);
  const [aiConfig, setAIConfig] = useState<AIConfig>(defaultAIConfig);
  const [aiConfigHydrated, setAIConfigHydrated] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [savedSchemes, setSavedSchemes] = useState<SavedScheme[]>([]);
  const [savedStats, setSavedStats] = useState<SavedSchemeStats | null>(null);
  const [savingSchemeLabels, setSavingSchemeLabels] = useState<string[]>([]);
  const [schemePendingSave, setSchemePendingSave] = useState<FinalScheme | null>(null);
  const [deletingSavedIds, setDeletingSavedIds] = useState<number[]>([]);
  const [manualSubmitting, setManualSubmitting] = useState(false);
  const [manualResultSubmittingIssue, setManualResultSubmittingIssue] = useState<string | null>(null);
  const [backtestResult, setBacktestResult] = useState<BacktestResponse | null>(null);
  const [backtestIssues, setBacktestIssues] = useState(30);
  const [backtestSchemeCount, setBacktestSchemeCount] = useState(3);
  const [backtestStrategyMode, setBacktestStrategyMode] = useState<BacktestStrategyMode>("multi_cover");
  const [backtestTicketMode, setBacktestTicketMode] = useState<TicketMode>("basic");
  const [backtestAIReplayMode, setBacktestAIReplayMode] = useState<AIReplayMode>("local_only");
  const [backtestCompareModes, setBacktestCompareModes] = useState(true);
  const [backtestMultiple, setBacktestMultiple] = useState(1);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestJob, setBacktestJob] = useState<BacktestJobResponse | null>(null);
  const [backtestJobs, setBacktestJobs] = useState<BacktestJobResponse[]>([]);
  const [backtestError, setBacktestError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<(typeof pageTabs)[number]["key"]>("oracle");
  const backtestPollJobIdRef = useRef<string | null>(null);
  const savedSchemesRefreshTimerRef = useRef<number | null>(null);
  const optimisticSavedIdRef = useRef(-1);

  function scheduleSavedSchemesRefresh(delay = 600) {
    if (savedSchemesRefreshTimerRef.current != null) {
      window.clearTimeout(savedSchemesRefreshTimerRef.current);
    }
    savedSchemesRefreshTimerRef.current = window.setTimeout(() => {
      savedSchemesRefreshTimerRef.current = null;
      fetchSavedSchemes(100)
        .then((savedData) => {
          setSavedSchemes(savedData.items);
          setSavedStats(savedData.stats);
        })
        .catch((error) => {
          console.error("refresh saved schemes failed", error);
        });
    }, delay);
  }

  async function loadDashboard() {
    try {
      setDashboardError(null);
      const statusData = await fetchSyncStatus();
      setStatus(statusData);
      const historyData = await fetchHistory(statusData.total_draws || 5000);
      setHistory(historyData);
      const [savedData, jobsData] = await Promise.all([
        fetchSavedSchemes(100).catch(() => null),
        fetchBacktestJobs(12).catch(() => ({ items: [] })),
      ]);
      if (savedData) {
        setSavedSchemes(savedData.items);
        setSavedStats(savedData.stats);
      }
      setBacktestJobs(jobsData.items);
      setBacktestJob((current) => {
        if (current) {
          return jobsData.items.find((item) => item.job_id === current.job_id) ?? current;
        }
        return jobsData.items[0] ?? null;
      });
      setBacktestResult((current) => {
        if (current) {
          return current;
        }
        const latestWithResult = jobsData.items.find((item) => item.result)?.result ?? null;
        return latestWithResult;
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      setDashboardError(`数据加载失败：${message}。请确认后端 API 已启动。`);
      throw error;
    }
  }

  useEffect(() => {
    clearObsoleteCacheKeys();
    loadDashboard().catch(console.error);

    const cachedResult = safeStorageGet(STORAGE_KEY);
    const cachedCount = safeStorageGet(COUNT_KEY);
    const cachedAIConfig = safeStorageGet(AI_CONFIG_KEY);
    const cachedBacktestOptions = safeStorageGet(BACKTEST_OPTIONS_KEY);

    if (cachedCount) {
      setSchemeCount(Math.max(1, Math.min(50, Number(cachedCount) || 3)));
    }
    if (cachedResult) {
      try {
        const parsed = normalizeDeep(JSON.parse(cachedResult) as DivinationResponse);
        if (parsed.front_signal && parsed.back_signal) {
          setResult(parsed);
          setStrategyMode(parsed.strategy_mode ?? "multi_cover");
          setLockedSchemes(parsed.final_schemes[0] ? [parsed.final_schemes[0].label] : []);
          setRestored(true);
        } else {
          safeStorageRemove(STORAGE_KEY);
        }
      } catch {
        safeStorageRemove(STORAGE_KEY);
      }
    }
    if (cachedAIConfig) {
      try {
        setAIConfig(normalizeStoredAIConfig(JSON.parse(cachedAIConfig)));
      } catch {
        safeStorageRemove(AI_CONFIG_KEY);
      }
    }
    setAIConfigHydrated(true);
    if (cachedBacktestOptions) {
      try {
        const parsed = JSON.parse(cachedBacktestOptions) as {
          recentIssues?: number;
          schemeCount?: number;
          strategyMode?: StrategyMode;
          ticketMode?: TicketMode;
          aiReplayMode?: AIReplayMode;
          compareModes?: boolean;
          multiple?: number;
        };
        if (parsed.recentIssues) {
          setBacktestIssues(Math.max(5, Number(parsed.recentIssues) || 30));
        }
        if (parsed.schemeCount) {
          setBacktestSchemeCount(Math.max(1, Number(parsed.schemeCount) || 3));
        }
        if (parsed.strategyMode === "multi_cover" || parsed.strategyMode === "single_hit" || parsed.strategyMode === "smart_balance") {
          setBacktestStrategyMode(parsed.strategyMode);
        }
        if (parsed.ticketMode === "basic" || parsed.ticketMode === "additional") {
          setBacktestTicketMode(parsed.ticketMode);
        }
        if (parsed.aiReplayMode === "local_only" || parsed.aiReplayMode === "external_rerank") {
          setBacktestAIReplayMode(parsed.aiReplayMode);
        }
        if (typeof parsed.compareModes === "boolean") {
          setBacktestCompareModes(parsed.compareModes);
        }
        if (typeof parsed.multiple === "number" && Number.isFinite(parsed.multiple)) {
          setBacktestMultiple(Math.max(1, Math.min(99, Math.round(parsed.multiple))));
        }
      } catch {
        safeStorageRemove(BACKTEST_OPTIONS_KEY);
      }
    }
  }, []);

  useEffect(() => {
    return () => {
      if (savedSchemesRefreshTimerRef.current != null) {
        window.clearTimeout(savedSchemesRefreshTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!aiConfigHydrated) {
      return;
    }
    safeStorageSet(AI_CONFIG_KEY, JSON.stringify(aiConfig));
  }, [aiConfig, aiConfigHydrated]);

  useEffect(() => {
    safeStorageSet(
      BACKTEST_OPTIONS_KEY,
      JSON.stringify({
        recentIssues: backtestIssues,
        schemeCount: backtestSchemeCount,
        strategyMode: backtestStrategyMode,
        ticketMode: backtestTicketMode,
        aiReplayMode: backtestAIReplayMode,
        compareModes: backtestCompareModes,
        multiple: backtestMultiple,
      }),
    );
  }, [backtestAIReplayMode, backtestCompareModes, backtestIssues, backtestMultiple, backtestSchemeCount, backtestStrategyMode, backtestTicketMode]);

  // Auto-sync when entering "saved" tab if the next draw time has passed
  // and DB hasn't been refreshed since then (so saved schemes can settle).
  useEffect(() => {
    if (activeTab !== "saved" || syncing || !status?.next_draw_datetime) return;
    const drawTime = new Date(status.next_draw_datetime).getTime();
    const now = Date.now();
    if (now < drawTime) return;
    const lastSynced = status.last_synced_at ? new Date(status.last_synced_at).getTime() : 0;
    if (lastSynced >= drawTime) return;
    void handleSync();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, status?.next_draw_datetime, status?.last_synced_at]);

  async function handleStart() {
    const aiReady = isAIConfigReady(aiConfig);
    setLoading(true);
    setRestored(false);
    setDivinationError(null);
    try {
      const targetIssue = status?.next_issue ?? undefined;
      const data = await startDivination(targetIssue, schemeCount, strategyMode, aiReady ? aiConfig : undefined);
      setResult(data);
      setLockedSchemes(data.final_schemes[0] ? [data.final_schemes[0].label] : []);
      if (data.final_schemes.length === 0) {
        const reason = data.decision_reason || data.ai_analysis?.final_advice || "本次推演没有生成号码组合，请调整推演组数或策略后重试。";
        setDivinationError(`本次未生成号码组合：${reason}`);
      }
      safeStorageSet(STORAGE_KEY, JSON.stringify(normalizeDeep(data)));
      safeStorageSet(COUNT_KEY, String(schemeCount));
    } catch (error) {
      const message = error instanceof Error ? error.message : "推演失败";
      setDivinationError(message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    try {
      await runSync(false);
      await loadDashboard();
    } finally {
      setSyncing(false);
    }
  }

  const aiReady = isAIConfigReady(aiConfig);
  const aiStatusText = aiReady ? `AI · ${aiConfig.model}` : "本地模式";

  useEffect(() => {
    if (aiReady || backtestAIReplayMode !== "external_rerank") {
      return;
    }
    setBacktestAIReplayMode("local_only");
  }, [aiReady, backtestAIReplayMode]);

  const highlightedSchemes = useMemo(() => {
    if (!result) {
      return [];
    }
    return result.final_schemes.filter((scheme) => lockedSchemes.includes(scheme.label));
  }, [lockedSchemes, result]);

  function handleToggleSchemeLock(label: string) {
    setLockedSchemes((current) => {
      if (current.includes(label)) {
        return current.filter((item) => item !== label);
      }
      if (current.length >= 3) {
        return [...current.slice(1), label];
      }
      return [...current, label];
    });
  }

  function handleSaveScheme(scheme: FinalScheme) {
    if (!result?.final_schemes.length) {
      return;
    }
    setSchemePendingSave(scheme);
  }

  async function handleConfirmSaveScheme(input: { multiple: number; isAdditional: boolean }) {
    const scheme = schemePendingSave;
    if (!result || !status?.next_issue) {
      return;
    }
    const targetIssue = status.next_issue;
    if (!scheme) {
      return;
    }
    const schemesToSave = result.final_schemes;
    const schemeLabels = schemesToSave.map((item) => item.label);
    const optimisticItems = schemesToSave.map((currentScheme) =>
      buildOptimisticGeneratedSavedScheme(optimisticSavedIdRef.current--, result, targetIssue, currentScheme, input),
    );
    const optimisticKeys = new Set(optimisticItems.map(savedSchemeKey));
    setSavingSchemeLabels((current) => Array.from(new Set([...current, ...schemeLabels])));
    setSchemePendingSave(null);
    setSavedSchemes((current) => [
      ...optimisticItems,
      ...current.filter((item) => !optimisticKeys.has(savedSchemeKey(item))),
    ]);
    try {
      const createdItems = await saveGeneratedSchemes(
        schemesToSave.map((currentScheme) => ({
          targetIssue,
          seedMode: result.seed_mode,
          seedValue: result.seed_value,
          movingLine: result.moving_line,
          aiEngine: result.ai_analysis.engine,
          scheme: currentScheme,
          tuningProfile: result.tuning_profile,
          issueConfidence: result.issue_confidence,
          calibratedConfidence: result.calibrated_confidence,
          appliedThreshold: result.applied_threshold,
          shouldObserve: result.should_observe,
          frontConfidence: result.front_confidence,
          frontGate: result.front_gate,
          backConfidence: result.back_confidence,
          backGate: result.back_gate,
          deepSearchTriggered: result.deep_search_triggered,
          deepSearchReason: result.deep_search_reason,
          decisionReason: result.decision_reason,
          multiple: input.multiple,
          isAdditional: input.isAdditional,
        })),
      );
      const tempIds = new Set(optimisticItems.map((item) => item.id));
      const createdIds = new Set(createdItems.map((item) => item.id));
      const createdKeys = new Set(createdItems.map(savedSchemeKey));
      setSavedSchemes((current) => {
        return [
          ...createdItems,
          ...current.filter(
            (item) => !tempIds.has(item.id) && !createdIds.has(item.id) && !createdKeys.has(savedSchemeKey(item)),
          ),
        ];
      });
      scheduleSavedSchemesRefresh();
    } catch (error) {
      console.error("save generated schemes failed", error);
      const tempIds = new Set(optimisticItems.map((item) => item.id));
      setSavedSchemes((current) => current.filter((item) => !tempIds.has(item.id)));
      setDashboardError(`保存购买方案失败：${error instanceof Error ? error.message : "未知错误"}`);
      scheduleSavedSchemesRefresh(50);
    } finally {
      setSavingSchemeLabels((current) => current.filter((item) => !schemeLabels.includes(item)));
    }
  }

  async function handleDeleteSavedScheme(savedId: number) {
    setDeletingSavedIds((current) => Array.from(new Set([...current, savedId])));
    setSavedSchemes((current) => current.filter((item) => item.id !== savedId));
    try {
      await deleteSavedScheme(savedId);
      scheduleSavedSchemesRefresh();
    } catch (error) {
      console.error("delete saved scheme failed", error);
      scheduleSavedSchemesRefresh(50);
      throw error;
    } finally {
      setDeletingSavedIds((current) => current.filter((id) => id !== savedId));
    }
  }

  async function handleDeleteSavedIssue(issue: string, itemIds: number[]) {
    if (itemIds.length === 0) {
      return;
    }
    setDeletingSavedIds((current) => Array.from(new Set([...current, ...itemIds])));
    setSavedSchemes((current) => current.filter((item) => item.target_issue !== issue));
    try {
      await deleteSavedIssue(issue);
    } catch (error) {
      console.error("delete saved issue failed", error);
      scheduleSavedSchemesRefresh(50);
      throw error;
    } finally {
      setDeletingSavedIds((current) => current.filter((id) => !itemIds.includes(id)));
      scheduleSavedSchemesRefresh();
    }
  }

  function handleAddManualScheme(input: ManualScheme) {
    const optimisticItem = buildOptimisticManualSavedScheme(optimisticSavedIdRef.current--, input);
    const optimisticKey = savedSchemeKey(optimisticItem);
    setManualSubmitting(true);
    setSavedSchemes((current) => [
      optimisticItem,
      ...current.filter((item) => savedSchemeKey(item) !== optimisticKey),
    ]);
    void saveManualScheme(input)
      .then((created) => {
        setSavedSchemes((current) => [
          created,
          ...current.filter((item) => item.id !== optimisticItem.id && item.id !== created.id && savedSchemeKey(item) !== savedSchemeKey(created)),
        ]);
        scheduleSavedSchemesRefresh();
      })
      .catch((error) => {
        console.error("save manual scheme failed", error);
        setSavedSchemes((current) => current.filter((item) => item.id !== optimisticItem.id));
        setDashboardError(`保存购买号码失败：${error instanceof Error ? error.message : "未知错误"}`);
        scheduleSavedSchemesRefresh(50);
      })
      .finally(() => {
        setManualSubmitting(false);
      });
  }

  async function handleSaveManualResult(input: ManualDrawResultInput) {
    setManualResultSubmittingIssue(input.issue);
    try {
      await saveManualDrawResult(input);
      // Manual draw result changes evaluation for every saved scheme of that issue.
      // Refresh in background; UI stays responsive.
      scheduleSavedSchemesRefresh();
    } finally {
      setManualResultSubmittingIssue(null);
    }
  }

  async function handleDeleteManualResult(issue: string) {
    setManualResultSubmittingIssue(issue);
    try {
      await deleteManualDrawResult(issue);
      scheduleSavedSchemesRefresh();
    } finally {
      setManualResultSubmittingIssue(null);
    }
  }

  async function handleRunBacktest(tuningProfileOverride?: string | null) {
    const effectiveAIReplayMode: AIReplayMode = backtestStrategyMode === "smart_balance" ? "local_only" : backtestAIReplayMode === "external_rerank" && aiReady ? "external_rerank" : "local_only";
    const effectiveCompareModes = backtestStrategyMode === "smart_balance" ? false : backtestCompareModes;
    if (effectiveAIReplayMode !== backtestAIReplayMode) {
      setBacktestAIReplayMode(effectiveAIReplayMode);
    }
    setBacktestLoading(true);
    setBacktestResult(null);
    setBacktestJob(null);
    setBacktestError(null);
    try {
        const job = await createBacktestJob(
          backtestIssues,
          backtestSchemeCount,
          backtestStrategyMode,
          backtestTicketMode,
          effectiveAIReplayMode,
          effectiveCompareModes,
          aiReady ? aiConfig : undefined,
          tuningProfileOverride,
          backtestMultiple,
      );
      setBacktestJob(job);
      setBacktestJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)].slice(0, 12));
      backtestPollJobIdRef.current = job.job_id;
    } catch (error) {
      console.error(error);
      const message = error instanceof Error ? error.message : "回测任务启动失败";
      if (message.includes("404") || message.includes("405")) {
        try {
          const result = await runBacktestNow(
            backtestIssues,
            backtestSchemeCount,
            backtestStrategyMode,
            backtestTicketMode,
            effectiveAIReplayMode,
            effectiveCompareModes,
            aiReady ? aiConfig : undefined,
            tuningProfileOverride,
            backtestMultiple,
          );
          setBacktestResult(result);
          setBacktestLoading(false);
          backtestPollJobIdRef.current = null;
          return;
        } catch (fallbackError) {
          console.error(fallbackError);
          setBacktestError(fallbackError instanceof Error ? fallbackError.message : "回测失败");
          setBacktestLoading(false);
          return;
        }
      }
      setBacktestError(message);
      setBacktestLoading(false);
    }
  }

  useEffect(() => {
    const jobId = backtestJob?.job_id;
    if (!backtestLoading || !jobId) {
      return;
    }
    let cancelled = false;
    async function poll() {
      while (!cancelled && backtestPollJobIdRef.current === jobId) {
        const latest = await fetchBacktestJob(jobId);
        if (cancelled) {
          return;
        }
        setBacktestJob(latest);
        setBacktestJobs((current) => [latest, ...current.filter((item) => item.job_id !== latest.job_id)].slice(0, 12));
        if (latest.status === "completed") {
          setBacktestResult(latest.result ?? null);
          setBacktestError(null);
          setBacktestLoading(false);
          backtestPollJobIdRef.current = null;
          return;
        }
        if (latest.status === "failed") {
          setBacktestLoading(false);
          backtestPollJobIdRef.current = null;
          throw new Error(latest.error ?? "回测任务失败");
        }
        if (latest.status === "canceled") {
          setBacktestResult(null);
          setBacktestLoading(false);
          backtestPollJobIdRef.current = null;
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
    }
    poll().catch((error) => {
      console.error(error);
      if (!cancelled) {
        setBacktestJob((current) =>
          current
            ? {
                ...current,
                status: "failed",
                error: error instanceof Error ? error.message : "回测任务失败",
                message: "回测任务失败",
              }
            : current,
        );
        setBacktestError(error instanceof Error ? error.message : "回测任务失败");
        setBacktestLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [backtestJob?.job_id, backtestLoading]);

  async function handleCancelBacktest() {
    if (!backtestJob?.job_id) {
      return;
    }
    const latest = await cancelBacktestJob(backtestJob.job_id);
    setBacktestJob(latest);
    setBacktestJobs((current) => [latest, ...current.filter((item) => item.job_id !== latest.job_id)].slice(0, 12));
    setBacktestError(null);
    if (latest.status === "canceled") {
      setBacktestLoading(false);
      setBacktestResult(null);
      backtestPollJobIdRef.current = null;
    }
  }

  function handleOpenBacktestJob(job: BacktestJobResponse) {
    setBacktestJob(job);
    setBacktestStrategyMode(job.result?.strategy_mode ?? job.strategy_mode);
    setBacktestTicketMode(job.result?.ticket_mode ?? job.ticket_mode);
    setBacktestAIReplayMode(job.result?.ai_replay_mode ?? job.ai_replay_mode ?? "local_only");
    if (job.result) {
      setBacktestResult(job.result);
      setBacktestError(null);
      setBacktestLoading(false);
      backtestPollJobIdRef.current = null;
      return;
    }
    setBacktestResult(null);
    if (job.status === "queued" || job.status === "running" || job.status === "canceling") {
      backtestPollJobIdRef.current = job.job_id;
      setBacktestLoading(true);
    } else {
      setBacktestLoading(false);
    }
  }

  const savedSchemeLabels = useMemo(() => {
    const targetIssue = status?.next_issue;
    if (!targetIssue) {
      return [];
    }
    return savedSchemes
      .filter((item) => item.target_issue === targetIssue)
      .map((item) => item.label);
  }, [savedSchemes, status?.next_issue]);

  const currentIssueSavedSchemeMap = useMemo(() => {
    const targetIssue = status?.next_issue;
    if (!targetIssue) {
      return new Map<string, SavedScheme>();
    }
    return new Map(
      savedSchemes
        .filter((item) => item.target_issue === targetIssue)
        .map((item) => [item.label, item]),
    );
  }, [savedSchemes, status?.next_issue]);

  return (
    <main className="min-h-screen text-slate-900">
      {dashboardError ? (
        <div className="border-b border-rose-200 bg-rose-50">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm text-rose-700 sm:px-6 lg:px-8">
            <p>{dashboardError}</p>
            <button
              onClick={() => loadDashboard().catch(console.error)}
              className="rounded-xl border border-rose-200 bg-white px-3 py-1.5 font-medium text-rose-700"
            >
              重新加载
            </button>
          </div>
        </div>
      ) : null}
      {/* Top navigation bar */}
      <div className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-5 sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-red-500 to-blue-600 text-white shadow-sm">
              <Sparkles className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-[15px] font-semibold text-slate-900">{"\u5927\u4e50\u900f\u63a8\u6f14\u4e2d\u5fc3"}</p>
              <p className="truncate text-xs text-slate-500">{"\u5168\u5386\u53f2\u5efa\u6a21 \u00b7 \u6885\u82b1\u8d77\u5366 \u00b7 AI \u8bc4\u4f30"}</p>
            </div>
          </div>

          <nav className="hidden flex-1 justify-center md:flex">
            <div className="flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50/70 p-1">
              {pageTabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`rounded-full px-4 py-1.5 text-sm transition ${
                    activeTab === tab.key
                      ? "bg-white font-medium text-slate-900 shadow-sm"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </nav>

          <div className="flex items-center gap-2">
            <span className={`hidden items-center gap-1.5 rounded-full border px-3 py-1 text-xs lg:inline-flex ${
              aiReady
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-amber-200 bg-amber-50 text-amber-700"
            }`}>
              <span className={`h-1.5 w-1.5 rounded-full ${aiReady ? "bg-emerald-500" : "bg-amber-500"}`} />
              {aiStatusText}
            </span>
            <button
              onClick={() => setSettingsOpen(true)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
              aria-label={"\u8bbe\u7f6e"}
              title={"\u8bbe\u7f6e"}
            >
              <Settings2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Mobile tabs */}
        <div className="border-t border-slate-200/70 bg-white/70 px-3 py-2 md:hidden">
          <div className="flex gap-1 overflow-x-auto">
            {pageTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`whitespace-nowrap rounded-full px-3 py-1.5 text-sm transition ${
                  activeTab === tab.key
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-6 lg:px-8">
        {/* Hero / control card */}
        <section className="grid gap-5 lg:grid-cols-[1.05fr_1fr]">
          {/* Left: next-draw target */}
          <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white p-7 shadow-[0_8px_32px_rgba(15,23,42,0.04)]">
            <div className="pointer-events-none absolute -right-10 -top-10 h-44 w-44 rounded-full bg-gradient-to-br from-red-500/10 to-blue-500/10 blur-2xl" />
            <div className="relative">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium tracking-[0.24em] text-slate-500">{"NEXT DRAW \u00b7 \u4e0b\u4e00\u671f"}</span>
                <button
                  onClick={handleSync}
                  disabled={syncing}
                  className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
                  {syncing ? "\u540c\u6b65\u4e2d" : "\u540c\u6b65\u5b98\u65b9\u6570\u636e"}
                </button>
              </div>

              <div className="mt-5 flex items-end gap-4">
                <p className="text-[64px] font-semibold leading-none tracking-tight text-slate-900 tabular-nums sm:text-[72px]">
                  {status?.next_issue ?? "----"}
                </p>
                <p className="pb-3 text-sm text-slate-500">{"\u671f"}</p>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-600">
                <CalendarClock className="h-4 w-4 text-slate-400" />
                <span>{formatDateTime(status?.next_draw_datetime)}</span>
                <span className="text-slate-300">|</span>
                <span>{"\u5f00\u5956\u65e5\uff1a\u5468\u4e00 / \u4e09 / \u516d 21:30"}</span>
              </div>

              <div className="mt-6 grid grid-cols-3 gap-3 border-t border-slate-100 pt-5">
                <div>
                  <p className="text-xs text-slate-500">{"\u5386\u53f2\u671f\u6570"}</p>
                  <p className="mt-1 text-lg font-semibold text-slate-900 tabular-nums">{status?.total_draws ?? "--"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">{"\u6700\u65b0\u671f\u53f7"}</p>
                  <p className="mt-1 text-lg font-semibold text-slate-900 tabular-nums">{status?.latest_issue ?? "--"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">{"\u6700\u540e\u540c\u6b65"}</p>
                  <p className="mt-1 truncate text-sm font-medium text-slate-700">
                    {status?.last_synced_at ? new Date(status.last_synced_at).toLocaleString("zh-CN", { hour12: false }) : "--"}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Right: divination control */}
          <div className="rounded-3xl border border-slate-200 bg-white p-7 shadow-[0_8px_32px_rgba(15,23,42,0.04)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <span className="text-xs font-medium tracking-[0.24em] text-slate-500">{"DIVINATION \u00b7 \u63a8\u6f14\u8bbe\u7f6e"}</span>
                <p className="mt-1 text-base font-semibold text-slate-900">{"\u4e00\u7b49\u5956\u76ee\u6807\u53f7\u7801\u63a8\u6f14"}</p>
              </div>
              <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white tabular-nums">
                {schemeCount} {"\u7ec4"}
              </span>
            </div>

            <div className="mt-5">
              <div className="mb-5">
                <p className="text-xs text-slate-500">{"选号目标"}</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {strategyModes.map((mode) => (
                    <button
                      key={mode.value}
                      onClick={() => setStrategyMode(mode.value)}
                      className={`rounded-xl border px-4 py-3 text-left transition ${
                        strategyMode === mode.value
                          ? "border-slate-900 bg-slate-900 text-white"
                          : "border-slate-200 bg-white text-slate-700"
                      }`}
                    >
                      <p className="text-sm font-medium">{mode.label}</p>
                      <p className={`mt-1 text-xs leading-5 ${strategyMode === mode.value ? "text-slate-200" : "text-slate-500"}`}>
                        {mode.description}
                      </p>
                    </button>
                  ))}
                </div>
              </div>

              <label htmlFor="scheme-count" className="text-xs text-slate-500">{"\u63a8\u6f14\u7ec4\u6570\uff081 - 50\uff09"}</label>
              <div className="mt-2 relative">
                <input
                  id="scheme-count"
                  type="number"
                  min={1}
                  max={50}
                  value={schemeCount}
                  onChange={(event) => setSchemeCount(Math.max(1, Math.min(50, Number(event.target.value) || 1)))}
                  className="h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 pr-12 text-base font-medium tabular-nums text-slate-900 outline-none transition focus:border-slate-400 focus:bg-white"
                />
                <span className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-sm text-slate-400">{"\u7ec4"}</span>
              </div>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {inputPresets.map((count) => (
                  <button
                    key={count}
                    onClick={() => setSchemeCount(count)}
                    className={`rounded-md border px-2.5 py-1 text-xs transition ${
                      schemeCount === count
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                    }`}
                  >
                    {count}
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={handleStart}
              disabled={loading}
              className="mt-5 inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-red-600 to-blue-600 px-5 text-sm font-semibold text-white shadow-md transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-70"
            >
              <PanelsTopLeft className="h-4 w-4" />
              <span>{loading ? "\u63a8\u6f14\u4e2d\u00b7\u00b7\u00b7" : "\u5f00\u59cb\u63a8\u6f14"}</span>
              {!loading ? <ArrowRight className="h-4 w-4" /> : null}
            </button>

            {restored ? (
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                {"\u5df2\u6062\u590d\u4e0a\u6b21\u63a8\u6f14\u7ed3\u679c\uff0c\u53ef\u76f4\u63a5\u67e5\u770b\u6216\u91cd\u65b0\u63a8\u6f14\u3002"}
              </div>
            ) : null}
            {divinationError ? (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-800">
                {divinationError}
              </div>
            ) : null}
          </div>
        </section>

        {activeTab === "oracle" ? (
          <section className="mt-8 grid gap-6 xl:grid-cols-[0.78fr_1.22fr]">
            <DivinationAnimator loading={loading} result={result} />
            <div className="min-w-0">
              <RecommendationPanel
                result={result}
                loading={loading}
                error={divinationError}
                lockedSchemes={lockedSchemes}
                onToggleSchemeLock={handleToggleSchemeLock}
                onSaveScheme={handleSaveScheme}
                savingSchemeLabels={savingSchemeLabels}
                savedSchemeLabels={savedSchemeLabels}
                savedSchemeMap={currentIssueSavedSchemeMap}
              />
            </div>
          </section>
        ) : null}

        {activeTab === "saved" ? (
          <section className="mt-8">
            <SavedSchemePanel
              items={savedSchemes}
              stats={savedStats}
              onDelete={handleDeleteSavedScheme}
              onDeleteIssue={handleDeleteSavedIssue}
              deletingIds={deletingSavedIds}
              onAddManual={handleAddManualScheme}
              manualSubmitting={manualSubmitting}
              onSaveManualResult={handleSaveManualResult}
              onDeleteManualResult={handleDeleteManualResult}
              manualResultSubmittingIssue={manualResultSubmittingIssue}
              nextIssue={status?.next_issue ?? null}
            />
          </section>
        ) : null}

        {activeTab === "backtest" ? (
          <BacktestPanelErrorBoundary>
            <section className="mt-8">
              <BacktestPanel
                result={backtestResult}
                loading={backtestLoading}
                job={backtestJob}
                jobs={backtestJobs}
                error={backtestError}
                recentIssues={backtestIssues}
                schemeCount={backtestSchemeCount}
                ticketMode={backtestTicketMode}
                aiReplayMode={backtestAIReplayMode}
                compareModes={backtestCompareModes}
                multiple={backtestMultiple}
                onRecentIssuesChange={setBacktestIssues}
                onSchemeCountChange={setBacktestSchemeCount}
                onTicketModeChange={setBacktestTicketMode}
                strategyMode={backtestStrategyMode}
                onAIReplayModeChange={setBacktestAIReplayMode}
                onStrategyModeChange={setBacktestStrategyMode}
                onCompareModesChange={setBacktestCompareModes}
                onMultipleChange={setBacktestMultiple}
                onRun={handleRunBacktest}
                onCancelJob={handleCancelBacktest}
                onOpenJob={handleOpenBacktestJob}
                aiEnabled={aiReady}
              />
            </section>
          </BacktestPanelErrorBoundary>
        ) : null}

        {activeTab === "history" ? (
          <section className="mt-8">
            <HistoryTable rows={history} highlightedSchemes={highlightedSchemes} />
          </section>
        ) : null}
      </div>

      {schemePendingSave ? (
        <PurchaseConfigModal
          scheme={schemePendingSave}
          schemes={result?.final_schemes ?? [schemePendingSave]}
          issue={status?.next_issue ?? null}
          saving={(result?.final_schemes ?? [schemePendingSave]).some((item) => savingSchemeLabels.includes(item.label))}
          initialMultiple={currentIssueSavedSchemeMap.get(schemePendingSave.label)?.multiple ?? 1}
          initialAdditional={currentIssueSavedSchemeMap.get(schemePendingSave.label)?.is_additional ?? false}
          onClose={() => setSchemePendingSave(null)}
          onConfirm={handleConfirmSaveScheme}
        />
      ) : null}

      {settingsOpen ? (
        <div className="fixed inset-0 z-50 flex items-start justify-end bg-slate-900/18 p-0 backdrop-blur-sm">
          <div className="absolute inset-0" onClick={() => setSettingsOpen(false)} />
          <div className="relative z-10 flex h-screen w-full max-w-[760px] flex-col border-l border-slate-200 bg-[linear-gradient(180deg,_rgba(255,255,255,0.98),_rgba(248,250,252,0.98))] p-4 shadow-[-20px_0_80px_rgba(15,23,42,0.12)] sm:p-5">
            <div className="mb-4 flex items-center justify-between gap-4 rounded-[24px] border border-slate-200 bg-white px-4 py-4">
              <div>
                <p className="text-xs tracking-[0.24em] text-cyan-700/70">{"\u8bbe\u7f6e\u4e2d\u5fc3"}</p>
                <p className="mt-1 text-lg font-semibold text-slate-900">{"\u5916\u90e8 AI \u63a5\u5165"}</p>
              </div>
              <button
                onClick={() => setSettingsOpen(false)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 text-slate-600 transition hover:border-slate-300 hover:bg-white"
                aria-label={"\u5173\u95ed\u8bbe\u7f6e"}
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto pr-1">
              <AIConfigPanel
                value={aiConfig}
                onChange={setAIConfig}
                footer={
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-xs text-slate-500">
                      {
                        "\u914d\u7f6e\u5df2\u81ea\u52a8\u4fdd\u5b58\u5230\u672c\u5730\uff0c\u4e0b\u6b21\u63a8\u6f14\u4f1a\u81ea\u52a8\u5e26\u4e0a\u8fd9\u7ec4\u53c2\u6570\u3002"
                      }
                    </p>
                    <button
                      onClick={() => setSettingsOpen(false)}
                      className="rounded-2xl bg-cyan-300 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-200"
                    >
                      {"\u5b8c\u6210"}
                    </button>
                  </div>
                }
              />
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
