import type { AIConfig, AIModelItem, AIReplayMode, BacktestJobListResponse, BacktestJobResponse, BacktestResponse, BacktestStrategyMode, DivinationResponse, FinalScheme, FullHistoryCacheRebuildJob, FullHistoryCacheStatus, LottoDraw, ManualDrawResult, SavedScheme, SavedSchemeListResponse, StrategyMode, SyncStatus, TicketMode } from "./types";
import { normalizeDeep } from "./text";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

function formatRequestTimestamp(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  const hour = String(value.getHours()).padStart(2, "0");
  const minute = String(value.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

function readTrimmedString(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

export function isAIConfigReady(aiConfig?: AIConfig | null) {
  return !!(
    aiConfig?.enabled &&
    readTrimmedString(aiConfig.baseUrl) &&
    readTrimmedString(aiConfig.apiKey) &&
    readTrimmedString(aiConfig.model)
  );
}

function buildAIConfigPayload(aiConfig?: AIConfig) {
  if (!isAIConfigReady(aiConfig)) {
    return undefined;
  }
  const resolvedAIConfig = aiConfig!;
  return {
    enabled: true,
    base_url: readTrimmedString(resolvedAIConfig.baseUrl),
    api_key: readTrimmedString(resolvedAIConfig.apiKey),
    model: readTrimmedString(resolvedAIConfig.model),
    selected_models: Array.isArray(resolvedAIConfig.selectedModels) ? resolvedAIConfig.selectedModels : [],
    system_prompt: typeof resolvedAIConfig.systemPrompt === "string" ? resolvedAIConfig.systemPrompt : "",
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = "";
    let detailPayload: unknown = null;
    try {
      const payload = (await response.json()) as { detail?: unknown; message?: unknown };
      const rawDetail = payload.detail ?? payload.message;
      detailPayload = rawDetail ?? payload;
      detail = typeof rawDetail === "string" ? rawDetail : rawDetail ? JSON.stringify(rawDetail) : "";
    } catch {
      detail = await response.text().catch(() => "");
      detailPayload = detail;
    }
    throw new ApiError(detail || `Request failed: ${response.status}`, response.status, normalizeDeep(detailPayload));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const data = (await response.json()) as T;
  return normalizeDeep(data);
}

export function fetchHistory(limit = 5000) {
  return request<LottoDraw[]>(`/history?limit=${limit}`);
}

export function fetchSyncStatus() {
  return request<SyncStatus>("/sync/status");
}

export function runSync(fullRefresh = false) {
  return request("/sync/run?full_refresh=" + String(fullRefresh), { method: "POST" });
}

export function fetchFullHistoryCacheStatus(schemeCount = 3, ticketMode: TicketMode = "basic") {
  const params = new URLSearchParams({
    scheme_count: String(schemeCount),
    ticket_mode: ticketMode,
  });
  return request<FullHistoryCacheStatus>(`/full-history-cache/status?${params.toString()}`);
}

export function rebuildFullHistoryCache(schemeCount = 3, ticketMode: TicketMode = "basic", force = true) {
  const params = new URLSearchParams({
    scheme_count: String(schemeCount),
    ticket_mode: ticketMode,
    force: String(force),
  });
  return request<FullHistoryCacheRebuildJob>(`/full-history-cache/rebuild?${params.toString()}`, { method: "POST" });
}

export function fetchFullHistoryCacheJob(jobId: string) {
  return request<FullHistoryCacheRebuildJob>(`/full-history-cache/jobs/${jobId}`);
}

export function startDivination(issue?: string, schemeCount = 3, strategyMode: StrategyMode = "smart_balance", aiConfig?: AIConfig) {
  const aiConfigPayload = buildAIConfigPayload(aiConfig);
  return request<DivinationResponse>("/divination", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...(issue ? { issue } : {}),
      timestamp: formatRequestTimestamp(new Date()),
      scheme_count: schemeCount,
      strategy_mode: strategyMode,
      ...(aiConfigPayload
        ? {
            ai_config: aiConfigPayload,
          }
        : {}),
    }),
  });
}

export function fetchAIModels(baseUrl: string, apiKey: string) {
  return request<{ models: AIModelItem[] }>("/ai/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      base_url: baseUrl,
      api_key: apiKey,
    }),
  });
}

export function fetchSavedSchemes(limit = 100) {
  return request<SavedSchemeListResponse>(`/saved-schemes?limit=${limit}`);
}

export function saveGeneratedScheme(input: {
  targetIssue: string;
  seedMode: DivinationResponse["seed_mode"];
  seedValue: string;
  movingLine: number;
  aiEngine: string;
  scheme: FinalScheme;
  tuningProfile?: string | null;
  issueConfidence?: number | null;
  calibratedConfidence?: number | null;
  appliedThreshold?: number | null;
  shouldObserve?: boolean;
  frontConfidence?: number | null;
  frontGate?: number | null;
  backConfidence?: number | null;
  backGate?: number | null;
  deepSearchTriggered?: boolean;
  deepSearchReason?: string | null;
  decisionReason?: string | null;
  multiple?: number;
  isAdditional?: boolean;
}) {
  return request<SavedScheme>("/saved-schemes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_issue: input.targetIssue,
      seed_mode: input.seedMode,
      seed_value: input.seedValue,
      moving_line: input.movingLine,
      ai_engine: input.aiEngine,
      scheme: input.scheme,
      tuning_profile: input.tuningProfile,
      issue_confidence: input.issueConfidence,
      calibrated_confidence: input.calibratedConfidence,
      applied_threshold: input.appliedThreshold,
      should_observe: input.shouldObserve ?? false,
      front_confidence: input.frontConfidence,
      front_gate: input.frontGate,
      back_confidence: input.backConfidence,
      back_gate: input.backGate,
      deep_search_triggered: input.deepSearchTriggered ?? false,
      deep_search_reason: input.deepSearchReason,
      decision_reason: input.decisionReason,
      multiple: input.multiple ?? 1,
      is_additional: input.isAdditional ?? false,
    }),
  });
}

function buildGeneratedSchemePayload(input: {
  targetIssue: string;
  seedMode: DivinationResponse["seed_mode"];
  seedValue: string;
  movingLine: number;
  aiEngine: string;
  scheme: FinalScheme;
  tuningProfile?: string | null;
  issueConfidence?: number | null;
  calibratedConfidence?: number | null;
  appliedThreshold?: number | null;
  shouldObserve?: boolean;
  frontConfidence?: number | null;
  frontGate?: number | null;
  backConfidence?: number | null;
  backGate?: number | null;
  deepSearchTriggered?: boolean;
  deepSearchReason?: string | null;
  decisionReason?: string | null;
  multiple?: number;
  isAdditional?: boolean;
}) {
  return {
    target_issue: input.targetIssue,
    seed_mode: input.seedMode,
    seed_value: input.seedValue,
    moving_line: input.movingLine,
    ai_engine: input.aiEngine,
    scheme: input.scheme,
    tuning_profile: input.tuningProfile,
    issue_confidence: input.issueConfidence,
    calibrated_confidence: input.calibratedConfidence,
    applied_threshold: input.appliedThreshold,
    should_observe: input.shouldObserve ?? false,
    front_confidence: input.frontConfidence,
    front_gate: input.frontGate,
    back_confidence: input.backConfidence,
    back_gate: input.backGate,
    deep_search_triggered: input.deepSearchTriggered ?? false,
    deep_search_reason: input.deepSearchReason,
    decision_reason: input.decisionReason,
    multiple: input.multiple ?? 1,
    is_additional: input.isAdditional ?? false,
  };
}

export function saveGeneratedSchemes(
  inputs: Array<Parameters<typeof buildGeneratedSchemePayload>[0]>,
) {
  return request<SavedScheme[]>("/saved-schemes/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      items: inputs.map(buildGeneratedSchemePayload),
    }),
  });
}

export function deleteSavedScheme(savedId: number) {
  return request<void>(`/saved-schemes/${savedId}`, { method: "DELETE" });
}

export function deleteSavedIssue(issue: string) {
  return request<{ deleted: number }>(`/saved-schemes/issues/${encodeURIComponent(issue)}`, { method: "DELETE" });
}

export interface ManualScheme {
  targetIssue: string;
  frontNumbers: number[];
  backNumbers: number[];
  label?: string;
  note?: string;
  multiple?: number;
  isAdditional?: boolean;
}

export interface ManualDrawResultInput {
  issue: string;
  frontNumbers: number[];
  backNumbers: number[];
  drawDate?: string;
  highPool?: boolean;
}

export function saveManualScheme(input: ManualScheme) {
  return request<SavedScheme>("/saved-schemes/manual", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_issue: input.targetIssue,
      front_numbers: input.frontNumbers,
      back_numbers: input.backNumbers,
      label: input.label,
      note: input.note,
      multiple: input.multiple ?? 1,
      is_additional: input.isAdditional ?? false,
    }),
  });
}

export function saveManualDrawResult(input: ManualDrawResultInput) {
  return request<ManualDrawResult>(`/saved-schemes/issues/${input.issue}/manual-result`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      draw_date: input.drawDate,
      front_numbers: input.frontNumbers,
      back_numbers: input.backNumbers,
      high_pool: input.highPool ?? false,
    }),
  });
}

export function deleteManualDrawResult(issue: string) {
  return request<void>(`/saved-schemes/issues/${issue}/manual-result`, { method: "DELETE" });
}

export function runBacktest(
  recentIssues: number,
  schemeCount: number,
  strategyMode: BacktestStrategyMode = "multi_cover",
  ticketMode: "basic" | "additional" = "basic",
  aiReplayMode: AIReplayMode = "local_only",
  compareModes = false,
  aiConfig?: AIConfig,
  tuningProfileOverride?: string | null,
  multiple = 1,
) {
  return request<BacktestResponse>("/backtest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildBacktestRequest(recentIssues, schemeCount, strategyMode, ticketMode, aiReplayMode, compareModes, aiConfig, tuningProfileOverride, multiple)),
  });
}

function buildBacktestRequest(
  recentIssues: number,
  schemeCount: number,
  strategyMode: BacktestStrategyMode = "multi_cover",
  ticketMode: "basic" | "additional" = "basic",
  aiReplayMode: AIReplayMode = "local_only",
  compareModes = false,
  aiConfig?: AIConfig,
  tuningProfileOverride?: string | null,
  multiple = 1,
) {
  const aiConfigPayload = buildAIConfigPayload(aiConfig);
  const effectiveAIReplayMode = aiReplayMode === "external_rerank" && aiConfigPayload ? aiReplayMode : "local_only";
  return {
    recent_issues: recentIssues,
    scheme_count: schemeCount,
    multiple: Math.max(1, Math.min(99, Math.round(multiple || 1))),
    strategy_mode: strategyMode,
    ticket_mode: ticketMode,
    ai_replay_mode: effectiveAIReplayMode,
    compare_modes: compareModes,
    ...(tuningProfileOverride ? { tuning_profile_override: tuningProfileOverride } : {}),
    ...(aiConfigPayload && effectiveAIReplayMode === "external_rerank"
      ? {
          ai_config: aiConfigPayload,
        }
      : {}),
  };
}

export function createBacktestJob(
  recentIssues: number,
  schemeCount: number,
  strategyMode: BacktestStrategyMode = "multi_cover",
  ticketMode: "basic" | "additional" = "basic",
  aiReplayMode: AIReplayMode = "local_only",
  compareModes = false,
  aiConfig?: AIConfig,
  tuningProfileOverride?: string | null,
  multiple = 1,
) {
  return request<BacktestJobResponse>("/backtest/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildBacktestRequest(recentIssues, schemeCount, strategyMode, ticketMode, aiReplayMode, compareModes, aiConfig, tuningProfileOverride, multiple)),
  });
}

export function runBacktestNow(
  recentIssues: number,
  schemeCount: number,
  strategyMode: BacktestStrategyMode = "multi_cover",
  ticketMode: "basic" | "additional" = "basic",
  aiReplayMode: AIReplayMode = "local_only",
  compareModes = false,
  aiConfig?: AIConfig,
  tuningProfileOverride?: string | null,
  multiple = 1,
) {
  return request<BacktestResponse>("/backtest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildBacktestRequest(recentIssues, schemeCount, strategyMode, ticketMode, aiReplayMode, compareModes, aiConfig, tuningProfileOverride, multiple)),
  });
}

export function fetchBacktestJob(jobId: string) {
  return request<BacktestJobResponse>(`/backtest/jobs/${jobId}`);
}

export function fetchBacktestJobs(limit = 20) {
  return request<BacktestJobListResponse>(`/backtest/jobs?limit=${limit}`);
}

export function cancelBacktestJob(jobId: string) {
  return request<BacktestJobResponse>(`/backtest/jobs/${jobId}/cancel`, {
    method: "POST",
  });
}
