import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { LottoBall } from "./LottoBall";

interface ManualSchemeFormProps {
  defaultIssue?: string;
  fixedIssue?: string;
  submitting?: boolean;
  onSubmit: (input: {
    targetIssue: string;
    frontNumbers: number[];
    backNumbers: number[];
    label?: string;
    note?: string;
    multiple?: number;
    isAdditional?: boolean;
  }) => Promise<void> | void;
  onCancel?: () => void;
}

type InputMode = "ball" | "text";

const FRONT_RANGE = Array.from({ length: 35 }, (_, idx) => idx + 1);
const BACK_RANGE = Array.from({ length: 12 }, (_, idx) => idx + 1);

function parseNumberList(value: string, min: number, max: number, limit: number): number[] {
  if (!value) return [];
  const tokens = value
    .replace(/[\s,，、;；|/\\\-]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  const result: number[] = [];
  for (const token of tokens) {
    const n = Number(token);
    if (!Number.isFinite(n) || !Number.isInteger(n)) continue;
    if (n < min || n > max) continue;
    if (result.includes(n)) continue;
    result.push(n);
    if (result.length >= limit) break;
  }
  return result;
}

export function ManualSchemeForm({
  defaultIssue,
  fixedIssue,
  submitting = false,
  onSubmit,
  onCancel,
}: ManualSchemeFormProps) {
  const [inputMode, setInputMode] = useState<InputMode>("text");
  const [issue, setIssue] = useState(fixedIssue ?? defaultIssue ?? "");
  const [front, setFront] = useState<number[]>([]);
  const [back, setBack] = useState<number[]>([]);
  const [frontText, setFrontText] = useState("");
  const [backText, setBackText] = useState("");
  const [combinedText, setCombinedText] = useState("");
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [multiple, setMultiple] = useState(1);
  const [isAdditional, setIsAdditional] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (fixedIssue) {
      setIssue(fixedIssue);
    } else if (defaultIssue && !issue) {
      setIssue(defaultIssue);
    }
  }, [fixedIssue, defaultIssue, issue]);

  // Live-parse the text inputs in "text" mode.
  useEffect(() => {
    if (inputMode !== "text") return;
    if (combinedText.trim()) {
      const parts = combinedText.split(/[+＋]/);
      if (parts.length >= 2) {
        setFront(parseNumberList(parts[0], 1, 35, 5));
        setBack(parseNumberList(parts.slice(1).join(" "), 1, 12, 2));
        return;
      }
      const all = parseNumberList(combinedText, 1, 35, 7);
      if (all.length >= 7) {
        const frontCandidate = all.slice(0, 5);
        const backCandidateRaw = all.slice(5, 7);
        const backCandidate = backCandidateRaw.filter((n) => n >= 1 && n <= 12);
        setFront(frontCandidate);
        setBack(backCandidate);
        return;
      }
      setFront(parseNumberList(combinedText, 1, 35, 5));
      setBack([]);
      return;
    }
    setFront(parseNumberList(frontText, 1, 35, 5));
    setBack(parseNumberList(backText, 1, 12, 2));
  }, [inputMode, frontText, backText, combinedText]);

  const frontReady = front.length === 5;
  const backReady = back.length === 2;
  const canSubmit = issue.trim().length > 0 && frontReady && backReady && !submitting;

  const summary = useMemo(() => {
    return {
      front: [...front].sort((a, b) => a - b),
      back: [...back].sort((a, b) => a - b),
    };
  }, [front, back]);

  function toggleFront(num: number) {
    setFront((current) => {
      if (current.includes(num)) {
        return current.filter((x) => x !== num);
      }
      if (current.length >= 5) {
        return current;
      }
      return [...current, num];
    });
  }

  function toggleBack(num: number) {
    setBack((current) => {
      if (current.includes(num)) {
        return current.filter((x) => x !== num);
      }
      if (current.length >= 2) {
        return current;
      }
      return [...current, num];
    });
  }

  function resetAll() {
    setFront([]);
    setBack([]);
    setFrontText("");
    setBackText("");
    setCombinedText("");
    setLabel("");
    setNote("");
    setMultiple(1);
    setIsAdditional(false);
  }

  async function handleSubmit() {
    setError("");
    if (!issue.trim()) {
      setError("请输入目标期号");
      return;
    }
    if (!frontReady) {
      setError("请输入 5 个前区号码（1-35）");
      return;
    }
    if (!backReady) {
      setError("请输入 2 个后区号码（1-12）");
      return;
    }
    try {
      await onSubmit({
        targetIssue: issue.trim(),
        frontNumbers: [...front].sort((a, b) => a - b),
        backNumbers: [...back].sort((a, b) => a - b),
        label: label.trim() || undefined,
        note: note.trim() || undefined,
        multiple,
        isAdditional,
      });
      resetAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    }
  }

  function handleQuickSubmit(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }
    if (!canSubmit) {
      return;
    }
    event.preventDefault();
    void handleSubmit();
  }

  return (
    <div className="rounded-[24px] border border-slate-200 bg-white p-4 shadow-sm">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1.5">
          <span className="text-xs text-slate-500">目标期号</span>
          <input
            value={issue}
            onChange={(event) => setIssue(event.target.value)}
            disabled={!!fixedIssue}
            placeholder="例如 26051"
            onKeyDown={handleQuickSubmit}
            className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none disabled:cursor-not-allowed disabled:bg-slate-100"
          />
        </label>
        <label className="grid gap-1.5">
          <span className="text-xs text-slate-500">备注名称（可选）</span>
          <input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="例如「姓名 - 生日号」"
            onKeyDown={handleQuickSubmit}
            className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none"
          />
        </label>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-[180px_1fr]">
        <label className="grid gap-1.5">
          <span className="text-xs text-slate-500">购买倍数</span>
          <input
            type="number"
            min={1}
            max={99}
            value={multiple}
            onChange={(event) => setMultiple(Math.max(1, Math.min(99, Number(event.target.value) || 1)))}
            onKeyDown={handleQuickSubmit}
            className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none"
          />
        </label>
        <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
          <input type="checkbox" checked={isAdditional} onChange={(event) => setIsAdditional(event.target.checked)} />
          追加投注（单注 +1 元，仅一二等奖享追加奖金）
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm font-medium text-slate-900">号码录入</p>
        <div className="inline-flex overflow-hidden rounded-xl border border-slate-200 bg-slate-50 text-xs">
          <button
            type="button"
            onClick={() => setInputMode("text")}
            className={`px-3 py-1.5 transition ${
              inputMode === "text" ? "bg-cyan-500 text-white" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            直接输入
          </button>
          <button
            type="button"
            onClick={() => setInputMode("ball")}
            className={`px-3 py-1.5 transition ${
              inputMode === "ball" ? "bg-cyan-500 text-white" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            点选号球
          </button>
        </div>
      </div>

      {inputMode === "text" ? (
        <div className="mt-3 grid gap-3">
          <label className="grid gap-1.5">
            <span className="text-xs text-slate-500">
              直接输入整组号码，前区 5 个 + 后区 2 个，支持空格、逗号、加号分隔。输入后按 Enter 可直接保存。
            </span>
            <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
              <input
                value={combinedText}
                onChange={(event) => {
                  setCombinedText(event.target.value);
                  setFrontText("");
                  setBackText("");
                }}
                placeholder="例如 01 12 22 27 30 + 03 09"
                onKeyDown={handleQuickSubmit}
                autoFocus
                className="h-12 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm tracking-wider outline-none focus:border-cyan-300"
              />
              <button
                type="button"
                disabled={!canSubmit}
                onClick={handleSubmit}
                className="h-12 rounded-xl border border-emerald-300 bg-emerald-500 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? "保存中..." : "直接保存"}
              </button>
            </div>
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1.5">
              <span className="text-xs text-slate-500">仅前区（1-35，五个号码）</span>
              <input
                value={frontText}
                onChange={(event) => {
                  setFrontText(event.target.value);
                  setCombinedText("");
                }}
                placeholder="例如 1 12 22 27 30"
                onKeyDown={handleQuickSubmit}
                className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm tracking-wider outline-none focus:border-cyan-300"
              />
            </label>
            <label className="grid gap-1.5">
              <span className="text-xs text-slate-500">仅后区（1-12，两个号码）</span>
              <input
                value={backText}
                onChange={(event) => {
                  setBackText(event.target.value);
                  setCombinedText("");
                }}
                placeholder="例如 3 9"
                onKeyDown={handleQuickSubmit}
                className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm tracking-wider outline-none focus:border-cyan-300"
              />
            </label>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
            支持粘贴整串号码；系统会自动去重、截取并排序。
          </div>
        </div>
      ) : (
        <>
          <div className="mt-3">
            <p className="text-xs text-slate-500">{`前区 1-35（已选 ${front.length}/5）`}</p>
            <div className="mt-2 grid grid-cols-7 gap-2 sm:grid-cols-10">
              {FRONT_RANGE.map((num) => {
                const active = front.includes(num);
                const disabled = !active && front.length >= 5;
                return (
                  <button
                    key={`f-${num}`}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggleFront(num)}
                    className={`flex justify-center transition ${
                      disabled ? "cursor-not-allowed opacity-35" : active ? "scale-[1.02]" : "hover:scale-[1.02]"
                    }`}
                    aria-pressed={active}
                  >
                    <LottoBall number={num} tone="front" size="sm" highlight={active} />
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-4">
            <p className="text-xs text-slate-500">{`后区 1-12（已选 ${back.length}/2）`}</p>
            <div className="mt-2 grid grid-cols-7 gap-2 sm:grid-cols-12">
              {BACK_RANGE.map((num) => {
                const active = back.includes(num);
                const disabled = !active && back.length >= 2;
                return (
                  <button
                    key={`b-${num}`}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggleBack(num)}
                    className={`flex justify-center transition ${
                      disabled ? "cursor-not-allowed opacity-35" : active ? "scale-[1.02]" : "hover:scale-[1.02]"
                    }`}
                    aria-pressed={active}
                  >
                    <LottoBall number={num} tone="back" size="sm" highlight={active} />
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}

      <label className="mt-4 grid gap-1.5">
        <span className="text-xs text-slate-500">备注（可选）</span>
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="上记投注场景 / 送礼 / 后期复盘等信息"
          onKeyDown={handleQuickSubmit}
          className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none"
        />
      </label>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {summary.front.length > 0
            ? summary.front.map((number) => (
                <LottoBall key={`summary-front-${number}`} number={number} tone="front" size="sm" />
              ))
            : <span>前区 5 个</span>}
          <span className="px-1 text-slate-400">+</span>
          {summary.back.length > 0
            ? summary.back.map((number) => (
                <LottoBall key={`summary-back-${number}`} number={number} tone="back" size="sm" />
              ))
            : <span>后区 2 个</span>}
        </div>
        <div className="flex gap-2">
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              取消
            </button>
          ) : null}
          <button
            type="button"
            disabled={!canSubmit}
            onClick={handleSubmit}
            className="rounded-xl border border-emerald-300 bg-emerald-500 px-4 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "保存中..." : "保存购买号码"}
            </button>
          </div>
      </div>

      {error ? <p className="mt-2 text-xs text-rose-600">{error}</p> : null}
    </div>
  );
}
