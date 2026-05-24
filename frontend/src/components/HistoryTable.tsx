import { useEffect, useMemo, useState } from "react";
import { CalendarRange, Search, SlidersHorizontal, X } from "lucide-react";
import type { FinalScheme, LottoDraw } from "../lib/types";
import { LottoBall } from "./LottoBall";

interface HistoryTableProps {
  rows: LottoDraw[];
  highlightedSchemes?: FinalScheme[];
}

const pageSizes = [50, 100, 200];
const historyWindows = [
  { value: "30", label: "\u6700\u8fd1 30 \u671f", count: 30 },
  { value: "100", label: "\u6700\u8fd1 100 \u671f", count: 100 },
  { value: "all", label: "\u5168\u90e8\u5386\u53f2", count: 0 },
] as const;
const sumRangeOptions = [
  { value: "all", label: "\u5168\u90e8\u548c\u503c" },
  { value: "low", label: "\u524d\u533a\u548c\u503c 60 \u4ee5\u4e0b" },
  { value: "mid", label: "\u524d\u533a\u548c\u503c 60-100" },
  { value: "high", label: "\u524d\u533a\u548c\u503c 100 \u4ee5\u4e0a" },
];
const oddEvenOptions = [
  { value: "all", label: "\u5168\u90e8\u5947\u5076\u6bd4" },
  { value: "5:0", label: "5:0" },
  { value: "4:1", label: "4:1" },
  { value: "3:2", label: "3:2" },
  { value: "2:3", label: "2:3" },
  { value: "1:4", label: "1:4" },
  { value: "0:5", label: "0:5" },
];
const zonePatternOptions = [
  { value: "all", label: "\u5168\u90e8\u533a\u95f4\u5206\u5e03" },
  { value: "3:1:1", label: "3:1:1" },
  { value: "2:2:1", label: "2:2:1" },
  { value: "2:1:2", label: "2:1:2" },
  { value: "1:2:2", label: "1:2:2" },
  { value: "1:1:3", label: "1:1:3" },
];

function frontSum(numbers: number[]) {
  return numbers.reduce((sum, value) => sum + value, 0);
}

function oddEvenRatio(numbers: number[]) {
  const odd = numbers.filter((value) => value % 2 !== 0).length;
  return `${odd}:${numbers.length - odd}`;
}

function zonePattern(numbers: number[]) {
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

function frontSpan(numbers: number[]) {
  return numbers.length > 0 ? Math.max(...numbers) - Math.min(...numbers) : 0;
}

function matchSumRange(value: number, range: string) {
  if (range === "low") {
    return value < 60;
  }
  if (range === "mid") {
    return value >= 60 && value <= 100;
  }
  if (range === "high") {
    return value > 100;
  }
  return true;
}

function matchMetrics(draw: LottoDraw, scheme: FinalScheme) {
  const sumMatched = frontSum(draw.front_numbers) === frontSum(scheme.front_numbers);
  const oddEvenMatched = oddEvenRatio(draw.front_numbers) === oddEvenRatio(scheme.front_numbers);
  const zoneMatched = zonePattern(draw.front_numbers) === zonePattern(scheme.front_numbers);
  const score = Number(sumMatched) + Number(oddEvenMatched) + Number(zoneMatched);
  return { score };
}

function strengthTone(score: number) {
  if (score >= 3) {
    return {
      row: "border-cyan-200 bg-cyan-50/70",
      cell: "border-cyan-200 bg-cyan-50",
      badge: "border-cyan-200 bg-cyan-100 text-cyan-700",
      label: "\u5f3a\u547d\u4e2d",
    };
  }
  if (score === 2) {
    return {
      row: "border-amber-200 bg-amber-50/70",
      cell: "border-amber-200 bg-amber-50",
      badge: "border-amber-200 bg-amber-100 text-amber-700",
      label: "\u4e2d\u547d\u4e2d",
    };
  }
  if (score === 1) {
    return {
      row: "border-violet-200 bg-violet-50/70",
      cell: "border-violet-200 bg-violet-50",
      badge: "border-violet-200 bg-violet-100 text-violet-700",
      label: "\u5f31\u547d\u4e2d",
    };
  }
  return {
    row: "border-slate-200",
    cell: "border-slate-200 bg-slate-50",
    badge: "border-slate-200 bg-white text-slate-500",
    label: "\u672a\u547d\u4e2d",
  };
}

export function HistoryTable({ rows, highlightedSchemes = [] }: HistoryTableProps) {
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);
  const [issueQuery, setIssueQuery] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [frontTail, setFrontTail] = useState("all");
  const [backTail, setBackTail] = useState("all");
  const [sumRange, setSumRange] = useState("all");
  const [oddEvenFilter, setOddEvenFilter] = useState("all");
  const [zonePatternFilter, setZonePatternFilter] = useState("all");
  const [historyWindow, setHistoryWindow] = useState<(typeof historyWindows)[number]["value"]>("30");
  const [schemeView, setSchemeView] = useState("all");

  const windowedRows = useMemo(() => {
    const setting = historyWindows.find((item) => item.value === historyWindow);
    if (!setting || setting.value === "all") {
      return rows;
    }
    return rows.slice(0, setting.count);
  }, [historyWindow, rows]);

  const filteredRows = useMemo(() => {
    return windowedRows.filter((draw) => {
      const sum = frontSum(draw.front_numbers);
      const ratio = oddEvenRatio(draw.front_numbers);
      const zone = zonePattern(draw.front_numbers);

      if (issueQuery.trim() && !draw.issue.includes(issueQuery.trim())) {
        return false;
      }
      if (dateFrom && draw.draw_date < dateFrom) {
        return false;
      }
      if (dateTo && draw.draw_date > dateTo) {
        return false;
      }
      if (frontTail !== "all" && !draw.front_numbers.some((n) => n % 10 === Number(frontTail))) {
        return false;
      }
      if (backTail !== "all" && !draw.back_numbers.some((n) => n % 10 === Number(backTail))) {
        return false;
      }
      if (!matchSumRange(sum, sumRange)) {
        return false;
      }
      if (oddEvenFilter !== "all" && ratio !== oddEvenFilter) {
        return false;
      }
      if (zonePatternFilter !== "all" && zone !== zonePatternFilter) {
        return false;
      }
      return true;
    });
  }, [backTail, dateFrom, dateTo, frontTail, issueQuery, oddEvenFilter, sumRange, windowedRows, zonePatternFilter]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [filteredRows.length, page, pageSize]);

  useEffect(() => {
    setPage(1);
  }, [issueQuery, dateFrom, dateTo, frontTail, backTail, sumRange, oddEvenFilter, zonePatternFilter, historyWindow, schemeView]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const currentPage = Math.min(page, totalPages);

  const visibleRows = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredRows.slice(start, start + pageSize);
  }, [filteredRows, currentPage, pageSize]);

  const highlightedLabels = useMemo(
    () => highlightedSchemes.filter((scheme) => scheme?.label).map((scheme) => scheme.label),
    [highlightedSchemes],
  );

  const activeSchemes = useMemo(() => {
    if (schemeView === "all") {
      return highlightedSchemes;
    }
    return highlightedSchemes.filter((scheme) => scheme.label === schemeView);
  }, [highlightedSchemes, schemeView]);

  const matchSummary = useMemo(() => {
    if (activeSchemes.length === 0) {
      return null;
    }

    let strong = 0;
    let medium = 0;
    let weak = 0;

    filteredRows.forEach((draw) => {
      const bestScore = activeSchemes.reduce((max, scheme) => Math.max(max, matchMetrics(draw, scheme).score), 0);
      if (bestScore >= 3) {
        strong += 1;
      } else if (bestScore === 2) {
        medium += 1;
      } else if (bestScore === 1) {
        weak += 1;
      }
    });

    return { strong, medium, weak, total: filteredRows.length };
  }, [activeSchemes, filteredRows]);

  const hasFilters =
    issueQuery ||
    dateFrom ||
    dateTo ||
    frontTail !== "all" ||
    backTail !== "all" ||
    sumRange !== "all" ||
    oddEvenFilter !== "all" ||
    zonePatternFilter !== "all";

  function resetFilters() {
    setIssueQuery("");
    setDateFrom("");
    setDateTo("");
    setFrontTail("all");
    setBackTail("all");
    setSumRange("all");
    setOddEvenFilter("all");
    setZonePatternFilter("all");
  }

  return (
    <section className="rounded-[30px] border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,0.06)]">
      <div className="mb-5 grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div>
          <p className="text-xs tracking-[0.3em] text-cyan-700/70">{"\u5386\u53f2\u6570\u636e"}</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">{"\u5386\u53f2\u5f00\u5956\u6570\u636e"}</h2>
          <p className="mt-2 text-sm text-slate-600">
            {"\u7528\u5168\u5386\u53f2\u5f00\u5956\u6837\u672c\u56de\u770b\u7ed3\u6784\u5206\u5e03\uff0c\u5e76\u5bf9\u6bd4\u5df2\u9501\u5b9a\u65b9\u6848\u5728\u4e0d\u540c\u7a97\u53e3\u4e0b\u7684\u63a5\u8fd1\u5ea6\u3002"}
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p className="text-xs text-slate-500">{"\u5168\u91cf\u671f\u6570"}</p>
            <p className="mt-2 text-2xl font-semibold text-cyan-700">{rows.length}</p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p className="text-xs text-slate-500">{"\u5f53\u524d\u7b5b\u9009"}</p>
            <p className="mt-2 text-2xl font-semibold text-amber-700">{filteredRows.length}</p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p className="text-xs text-slate-500">{"\u6bcf\u9875\u6761\u6570"}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {pageSizes.map((size) => (
                <button
                  key={size}
                  onClick={() => {
                    setPageSize(size);
                    setPage(1);
                  }}
                  className={`rounded-full border px-3 py-1 text-xs transition ${
                    pageSize === size
                      ? "border-amber-300 bg-amber-50 text-amber-700"
                      : "border-slate-200 bg-white text-slate-500"
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="mb-4 grid gap-4 xl:grid-cols-[1.28fr_0.72fr]">
        <div className="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-slate-900">
              <SlidersHorizontal className="h-4 w-4 text-cyan-700" />
              <div>
                <p className="text-sm font-medium">{"\u5386\u53f2\u7ed3\u6784\u7b5b\u9009"}</p>
                <p className="mt-1 text-xs text-slate-500">{"\u5148\u9009\u7a97\u53e3\uff0c\u518d\u6309\u671f\u53f7\u3001\u65e5\u671f\u4e0e\u7ed3\u6784\u6761\u4ef6\u7ec4\u5408\u7b5b\u9009\u3002"}</p>
              </div>
            </div>
            {hasFilters ? (
              <button
                onClick={resetFilters}
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700"
              >
                <X className="h-3.5 w-3.5" />
                <span>{"\u6e05\u7a7a\u7b5b\u9009"}</span>
              </button>
            ) : null}
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {historyWindows.map((item) => (
              <button
                key={item.value}
                onClick={() => setHistoryWindow(item.value)}
                className={`rounded-full border px-3 py-1.5 text-xs transition ${
                  historyWindow === item.value
                    ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                    : "border-slate-200 bg-white text-slate-600"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <label className="grid gap-2">
              <span className="text-xs text-slate-500">{"\u671f\u53f7\u68c0\u7d22"}</span>
              <div className="relative">
                <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                <input
                  value={issueQuery}
                  onChange={(event) => setIssueQuery(event.target.value)}
                  placeholder={"\u4f8b\u5982 26051"}
                  className="h-10 w-full rounded-2xl border border-slate-200 bg-white pl-11 pr-4 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-cyan-300"
                />
              </div>
            </label>

            <label className="grid gap-2">
              <span className="text-xs text-slate-500">{"\u8d77\u59cb\u65e5\u671f"}</span>
              <div className="relative">
                <CalendarRange className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(event) => setDateFrom(event.target.value)}
                  className="h-10 w-full rounded-2xl border border-slate-200 bg-white pl-11 pr-4 text-sm text-slate-900 outline-none focus:border-cyan-300"
                />
              </div>
            </label>

            <label className="grid gap-2">
              <span className="text-xs text-slate-500">{"\u622a\u6b62\u65e5\u671f"}</span>
              <div className="relative">
                <CalendarRange className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                <input
                  type="date"
                  value={dateTo}
                  onChange={(event) => setDateTo(event.target.value)}
                  className="h-10 w-full rounded-2xl border border-slate-200 bg-white pl-11 pr-4 text-sm text-slate-900 outline-none focus:border-cyan-300"
                />
              </div>
            </label>

            <label className="grid gap-2">
              <span className="text-xs text-slate-500">{"\u524d\u533a\u548c\u503c"}</span>
              <select
                value={sumRange}
                onChange={(event) => setSumRange(event.target.value)}
                className="h-10 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none focus:border-cyan-300"
              >
                {sumRangeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="grid gap-2">
              <span className="text-xs text-slate-500">{"\u524d\u533a\u5947\u5076\u6bd4"}</span>
              <select
                value={oddEvenFilter}
                onChange={(event) => setOddEvenFilter(event.target.value)}
                className="h-10 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none focus:border-cyan-300"
              >
                {oddEvenOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="grid gap-2">
              <span className="text-xs text-slate-500">{"\u524d\u533a\u4e09\u533a\u5206\u5e03"}</span>
              <select
                value={zonePatternFilter}
                onChange={(event) => setZonePatternFilter(event.target.value)}
                className="h-10 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none focus:border-cyan-300"
              >
                {zonePatternOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="grid gap-2">
              <span className="text-xs text-slate-500">{"\u524d\u533a\u5c3e\u53f7"}</span>
              <select
                value={frontTail}
                onChange={(event) => setFrontTail(event.target.value)}
                className="h-10 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none focus:border-cyan-300"
              >
                <option value="all">{"\u5168\u90e8"}</option>
                {Array.from({ length: 10 }).map((_, index) => (
                  <option key={`front-tail-${index}`} value={String(index)}>
                    {index}
                  </option>
                ))}
              </select>
            </label>

            <label className="grid gap-2">
              <span className="text-xs text-slate-500">{"\u540e\u533a\u5c3e\u53f7"}</span>
              <select
                value={backTail}
                onChange={(event) => setBackTail(event.target.value)}
                className="h-10 rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none focus:border-cyan-300"
              >
                <option value="all">{"\u5168\u90e8"}</option>
                {Array.from({ length: 10 }).map((_, index) => (
                  <option key={`back-tail-${index}`} value={String(index)}>
                    {index}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="grid gap-4">
          <div className="rounded-[24px] border border-slate-200 bg-white p-4">
            <p className="text-sm font-medium text-slate-900">{"\u5206\u6790\u89c6\u89d2"}</p>
            <p className="mt-1 text-xs text-slate-500">{"\u5728\u8fd9\u91cc\u5207\u6362\u9501\u5b9a\u65b9\u6848\u89c6\u56fe\uff0c\u5feb\u901f\u67e5\u770b\u4e0e\u54ea\u7ec4\u63a8\u6f14\u8f83\u63a5\u8fd1\u3002"}</p>

            {highlightedSchemes.length > 0 ? (
              <div className="mt-4">
                <p className="text-xs text-slate-500">{"\u65b9\u6848\u89c6\u56fe"}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    onClick={() => setSchemeView("all")}
                    className={`rounded-full border px-3 py-1.5 text-xs transition ${
                      schemeView === "all"
                        ? "border-amber-300 bg-amber-50 text-amber-700"
                        : "border-slate-200 bg-slate-50 text-slate-600"
                    }`}
                  >
                    {"\u5168\u90e8\u9501\u5b9a\u65b9\u6848"}
                  </button>
                  {highlightedSchemes.map((scheme) => (
                    <button
                      key={scheme.label}
                      onClick={() => setSchemeView(scheme.label)}
                      className={`rounded-full border px-3 py-1.5 text-xs transition ${
                        schemeView === scheme.label
                          ? "border-amber-300 bg-amber-50 text-amber-700"
                          : "border-slate-200 bg-slate-50 text-slate-600"
                      }`}
                    >
                      {scheme.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                {"\u5148\u5728\u4e0a\u65b9\u63a8\u8350\u533a\u9501\u5b9a\u8981\u5bf9\u6bd4\u7684\u65b9\u6848\uff0c\u8fd9\u91cc\u624d\u4f1a\u51fa\u73b0\u5386\u53f2\u547d\u4e2d\u89c6\u56fe\u3002"}
              </div>
            )}
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-white p-4">
            <p className="text-sm font-medium text-slate-900">{"\u5f53\u524d\u5de5\u4f5c\u533a"}</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="text-xs text-slate-500">{"\u6837\u672c\u7a97\u53e3"}</p>
                <p className="mt-2 text-sm font-medium text-cyan-700">
                  {historyWindows.find((item) => item.value === historyWindow)?.label ?? "\u5168\u90e8\u5386\u53f2"}
                </p>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p className="text-xs text-slate-500">{"\u65b9\u6848\u89c6\u56fe"}</p>
                <p className="mt-2 text-sm font-medium text-amber-700">
                  {schemeView === "all" ? "\u5168\u90e8\u9501\u5b9a\u65b9\u6848" : schemeView}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {highlightedSchemes.length > 0 && matchSummary ? (
        <div className="mb-4 rounded-[24px] border border-cyan-200 bg-cyan-50 px-4 py-4">
          <p className="text-sm text-cyan-700">
            {"\u5f53\u524d\u5386\u53f2\u547d\u4e2d\u5206\u6790\u5bf9\u5e94\u65b9\u6848\uff1a"}
            {highlightedLabels.join(" / ")}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {"\u7ed3\u6784\u5bf9\u6bd4\u57fa\u4e8e\u524d\u533a\u548c\u503c\u3001\u5947\u5076\u6bd4\u3001\u4e09\u533a\u5206\u5e03\u4e09\u4e2a\u7ef4\u5ea6\u3002"}
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-4">
            <div className="rounded-2xl border border-cyan-200 bg-white px-3 py-3">
              <p className="text-xs text-cyan-600">{"\u5f3a\u547d\u4e2d"}</p>
              <p className="mt-1 text-lg font-semibold text-cyan-700">{matchSummary.strong}</p>
            </div>
            <div className="rounded-2xl border border-amber-200 bg-white px-3 py-3">
              <p className="text-xs text-amber-600">{"\u4e2d\u547d\u4e2d"}</p>
              <p className="mt-1 text-lg font-semibold text-amber-700">{matchSummary.medium}</p>
            </div>
            <div className="rounded-2xl border border-violet-200 bg-white px-3 py-3">
              <p className="text-xs text-violet-600">{"\u5f31\u547d\u4e2d"}</p>
              <p className="mt-1 text-lg font-semibold text-violet-700">{matchSummary.weak}</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3">
              <p className="text-xs text-slate-500">{"\u7a97\u53e3\u6837\u672c"}</p>
              <p className="mt-1 text-lg font-semibold text-slate-900">{matchSummary.total}</p>
            </div>
          </div>
        </div>
      ) : null}

      <div className="overflow-hidden rounded-[24px] border border-slate-200 bg-white">
        <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 py-4 backdrop-blur">
          <div>
            <p className="text-sm font-medium text-slate-900">{"\u5386\u53f2\u5f00\u5956\u8868"}</p>
            <p className="mt-1 text-xs text-slate-500">{`\u5f53\u524d\u663e\u793a ${visibleRows.length} \u6761\uff0c\u5171 ${filteredRows.length} \u6761\u7b5b\u9009\u7ed3\u679c`}</p>
          </div>
          <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600">
            {`\u7b2c ${currentPage} / ${totalPages} \u9875`}
          </div>
        </div>
        <div className="max-h-[980px] overflow-auto">
        <table className="min-w-full text-sm text-slate-700">
          <thead className="bg-slate-50 text-left text-slate-500">
            <tr className="border-b border-slate-200">
              <th className="px-4 py-4 font-medium">{"\u671f\u53f7"}</th>
              <th className="px-4 py-4 font-medium">{"\u65e5\u671f"}</th>
              <th className="px-4 py-4 font-medium">{"\u5f00\u5956\u53f7\u7801"}</th>
              <th className="px-4 py-4 font-medium">{"\u7ed3\u6784"}</th>
              <th className="px-4 py-4 font-medium">{"\u5956\u6c60"}</th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.length > 0 ? (
              visibleRows.map((draw) => {
                const bestMatch =
                  activeSchemes.length > 0
                    ? activeSchemes.reduce<{ scheme: FinalScheme | null; score: number }>(
                        (best, scheme) => {
                          const current = matchMetrics(draw, scheme);
                          if (current.score > best.score) {
                            return { scheme, score: current.score };
                          }
                          return best;
                        },
                        { scheme: null, score: 0 },
                      )
                    : { scheme: null, score: 0 };

                const matchedScheme = bestMatch.scheme;
                const tone = strengthTone(bestMatch.score);

                return (
                  <tr key={draw.issue} className={`border-b align-middle ${tone.row}`}>
                    <td className="px-4 py-4 font-medium text-slate-900">{draw.issue}</td>
                    <td className="px-4 py-4 text-slate-600">{draw.draw_date}</td>
                    <td className="px-4 py-4">
                      <div className={`overflow-x-auto rounded-2xl border px-3 py-2 ${tone.cell}`}>
                        <div className="flex min-w-max items-center gap-2">
                          {draw.front_numbers.map((n) => (
                            <LottoBall key={`front-${draw.issue}-${n}`} number={n} tone="front" size="sm" />
                          ))}
                          <span className="px-1 text-slate-500">+</span>
                          {draw.back_numbers.map((n) => (
                            <LottoBall key={`back-${draw.issue}-${n}`} number={n} tone="back" size="sm" />
                          ))}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-4">
                      <div className="grid gap-2 text-xs text-slate-600">
                        <div className="flex flex-wrap gap-2">
                          <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1">
                            {`\u548c\u503c ${frontSum(draw.front_numbers)}`}
                          </span>
                          <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1">
                            {`\u8de8\u5ea6 ${frontSpan(draw.front_numbers)}`}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1">
                            {`\u5947\u5076 ${oddEvenRatio(draw.front_numbers)}`}
                          </span>
                          <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1">
                            {`\u4e09\u533a ${zonePattern(draw.front_numbers)}`}
                          </span>
                        </div>
                        {matchedScheme && bestMatch.score > 0 ? (
                          <div className="flex flex-wrap gap-2">
                            <span className={`rounded-full border px-2.5 py-1 ${tone.badge}`}>
                              {`${tone.label} ${matchedScheme.label}`}
                            </span>
                            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-500">
                              {`${bestMatch.score} / 3 \u9879`}
                            </span>
                          </div>
                        ) : null}
                      </div>
                    </td>
                    <td className="px-4 py-4 text-slate-600">{draw.pool_balance_afterdraw ?? "--"}</td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-sm text-slate-500">
                  {"\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u4e0b\u6682\u65e0\u547d\u4e2d\u7684\u5f00\u5956\u8bb0\u5f55\u3002"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="text-slate-600">{`\u5171 ${filteredRows.length} \u6761\u7b5b\u9009\u7ed3\u679c`}</p>
        <div className="flex gap-2">
          <button
            onClick={() => setPage((prev) => Math.max(1, prev - 1))}
            disabled={currentPage === 1}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {"\u4e0a\u4e00\u9875"}
          </button>
          <button
            onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
            disabled={currentPage === totalPages}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {"\u4e0b\u4e00\u9875"}
          </button>
        </div>
      </div>
    </section>
  );
}
