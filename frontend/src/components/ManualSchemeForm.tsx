import { useEffect, useMemo, useState } from "react";
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

const FRONT_RANGE = Array.from({ length: 35 }, (_, idx) => idx + 1);
const BACK_RANGE = Array.from({ length: 12 }, (_, idx) => idx + 1);

export function ManualSchemeForm({
  defaultIssue,
  fixedIssue,
  submitting = false,
  onSubmit,
  onCancel,
}: ManualSchemeFormProps) {
  const [issue, setIssue] = useState(fixedIssue ?? defaultIssue ?? "");
  const [front, setFront] = useState<number[]>([]);
  const [back, setBack] = useState<number[]>([]);
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

  async function handleSubmit() {
    setError("");
    if (!issue.trim()) {
      setError("\u8bf7\u8f93\u5165\u76ee\u6807\u671f\u53f7");
      return;
    }
    if (!frontReady) {
      setError("\u8bf7\u9009\u6ee1 5 \u4e2a\u524d\u533a\u53f7\u7801");
      return;
    }
    if (!backReady) {
      setError("\u8bf7\u9009\u6ee1 2 \u4e2a\u540e\u533a\u53f7\u7801");
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
      setFront([]);
      setBack([]);
      setLabel("");
      setNote("");
      setMultiple(1);
      setIsAdditional(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "\u4fdd\u5b58\u5931\u8d25");
    }
  }

  return (
    <div className="rounded-2xl border border-cyan-200 bg-white p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1.5">
          <span className="text-xs text-slate-500">{"\u76ee\u6807\u671f\u53f7"}</span>
          <input
            value={issue}
            onChange={(event) => setIssue(event.target.value)}
            disabled={!!fixedIssue}
            placeholder={"\u4f8b\u5982 26051"}
            className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none disabled:cursor-not-allowed disabled:bg-slate-100"
          />
        </label>
        <label className="grid gap-1.5">
          <span className="text-xs text-slate-500">{"\u5907\u6ce8\u540d\u79f0\uff08\u53ef\u9009\uff09"}</span>
          <input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder={"\u4f8b\u5982\u300c\u59d3\u540d - \u751f\u65e5\u53f7\u300d"}
            className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none"
          />
        </label>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1.5">
          <span className="text-xs text-slate-500">购买倍数</span>
          <input
            type="number"
            min={1}
            max={99}
            value={multiple}
            onChange={(event) => setMultiple(Math.max(1, Math.min(99, Number(event.target.value) || 1)))}
            className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none"
          />
        </label>
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          单式基本投注 2 元，追加投注 3 元；系统会按倍数自动计算票面金额，派奖期内按是否满 18 元判断是否参与派奖。
        </div>
      </div>

      <label className="mt-3 flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
        <input type="checkbox" checked={isAdditional} onChange={(event) => setIsAdditional(event.target.checked)} />
        追加投注
      </label>

      <div className="mt-4">
        <p className="text-xs text-slate-500">
          {`\u524d\u533a 1-35\uff08\u5df2\u9009 ${front.length}/5\uff09`}
        </p>
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
        <p className="text-xs text-slate-500">
          {`\u540e\u533a 1-12\uff08\u5df2\u9009 ${back.length}/2\uff09`}
        </p>
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

      <label className="mt-4 grid gap-1.5">
        <span className="text-xs text-slate-500">{"\u5907\u6ce8\uff08\u53ef\u9009\uff09"}</span>
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder={"\u4e0a\u8bb0\u6295\u6ce8\u573a\u666f / \u9001\u793c / \u540e\u671f\u590d\u76d8\u7b49\u4fe1\u606f"}
          className="h-10 rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none"
        />
      </label>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {summary.front.length > 0 ? summary.front.map((number) => (
            <LottoBall key={`summary-front-${number}`} number={number} tone="front" size="sm" />
          )) : <span>{"\u524d\u533a 5 \u4e2a"}</span>}
          <span className="px-1 text-slate-400">+</span>
          {summary.back.length > 0 ? summary.back.map((number) => (
            <LottoBall key={`summary-back-${number}`} number={number} tone="back" size="sm" />
          )) : <span>{"\u540e\u533a 2 \u4e2a"}</span>}
        </div>
        <div className="flex gap-2">
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
            >
              {"\u53d6\u6d88"}
            </button>
          ) : null}
          <button
            type="button"
            disabled={!canSubmit}
            onClick={handleSubmit}
            className="rounded-xl border border-emerald-300 bg-emerald-500 px-4 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "\u4fdd\u5b58\u4e2d..." : "\u4fdd\u5b58\u8d2d\u4e70\u53f7\u7801"}
          </button>
        </div>
      </div>

      {error ? <p className="mt-2 text-xs text-rose-600">{error}</p> : null}
    </div>
  );
}
