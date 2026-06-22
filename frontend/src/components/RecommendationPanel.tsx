import { useMemo, useRef, useState } from "react";
import { AlertTriangle, BrainCircuit, Copy, Layers3, LoaderCircle, Lock, Share2, Trophy, Unlock } from "lucide-react";
import { toPng } from "html-to-image";
import { displayElementName, displayHexagramName } from "../lib/display";
import { decodeEscapedUnicode } from "../lib/text";
import type {
  CandidateBreakdown,
  DivinationResponse,
  FinalScheme,
  RecommendationNumber,
  SavedScheme,
  TailWeightItem,
  ZoneSignal,
} from "../lib/types";
import { LottoBall } from "./LottoBall";

interface RecommendationPanelProps {
  result: DivinationResponse | null;
  loading?: boolean;
  error?: string | null;
  lockedSchemes?: string[];
  onToggleSchemeLock?: (label: string) => void;
  onSaveScheme?: (scheme: FinalScheme) => void;
  savingSchemeLabels?: string[];
  savedSchemeLabels?: string[];
  savedSchemeMap?: Map<string, SavedScheme>;
}

function purchaseSummary(savedScheme?: SavedScheme) {
  if (!savedScheme) {
    return null;
  }
  return `${savedScheme.is_additional ? "已按追加" : "已按基本"} ${savedScheme.multiple} 倍保存`;
}

type CandidateMetric = "score" | "tail_weight" | "omission" | "recent_hits";

const metricLabels: Record<CandidateMetric, string> = {
  score: "总分",
  tail_weight: "尾数权重",
  omission: "遗漏",
  recent_hits: "recent 30",
};

async function shareSchemesAsImage(node: HTMLElement): Promise<"copied" | "downloaded"> {
  const dataUrl = await toPng(node, {
    cacheBust: true,
    pixelRatio: 2,
    backgroundColor: "#ffffff",
  });
  const blob = await (await fetch(dataUrl)).blob();

  // Preferred: copy PNG to clipboard so user can paste anywhere
  try {
    const ClipboardItemCtor = (window as unknown as { ClipboardItem?: typeof ClipboardItem }).ClipboardItem;
    if (navigator.clipboard && "write" in navigator.clipboard && ClipboardItemCtor) {
      await navigator.clipboard.write([
        new ClipboardItemCtor({ "image/png": blob }),
      ]);
      return "copied";
    }
  } catch (err) {
    console.warn("clipboard write failed, falling back to download", err);
  }

  // Fallback: download the PNG
  const anchor = document.createElement("a");
  anchor.href = dataUrl;
  anchor.download = `dlt-schemes-${Date.now()}.png`;
  anchor.click();
  return "downloaded";
}

function formatSchemeNumbers(scheme: FinalScheme) {
  const front = scheme.front_numbers.map((n) => String(n).padStart(2, "0")).join(" ");
  const back = scheme.back_numbers.map((n) => String(n).padStart(2, "0")).join(" ");
  return `\u524d\u533a\uff1a${front} \u540e\u533a\uff1a${back}`;
}

async function copyScheme(scheme: FinalScheme) {
  await navigator.clipboard.writeText(formatSchemeNumbers(scheme));
}

function formatSchemeList(schemes: FinalScheme[]) {
  return schemes.map((scheme) => formatSchemeNumbers(scheme)).join("\n");
}

async function copySchemes(schemes: FinalScheme[]) {
  await navigator.clipboard.writeText(formatSchemeList(schemes));
}

function sum(numbers: number[]) {
  return numbers.reduce((total, value) => total + value, 0);
}

function span(numbers: number[]) {
  return numbers.length > 0 ? Math.max(...numbers) - Math.min(...numbers) : 0;
}

function oddEven(numbers: number[]) {
  const odd = numbers.filter((value) => value % 2 !== 0).length;
  return `${odd}:${numbers.length - odd}`;
}

function topNumbers(candidates: CandidateBreakdown[], count: number) {
  return candidates.slice(0, count).map((item) => item.number.toString().padStart(2, "0")).join(" / ");
}

function topTails(items: TailWeightItem[], count: number) {
  return items.slice(0, count).map((item) => item.tail).join(" / ");
}

function zoneSplit(numbers: number[]) {
  const zones = [0, 0, 0];
  numbers.forEach((value) => {
    if (value <= 12) {
      zones[0] += 1;
    } else if (value <= 24) {
      zones[1] += 1;
    } else {
      zones[2] += 1;
    }
  });
  return zones.join(":");
}

function ZoneSignalCard({ title, scale, signal, tone }: { title: string; scale: string; signal: ZoneSignal; tone: "front" | "back" }) {
  const toneClass = tone === "front" ? "border-cyan-100" : "border-sky-100";
  const accentClass = tone === "front" ? "text-cyan-700" : "text-sky-700";
  return (
    <div className={`rounded-2xl border ${toneClass} bg-white/90 px-4 py-4`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className={`text-[11px] tracking-[0.18em] ${accentClass}`}>{title}</p>
          <p className="mt-2 text-sm font-semibold text-slate-900">{scale}</p>
        </div>
        <p className="text-right text-[11px] leading-5 text-slate-500">{signal.active_elements.map(displayElementName).join(" / ")}</p>
      </div>
      <div className="mt-3 grid gap-1.5 text-xs leading-6 text-slate-600">
        <div className="flex items-center justify-between gap-2">
          <span>主卦</span>
          <span className="font-medium text-slate-800">{displayHexagramName(signal.main_hexagram)}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span>互卦</span>
          <span className="font-medium text-slate-800">{displayHexagramName(signal.mutual_hexagram)}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span>变卦</span>
          <span className="font-medium text-slate-800">{displayHexagramName(signal.changed_hexagram)}</span>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-600">
        <div className="rounded-xl bg-slate-50 px-3 py-2">
          <p className="text-[10px] tracking-[0.16em] text-slate-400">偏好尾数</p>
          <p className="mt-1 font-medium text-slate-800">{signal.favored_tails.join(" / ")}</p>
        </div>
        <div className="rounded-xl bg-slate-50 px-3 py-2">
          <p className="text-[10px] tracking-[0.16em] text-slate-400">high-weight tails</p>
          <p className="mt-1 font-medium text-slate-800">{topTails(signal.tail_weights, 4)}</p>
        </div>
      </div>
    </div>
  );
}

function InsightCard({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <p className="text-xs text-slate-500">{title}</p>
      <p className="mt-1.5 text-base font-semibold text-slate-900">{value}</p>
    </div>
  );
}

function PanelTitle({
  title,
  hint,
}: {
  title: string;
  hint?: string;
  tone?: "default" | "warm";
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2 text-slate-900">
        <Layers3 className="h-4 w-4 text-slate-400" />
        <p className="text-sm font-semibold">{title}</p>
      </div>
      {hint ? <span className="text-xs text-slate-500">{hint}</span> : null}
    </div>
  );
}

function generationStatus(engine: string) {
  if (engine.includes("调用失败") || engine.includes("回朜")) {
    return {
      label: "AI fallback",
      hint: "External AI failed, using local result.",
      tone: "border-amber-200 bg-amber-50 text-amber-700",
    };
  }
  if (engine.includes("AI 接口")) {
    return {
      label: "AI finalized",
      hint: "Local draft first, then finalized by external AI.",
      tone: "border-emerald-200 bg-emerald-50 text-emerald-700",
    };
  }
  return {
    label: "Local model",
    hint: "No external AI used; final numbers come from the local model.",
    tone: "border-slate-200 bg-slate-50 text-slate-700",
  };
}

function FeaturedScheme({
  scheme,
  onSaveScheme,
  saving,
  saved,
  savedScheme,
}: {
  scheme: FinalScheme;
  onSaveScheme?: (scheme: FinalScheme) => void;
  saving?: boolean;
  saved?: boolean;
  savedScheme?: SavedScheme;
}) {
  const summary = purchaseSummary(savedScheme);
  return (
    <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white p-6 shadow-[0_8px_32px_rgba(15,23,42,0.05)] sm:p-8">
      <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-gradient-to-br from-red-500/8 to-blue-500/8 blur-3xl" />

      <div className="relative">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-900 px-2.5 py-0.5 text-[11px] font-medium tracking-wider text-white">
              <Trophy className="h-3 w-3" />
              {"FEATURED"}
            </span>
            <h3 className="mt-3 text-2xl font-semibold tracking-tight text-slate-900 sm:text-[26px]">{scheme.label}</h3>
            <p className="mt-1.5 text-sm leading-6 text-slate-500">{decodeEscapedUnicode(scheme.strategy)}</p>
            {summary ? (
              <div className="mt-3 inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs text-emerald-700">
                {summary}
              </div>
            ) : null}
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <div className="rounded-xl bg-slate-50 px-3 py-2 text-right">
              <p className="text-[10px] tracking-[0.2em] text-slate-400">{"CONF"}</p>
              <p className="text-xl font-semibold tabular-nums text-slate-900">{scheme.confidence.toFixed(2)}</p>
            </div>
            {onSaveScheme ? (
              <button
                onClick={() => onSaveScheme(scheme)}
                disabled={saving}
                className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-slate-900 px-4 text-xs font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? "\u4fdd\u5b58\u4e2d" : saved ? "\u66f4\u65b0\u672c\u671f\u8bbe\u7f6e" : "\u4fdd\u5b58\u672c\u671f\u5168\u90e8"}
              </button>
            ) : null}
          </div>
        </div>

        <div className="mt-7 flex flex-wrap items-center gap-2 sm:gap-2.5">
          {scheme.front_numbers.map((number) => (
            <LottoBall key={`${scheme.label}-featured-front-${number}`} number={number} tone="front" size="md" />
          ))}
          <span className="mx-0.5 text-xl font-light text-slate-300">+</span>
          {scheme.back_numbers.map((number) => (
            <LottoBall key={`${scheme.label}-featured-back-${number}`} number={number} tone="back" size="md" />
          ))}
        </div>

        <p className="mt-6 border-t border-slate-100 pt-5 text-[13px] leading-7 text-slate-600">
          {decodeEscapedUnicode(scheme.rationale)}
        </p>
      </div>
    </div>
  );
}

function SchemeCard({
  scheme,
  locked,
  onToggleLock,
  onSaveScheme,
  saving,
  saved,
  savedScheme,
}: {
  scheme: FinalScheme;
  locked: boolean;
  onToggleLock?: () => void;
  onSaveScheme?: () => void;
  saving?: boolean;
  saved?: boolean;
  savedScheme?: SavedScheme;
}) {
  const summary = purchaseSummary(savedScheme);
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">{scheme.label}</p>
          <p className="mt-1 text-xs text-slate-500">{decodeEscapedUnicode(scheme.strategy)}</p>
          {summary ? <p className="mt-1 text-xs text-emerald-700">{summary}</p> : null}
        </div>
        <div className="flex items-center gap-2">
          {onToggleLock ? (
            <button
              onClick={onToggleLock}
              className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs ${
                locked
                  ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                  : "border-slate-200 bg-slate-50 text-slate-700"
              }`}
            >
              {locked ? <Lock className="h-3 w-3" /> : <Unlock className="h-3 w-3" />}
              <span>{locked ? "\u5df2\u9501\u5b9a" : "\u9501\u5b9a"}</span>
            </button>
          ) : null}
          <button
            onClick={() => copyScheme(scheme)}
            className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-700"
          >
            {"\u590d\u5236"}
          </button>
          {onSaveScheme ? (
            <button
              onClick={onSaveScheme}
              disabled={saving}
              className="rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs text-cyan-700 disabled:opacity-60"
            >
              {saving ? "\u4fdd\u5b58\u4e2d..." : saved ? "\u66f4\u65b0\u672c\u671f" : "\u4fdd\u5b58\u5168\u90e8"}
            </button>
          ) : null}
        </div>
      </div>
      <div className="mt-4 overflow-x-auto pb-1">
        <div className="flex min-w-max items-center gap-2">
        {scheme.front_numbers.map((number) => (
          <LottoBall key={`${scheme.label}-front-${number}`} number={number} tone="front" size="sm" />
        ))}
        <span className="px-1 text-slate-500">+</span>
        {scheme.back_numbers.map((number) => (
          <LottoBall key={`${scheme.label}-back-${number}`} number={number} tone="back" size="sm" />
        ))}
        </div>
      </div>
    </div>
  );
}

function SchemeCompareBoard({ schemes }: { schemes: FinalScheme[] }) {
  const stats = (scheme: FinalScheme) => [
    { label: "\u524d\u533a\u548c", value: String(sum(scheme.front_numbers)) },
    { label: "\u8de8\u5ea6", value: String(span(scheme.front_numbers)) },
    { label: "\u5947\u5076", value: oddEven(scheme.front_numbers) },
    { label: "\u4e09\u533a", value: zoneSplit(scheme.front_numbers) },
    { label: "\u540e\u533a\u548c", value: String(sum(scheme.back_numbers)) },
  ];

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6">
      <PanelTitle title="Scheme Compare" hint="Quick comparison" />
      <div className="mt-5 space-y-3">
        {schemes.map((scheme, index) => (
          <div
            key={scheme.label}
            className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-slate-50/60 p-4 lg:flex-row lg:items-center lg:gap-6 lg:px-5"
          >
            {/* Label + confidence */}
            <div className="flex items-center justify-between gap-3 lg:w-44 lg:shrink-0 lg:flex-col lg:items-start lg:justify-center">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-900">{scheme.label}</p>
                <p className="mt-0.5 text-[11px] text-slate-500">{index === 0 ? "\u9996\u9009" : `#${index + 1}`}</p>
              </div>
              <span className="rounded-md bg-white px-2.5 py-1 text-xs font-semibold tabular-nums text-slate-800 shadow-sm">
                {scheme.confidence.toFixed(2)}
              </span>
            </div>

            {/* Balls */}
            <div className="flex flex-nowrap items-center gap-1.5 rounded-xl bg-white px-3 py-2 lg:shrink-0">
              {scheme.front_numbers.map((number) => (
                <LottoBall key={`${scheme.label}-compare-front-${number}`} number={number} tone="front" size="sm" />
              ))}
              <span className="mx-0.5 text-xs text-slate-300">+</span>
              {scheme.back_numbers.map((number) => (
                <LottoBall key={`${scheme.label}-compare-back-${number}`} number={number} tone="back" size="sm" />
              ))}
            </div>

            {/* Stats */}
            <dl className="grid flex-1 grid-cols-5 gap-2 lg:gap-3">
              {stats(scheme).map((item) => (
                <div key={item.label} className="rounded-lg bg-white px-2 py-2 text-center">
                  <dt className="text-[10px] tracking-[0.12em] text-slate-400">{item.label}</dt>
                  <dd className="mt-1 text-sm font-semibold tabular-nums text-slate-800">{item.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricTabs({ value, onChange }: { value: CandidateMetric; onChange: (metric: CandidateMetric) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {(Object.keys(metricLabels) as CandidateMetric[]).map((metric) => (
        <button
          key={metric}
          onClick={() => onChange(metric)}
          className={`rounded-full border px-3 py-1 text-xs transition ${
            value === metric
              ? "border-cyan-300 bg-cyan-50 text-cyan-700"
              : "border-slate-200 bg-white text-slate-600 hover:text-slate-900"
          }`}
        >
          {metricLabels[metric]}
        </button>
      ))}
    </div>
  );
}

function TopList({
  title,
  candidates,
  metric,
  tone,
}: {
  title: string;
  candidates: CandidateBreakdown[];
  metric: CandidateMetric;
  tone: "front" | "back";
}) {
  const ordered = [...candidates].sort((a, b) => Number(b[metric]) - Number(a[metric]) || a.number - b.number).slice(0, 10);
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <p className="text-sm font-medium text-slate-900">{title}</p>
      <div className="mt-4 space-y-2">
        {ordered.map((item, index) => (
          <div key={item.number} className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2">
            <div className="flex items-center gap-3">
              <span className="w-5 text-xs text-slate-500">{String(index + 1).padStart(2, "0")}</span>
              <LottoBall number={item.number} tone={tone} size="sm" />
            </div>
            <div className="text-sm text-slate-700">
              {Number(item[metric]).toFixed(metric === "score" || metric === "tail_weight" ? 2 : 0)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CandidateGrid({
  title,
  candidates,
  tone,
  metric,
  onMetricChange,
}: {
  title: string;
  candidates: CandidateBreakdown[];
  tone: "front" | "back";
  metric: CandidateMetric;
  onMetricChange: (metric: CandidateMetric) => void;
}) {
  const gridCols = tone === "front" ? "grid-cols-5 sm:grid-cols-7" : "grid-cols-4 sm:grid-cols-6";
  const ringTone = tone === "front" ? "ring-red-300/60" : "ring-sky-300/60";
  const bgTone = tone === "front" ? "bg-red-500/8" : "bg-sky-500/8";
  const ordered = useMemo(
    () => [...candidates].sort((a, b) => Number(b[metric]) - Number(a[metric]) || a.number - b.number),
    [candidates, metric],
  );

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm font-medium text-slate-900">{title}</p>
        <MetricTabs value={metric} onChange={onMetricChange} />
      </div>
      <div className={`mt-4 grid ${gridCols} gap-3`}>
        {ordered.map((item) => (
          <div
            key={item.number}
            className={`rounded-2xl border border-slate-200 p-2 text-center transition ${
              item.selected ? `bg-white ring-1 ${ringTone} ${bgTone}` : "bg-white"
            }`}
          >
            <div className="flex justify-center">
              <LottoBall number={item.number} tone={tone} size="sm" />
            </div>
            <p className="mt-2 text-[11px] text-slate-600">
              {metricLabels[metric]} {Number(item[metric]).toFixed(metric === "score" || metric === "tail_weight" ? 2 : 0)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function ScoreRow({ title, numbers, tone }: { title: string; numbers: RecommendationNumber[]; tone: "front" | "back" }) {
  const chipTone =
    tone === "front"
      ? "border-red-200 bg-red-50 text-red-700"
      : "border-sky-200 bg-sky-50 text-sky-700";

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <p className="text-sm font-medium text-slate-900">{title}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {numbers.map((item) => (
          <div key={item.number} className={`rounded-full border px-3 py-1 text-xs ${chipTone}`} title={item.reason}>
            {String(item.number).padStart(2, "0")} / {item.score.toFixed(2)}
          </div>
        ))}
      </div>
    </div>
  );
}

function TailWeightPanel({ items }: { items: TailWeightItem[] }) {
  const maxWeight = Math.max(...items.map((item) => item.weight), 1);
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <p className="text-sm font-medium text-slate-900">尾数权重</p>
      <div className="mt-4 space-y-2">
        {items.map((item) => (
          <div key={item.tail} className="grid grid-cols-[24px_1fr_44px] items-center gap-3 text-sm">
            <span className="text-slate-700">{item.tail}</span>
            <div className="h-2 rounded-full bg-slate-200">
              <div
                className="h-2 rounded-full bg-[linear-gradient(90deg,_rgba(56,189,248,0.9),_rgba(251,191,36,0.9))]"
                style={{ width: `${(item.weight / maxWeight) * 100}%` }}
              />
            </div>
            <span className="text-right text-slate-600">{item.weight.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PendingReveal({ hasResult }: { hasResult: boolean }) {
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center rounded-[30px] bg-slate-950/72 backdrop-blur-md">
      <div className="w-full max-w-md rounded-[28px] border border-cyan-300/20 bg-[linear-gradient(180deg,_rgba(8,47,73,0.58),_rgba(15,23,42,0.95))] px-6 py-7 text-center shadow-[0_24px_80px_rgba(2,6,23,0.45)]">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full border border-cyan-300/30 bg-cyan-300/15 text-cyan-50">
          <LoaderCircle className="h-6 w-6 animate-spin" />
        </div>
        <p className="mt-4 text-lg font-semibold text-white">{"\u6b63\u5728\u91cd\u7ec4\u4e00\u7b49\u5956\u65b9\u6848"}</p>
        <p className="mt-2 text-sm leading-7 text-slate-300">
          {hasResult ? "\u65b0\u7684\u63a8\u6f14\u7ed3\u679c\u5c06\u8986\u76d6\u5f53\u524d\u5c55\u793a\u3002" : "\u6b63\u5728\u751f\u6210\u9996\u6279\u65b9\u6848\u3002"}
        </p>
      </div>
    </div>
  );
}

export function RecommendationPanel({
  result,
  loading = false,
  error = null,
  lockedSchemes = [],
  onToggleSchemeLock,
  onSaveScheme,
  savingSchemeLabels = [],
  savedSchemeLabels = [],
  savedSchemeMap = new Map<string, SavedScheme>(),
}: RecommendationPanelProps) {
  const [frontMetric, setFrontMetric] = useState<CandidateMetric>("score");
  const [backMetric, setBackMetric] = useState<CandidateMetric>("score");
  const [copying, setCopying] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [shareToast, setShareToast] = useState<string | null>(null);
  const captureRef = useRef<HTMLDivElement | null>(null);
  const toastTimerRef = useRef<number | null>(null);
  const generatedSchemes = result?.final_schemes ?? [];
  const featuredScheme = result?.final_schemes[0] ?? null;
  const otherSchemes = result?.final_schemes.slice(1) ?? [];
  const aiStatus = result ? generationStatus(result.ai_analysis.engine) : null;
  const liveDecisionLabel = result ? (result.should_observe ? "观望" : "出手") : null;
  const hasEmptyResult = !!result && result.final_schemes.length === 0;
  const compareSchemes = useMemo(() => {
    if (!result) {
      return [];
    }
    if (lockedSchemes.length > 0) {
      const locked = result.final_schemes.filter((scheme) => lockedSchemes.includes(scheme.label));
      return locked.length > 0 ? locked : result.final_schemes;
    }
    return result.final_schemes;
  }, [lockedSchemes, result]);

  function showShareToast(message: string) {
    setShareToast(message);
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setShareToast(null), 2400);
  }

  return (
    <section className="relative rounded-3xl border border-slate-200 bg-white p-6 shadow-[0_8px_32px_rgba(15,23,42,0.05)] sm:p-7">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-5">
        <div>
          <p className="text-[11px] font-medium tracking-[0.24em] text-slate-500">{"RESULT \u00b7 \u63a8\u6f14\u7ed3\u679c"}</p>
          <h2 className="mt-1.5 text-xl font-semibold tracking-tight text-slate-900">{"\u4e00\u7b49\u5956\u76ee\u6807\u53f7\u7801"}</h2>
        </div>
        {result ? (
          <div className="relative flex items-center gap-2">
            {generatedSchemes.length > 0 ? (
              <button
                onClick={async () => {
                  if (copying) return;
                  setCopying(true);
                  setShareToast(null);
                  try {
                    await copySchemes(generatedSchemes);
                    showShareToast(`\u5df2\u590d\u5236 ${generatedSchemes.length} \u7ec4\u53f7\u7801`);
                  } catch (err) {
                    console.error("copy failed", err);
                    showShareToast("\u590d\u5236\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5");
                  } finally {
                    setCopying(false);
                  }
                }}
                disabled={copying}
                className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-70"
              >
                <Copy className="h-3.5 w-3.5" />
                <span>{copying ? "\u590d\u5236\u4e2d..." : "\u590d\u5236"}</span>
              </button>
            ) : null}
            <button
              onClick={async () => {
                if (!captureRef.current || sharing) return;
                setSharing(true);
                setShareToast(null);
                try {
                  const outcome = await shareSchemesAsImage(captureRef.current);
                  showShareToast(outcome === "copied" ? "\u5df2\u590d\u5236\u5230\u526a\u8d34\u677f\uff0c\u53ef\u76f4\u63a5\u7c98\u8d34" : "\u5df2\u4e0b\u8f7d\u56fe\u7247");
                } catch (err) {
                  console.error("share failed", err);
                  showShareToast("\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5");
                } finally {
                  setSharing(false);
                }
              }}
              disabled={sharing}
              className="inline-flex items-center gap-1.5 rounded-xl bg-slate-900 px-3.5 py-2 text-xs font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
            >
              <Share2 className="h-3.5 w-3.5" />
              <span>{sharing ? "\u751f\u6210\u4e2d..." : "\u5206\u4eab"}</span>
            </button>
            {shareToast ? (
              <div className="pointer-events-none absolute right-0 top-full z-10 mt-2 whitespace-nowrap rounded-lg bg-slate-900 px-3 py-1.5 text-xs text-white shadow-lg">
                {shareToast}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {!result ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 px-4 py-16 text-center text-sm text-slate-500">
          {"\u8f93\u5165\u63a8\u6f14\u7ec4\u6570\u540e\u70b9\u51fb\u300c\u5f00\u59cb\u63a8\u6f14\u300d\uff0c\u7cfb\u7edf\u4f1a\u8fd4\u56de\u5bf9\u5e94\u6570\u91cf\u7684\u4e00\u7b49\u5956\u76ee\u6807\u65b9\u6848\u3002"}
        </div>
      ) : hasEmptyResult ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-6 text-amber-900">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
            <div>
              <p className="text-sm font-semibold">{"本次推演未生成号码组合"}</p>
              <p className="mt-2 text-sm leading-7">
                {error || decodeEscapedUnicode(result.decision_reason ?? result.ai_analysis.final_advice ?? "当前置信度未通过实战阈值，本期建议观望。")}
              </p>
              <div className="mt-4 grid gap-3 text-xs text-amber-800 sm:grid-cols-3">
                <div className="rounded-xl border border-amber-200 bg-white/70 px-3 py-2">
                  <p className="text-amber-600">{"校准置信"}</p>
                  <p className="mt-1 font-semibold">{result.calibrated_confidence != null ? result.calibrated_confidence.toFixed(3) : "-"}</p>
                </div>
                <div className="rounded-xl border border-amber-200 bg-white/70 px-3 py-2">
                  <p className="text-amber-600">{"实战阈值"}</p>
                  <p className="mt-1 font-semibold">{result.applied_threshold != null ? result.applied_threshold.toFixed(3) : "-"}</p>
                </div>
                <div className="rounded-xl border border-amber-200 bg-white/70 px-3 py-2">
                  <p className="text-amber-600">{"决策层级"}</p>
                  <p className="mt-1 font-semibold">{result.decision_tier ?? "observe"}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {result.should_observe ? (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                <p>
                  {"当前仍建议观望；下方号码仅作为推演参考组合展示，不代表实战出手信号。"}
                </p>
              </div>
            </div>
          ) : null}
          <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
            <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-6">
              <div className="flex items-center gap-2 text-slate-900">
                <BrainCircuit className="h-4 w-4 text-slate-500" />
                <p className="text-sm font-semibold">{result.ai_analysis.engine}</p>
              </div>
              {aiStatus ? (
                <>
                  <div className={`mt-3 inline-flex rounded-full border px-3 py-1 text-xs font-medium ${aiStatus.tone}`}>
                    {aiStatus.label}
                  </div>
                  <p className="mt-3 text-xs leading-6 text-slate-500">{aiStatus.hint}</p>
                </>
              ) : null}
              <p className="mt-3 text-[13px] leading-7 text-slate-700">{decodeEscapedUnicode(result.ai_analysis.overview)}</p>
              <p className="mt-3 border-t border-slate-200/70 pt-3 text-[13px] leading-7 text-slate-600">{decodeEscapedUnicode(result.ai_analysis.final_advice)}</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <InsightCard title="Schemes" value={String(result.final_schemes.length)} />
              <InsightCard title="Decision" value={liveDecisionLabel ?? "-"} />
              <InsightCard
                title="校准置信"
                value={result.calibrated_confidence != null ? result.calibrated_confidence.toFixed(3) : "-"}
              />
              <InsightCard
                title="实战阈值"
                value={result.applied_threshold != null ? result.applied_threshold.toFixed(3) : "-"}
              />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <InsightCard title="调参方案" value={result.tuning_profile ?? "-"} />
              <InsightCard
                title="原始置信"
                value={result.issue_confidence != null ? result.issue_confidence.toFixed(3) : "-"}
              />
              <InsightCard title="Deep Search" value={result.deep_search_triggered ? "Triggered" : "Skipped"} />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <InsightCard title="起卦时点" value={result.divination_datetime} />
              <InsightCard title="应期开奖" value={result.target_draw_datetime} />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <InsightCard
                title="前区置信"
                value={
                  result.front_calibrated_confidence != null && result.front_gate != null
                    ? `${result.front_calibrated_confidence.toFixed(3)} / ${result.front_gate.toFixed(3)}`
                    : "-"
                }
              />
              <InsightCard
                title="后区置信"
                value={
                  result.back_calibrated_confidence != null && result.back_gate != null
                    ? `${result.back_calibrated_confidence.toFixed(3)} / ${result.back_gate.toFixed(3)}`
                    : "-"
                }
              />
              <InsightCard title="Decision Policy" value={result.count_policy ?? `Line ${result.moving_line}`} />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <InsightCard title="Active elements" value={result.active_elements.map(displayElementName).join(" / ")} />
              <InsightCard title="偏好尾数" value={result.favored_tails.join(" / ")} />
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-4">
              <p className="text-xs font-medium text-slate-500">实战解释</p>
              <p className="mt-2 text-sm leading-6 text-slate-700">
                {decodeEscapedUnicode(result.decision_reason ?? "当前未生成额外解释。")}
              </p>
              <p className="mt-2 border-t border-slate-200 pt-2 text-xs leading-6 text-slate-500">
                {decodeEscapedUnicode(result.deep_search_reason ?? "当前未触发深搜说明。")}
              </p>
            </div>
          </div>

          {featuredScheme ? (
            <FeaturedScheme
              scheme={featuredScheme}
              onSaveScheme={onSaveScheme}
              saving={savingSchemeLabels.includes(featuredScheme.label)}
              saved={savedSchemeLabels.includes(featuredScheme.label)}
              savedScheme={savedSchemeMap.get(featuredScheme.label)}
            />
          ) : null}

          {result.final_schemes.length > 1 ? (
            <p className="-mt-2 px-1 text-[12px] leading-6 text-slate-500">
              {result.strategy_mode === "smart_balance"
                ? "\u5f53\u524d\u4f7f\u7528\u667a\u80fd\u5e73\u8861\u6a21\u5f0f\uff1a\u7cfb\u7edf\u5148\u6839\u636e\u8fd1\u671f\u56de\u653e\u7ed3\u679c\u5728\u591a\u6ce8\u8986\u76d6\u4e0e\u5355\u6ce8\u4f18\u5148\u6863\u4f4d\u4e4b\u95f4\u62e9\u4f18\uff0c\u518d\u7528\u9009\u4e2d\u6863\u4f4d\u751f\u6210\u5f53\u671f\u53f7\u7801\u3002"
                : result.strategy_mode === "single_hit"
                ? "\u5f53\u524d\u4f7f\u7528\u5355\u6ce8\u4f18\u5148\u6a21\u5f0f\uff1a\u591a\u7ec4\u65b9\u6848\u56f4\u7ed5\u9ad8\u5206\u6838\u5fc3\u53f7\u505a\u53d8\u4f53\uff0c\u76ee\u6807\u662f\u63d0\u5347\u524d\u51e0\u7ec4\u7684\u5355\u6ce8\u547d\u4e2d\u80fd\u529b\uff0c\u800c\u4e0d\u662f\u6700\u5927\u5316\u7ec4\u4e0e\u7ec4\u4e4b\u95f4\u7684\u8986\u76d6\u9762\u3002"
                : "\u591a\u6ce8\u91c7\u7528\u8d2a\u5fc3\u8986\u76d6\u4f18\u5316\u7b56\u7565\uff1a\u9996\u9009\u9501\u5b9a\u9ad8\u5206\u6838\u5fc3\u53f7\uff0c\u540e\u7eed\u5907\u9009\u4f18\u5148\u9009\u53d6\u5c1a\u672a\u88ab\u8986\u76d6\u7684\u9ad8\u5206\u53f7\u7801\uff0c\u4ee5\u63d0\u9ad8\u591a\u6ce8\u81f3\u5c11\u547d\u4e2d 1 \u7801\u7684\u6982\u7387\uff1b\u5f69\u7968\u4e3a i.i.d. \u968f\u673a\u8fc7\u7a0b\uff0c\u4efb\u4f55\u7b56\u7565\u4ec5\u80fd\u964d\u4f4e'\u5168\u90e8\u843d\u7a7a'\u7684\u65b9\u5dee\uff0c\u7406\u6027\u8d2d\u5f69\u3002"}
            </p>
          ) : null}

          <div className="grid gap-5">
            <div className="rounded-3xl border border-slate-200 bg-white p-6">
              <PanelTitle
                title="More Schemes"
                hint={otherSchemes.length > 0 ? `\u5df2\u9501\u5b9a ${lockedSchemes.length} / ${Math.min(3, otherSchemes.length + 1)}` : undefined}
              />
              <div className="mt-5 grid gap-3">
                {otherSchemes.length > 0 ? (
                  otherSchemes.map((scheme) => (
                    <SchemeCard
                      key={scheme.label}
                      scheme={scheme}
                      locked={lockedSchemes.includes(scheme.label)}
                      onToggleLock={onToggleSchemeLock ? () => onToggleSchemeLock(scheme.label) : undefined}
                      onSaveScheme={onSaveScheme ? () => onSaveScheme(scheme) : undefined}
                      saving={savingSchemeLabels.includes(scheme.label)}
                      saved={savedSchemeLabels.includes(scheme.label)}
                      savedScheme={savedSchemeMap.get(scheme.label)}
                    />
                  ))
                ) : (
                  <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 px-4 py-10 text-center">
                    <p className="text-sm font-medium text-slate-700">{"\u5f53\u524d\u4ec5\u8fd4\u56de\u4e86 1 \u7ec4\u9996\u9009\u65b9\u6848"}</p>
                    <p className="mt-1.5 text-xs leading-6 text-slate-500">{"\u53ef\u5728\u9876\u90e8\u8c03\u9ad8\u63a8\u6f14\u7ec4\u6570\uff08\u5982 3 / 5 / 8\uff09\u540e\u91cd\u65b0\u63a8\u6f14\uff0c\u67e5\u770b\u591a\u7ec4\u5907\u9009\u3002"}</p>
                  </div>
                )}
              </div>
            </div>


            <div className="rounded-3xl border border-slate-200 bg-white p-6">
              <PanelTitle title="卦象摘要" />
              <div className="mt-5 grid gap-3">
                <div className="rounded-xl bg-slate-50 px-4 py-3.5">
                  <p className="text-[11px] tracking-[0.18em] text-slate-400">{"\u5366\u8c61\u8def\u5f84"}</p>
                  <div className="mt-2 grid gap-1.5 text-sm text-slate-800">
                    <div className="flex items-center justify-between gap-2"><span className="text-slate-500">{"\u4e3b\u5366"}</span><span className="font-medium">{displayHexagramName(result.main_hexagram)}</span></div>
                    <div className="flex items-center justify-between gap-2"><span className="text-slate-500">{"\u4e92\u5366"}</span><span className="font-medium">{displayHexagramName(result.mutual_hexagram)}</span></div>
                    <div className="flex items-center justify-between gap-2"><span className="text-slate-500">{"\u53d8\u5366"}</span><span className="font-medium">{displayHexagramName(result.changed_hexagram)}</span></div>
                  </div>
                </div>
                <div className="rounded-xl bg-slate-50 px-4 py-3.5">
                  <p className="text-[11px] tracking-[0.18em] text-slate-400">{"\u7ed3\u6784\u6458\u8981"}</p>
                  <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                    <div>
                      <p className="text-xs text-slate-500">{"\u524d\u533a\u548c"}</p>
                      <p className="mt-0.5 text-lg font-semibold tabular-nums text-slate-900">{result.summary.front_sum}</p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">{"\u524d\u533a\u5947\u5076"}</p>
                      <p className="mt-0.5 text-lg font-semibold tabular-nums text-slate-900">{result.summary.front_odd_even}</p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">{"\u540e\u533a\u5947\u5076"}</p>
                      <p className="mt-0.5 text-lg font-semibold tabular-nums text-slate-900">{result.summary.back_odd_even}</p>
                    </div>
                  </div>
                </div>
              </div>
              <p className="mt-5 text-[13px] leading-7 text-slate-600">{decodeEscapedUnicode(result.summary.explanation)}</p>
            </div>
          </div>

          {result.front_signal && result.back_signal ? (
            <div className="rounded-3xl border border-slate-200 bg-white p-6">
              <PanelTitle title="Split Signals" />
              <div className="mt-5 grid gap-3 lg:grid-cols-2">
                <ZoneSignalCard title="Front pool" scale="35 choose 5 modeled separately" signal={result.front_signal} tone="front" />
                <ZoneSignalCard title="Back pool" scale="12 choose 2 modeled separately" signal={result.back_signal} tone="back" />
              </div>
              <p className="mt-4 text-xs leading-6 text-slate-600">
                {`Front top candidates: ${topNumbers(result.front_candidates, 5)}; back top candidates: ${topNumbers(result.back_candidates, 2)}. They are scored separately before final assembly.`}
              </p>
            </div>
          ) : null}

          {!featuredScheme && result.should_observe ? (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-800">
              当前校准后置信度未通过实战阈值，本期建议观望。
            </div>
          ) : null}

          {compareSchemes.length > 0 ? <SchemeCompareBoard schemes={compareSchemes} /> : null}

          <div className="grid gap-4 xl:grid-cols-[0.92fr_1.08fr]">
            <TailWeightPanel items={result.tail_weights} />
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <p className="text-sm font-medium text-slate-900">前区结构</p>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-700">
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">和?{result.summary.front_sum}</div>
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">跨度 {result.summary.front_span}</div>
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">奇偶?{result.summary.front_odd_even}</div>
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">
                    三区 {zoneSplit(result.front_recommendations.map((item) => item.number))}
                  </div>
                </div>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <p className="text-sm font-medium text-slate-900">后区结构</p>
                <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-700">
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">和?{result.summary.back_sum}</div>
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">跨度 {result.summary.back_span}</div>
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">奇偶?{result.summary.back_odd_even}</div>
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">号码?2</div>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-white p-4 shadow-sm">
            <PanelTitle title="Candidate Heat" hint="Switch between metrics" />
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <TopList title={`前区 Top 10 ${metricLabels[frontMetric]}`} candidates={result.front_candidates} metric={frontMetric} tone="front" />
              <TopList title={`后区 Top 10 ${metricLabels[backMetric]}`} candidates={result.back_candidates} metric={backMetric} tone="back" />
            </div>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <CandidateGrid title="Front candidates" candidates={result.front_candidates} tone="front" metric={frontMetric} onMetricChange={setFrontMetric} />
              <CandidateGrid title="Back candidates" candidates={result.back_candidates} tone="back" metric={backMetric} onMetricChange={setBackMetric} />
            </div>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <ScoreRow title="Front scored numbers" numbers={result.front_recommendations} tone="front" />
              <ScoreRow title="Back scored numbers" numbers={result.back_recommendations} tone="back" />
            </div>
          </div>
        </div>
      )}

      {loading ? <PendingReveal hasResult={!!result} /> : null}

      {/* Offscreen share poster: only schemes, used for screenshot */}
      {result ? (
        <div
          aria-hidden
          style={{ position: "fixed", left: "-10000px", top: 0, pointerEvents: "none" }}
        >
          <div
            ref={captureRef}
            style={{ width: "520px", padding: "28px", background: "#ffffff", fontFamily: 'system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif' }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingBottom: "16px", borderBottom: "1px solid #e2e8f0" }}>
              <p style={{ margin: 0, fontSize: "10px", letterSpacing: "0.24em", color: "#64748b", fontWeight: 500 }}>SUPER LOTTO</p>
              <p style={{ margin: 0, fontSize: "10px", color: "#94a3b8" }}>{result.final_schemes.length} schemes</p>
            </div>

            <div style={{ marginTop: "16px", border: "1px solid #e2e8f0", borderRadius: "14px", padding: "12px 14px", background: "#f8fafc" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "8px" }}>
                <div style={{ fontSize: "11px", color: "#475569" }}>决策 {result.should_observe ? "观望" : "出手"}</div>
                <div style={{ fontSize: "11px", color: "#475569" }}>
                  校准 {result.calibrated_confidence != null ? result.calibrated_confidence.toFixed(3) : "-"}
                </div>
                <div style={{ fontSize: "11px", color: "#475569" }}>
                  阈值 {result.applied_threshold != null ? result.applied_threshold.toFixed(3) : "-"}
                </div>
                <div style={{ fontSize: "11px", color: "#475569" }}>
                  调参 {result.tuning_profile ?? "-"}
                </div>
              </div>
              <div style={{ marginTop: "8px", fontSize: "10px", color: "#64748b", lineHeight: 1.6 }}>
                {decodeEscapedUnicode(result.decision_reason ?? result.ai_analysis.final_advice)}
              </div>
            </div>

            <div style={{ marginTop: "20px", display: "flex", flexDirection: "column", gap: "12px" }}>
              {result.final_schemes.map((scheme, index) => (
                <div
                  key={`poster-${scheme.label}`}
                  style={{
                    border: "1px solid #e2e8f0",
                    borderRadius: "16px",
                    padding: "14px 16px",
                    background: index === 0 ? "linear-gradient(135deg,#fafafa,#ffffff)" : "#ffffff",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "10px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{ fontSize: "11px", fontWeight: 600, color: "#fff", background: "#0f172a", padding: "2px 8px", borderRadius: "999px" }}>
                        {index + 1}
                      </span>
                      <span style={{ fontSize: "14px", fontWeight: 600, color: "#0f172a" }}>{scheme.label}</span>
                    </div>
                    <span style={{ fontSize: "12px", color: "#64748b", fontVariantNumeric: "tabular-nums" }}>
                      倾向 {scheme.confidence.toFixed(2)}
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "nowrap" }}>
                    {scheme.front_numbers.map((n) => (
                      <PosterBall key={`poster-${scheme.label}-f-${n}`} number={n} tone="front" />
                    ))}
                    <span style={{ color: "#cbd5e1", fontSize: "16px", margin: "0 2px" }}>+</span>
                    {scheme.back_numbers.map((n) => (
                      <PosterBall key={`poster-${scheme.label}-b-${n}`} number={n} tone="back" />
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <p style={{ marginTop: "18px", fontSize: "10px", color: "#94a3b8", textAlign: "center" }}>
              大乐透推演中?· 仅供参，理购?            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function PosterBall({ number, tone }: { number: number; tone: "front" | "back" }) {
  const isFront = tone === "front";
  return (
    <div
      style={{
        width: "36px",
        height: "36px",
        borderRadius: "50%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#ffffff",
        fontSize: "14px",
        fontWeight: 600,
        fontVariantNumeric: "tabular-nums",
        background: isFront
          ? "radial-gradient(circle at 30% 28%, #fb7185, #dc2626 70%)"
          : "radial-gradient(circle at 30% 28%, #60a5fa, #1d4ed8 70%)",
        boxShadow: isFront ? "0 3px 8px rgba(220,38,38,0.28)" : "0 3px 8px rgba(29,78,216,0.28)",
      }}
    >
      {String(number).padStart(2, "0")}
    </div>
  );
}
