import { useEffect, useMemo, useState } from "react";
import { LottoBall } from "./LottoBall";

interface ManualDrawResultFormProps {
  issue: string;
  initialFrontNumbers?: number[];
  initialBackNumbers?: number[];
  initialDrawDate?: string | null;
  initialHighPool?: boolean;
  submitting?: boolean;
  onSubmit: (input: {
    issue: string;
    frontNumbers: number[];
    backNumbers: number[];
    drawDate?: string;
    highPool: boolean;
  }) => Promise<void> | void;
  onCancel?: () => void;
}

const FRONT_RANGE = Array.from({ length: 35 }, (_, idx) => idx + 1);
const BACK_RANGE = Array.from({ length: 12 }, (_, idx) => idx + 1);

export function ManualDrawResultForm({
  issue,
  initialFrontNumbers = [],
  initialBackNumbers = [],
  initialDrawDate,
  initialHighPool = false,
  submitting = false,
  onSubmit,
  onCancel,
}: ManualDrawResultFormProps) {
  const [front, setFront] = useState<number[]>(initialFrontNumbers);
  const [back, setBack] = useState<number[]>(initialBackNumbers);
  const [drawDate, setDrawDate] = useState(initialDrawDate?.slice(0, 10) ?? "");
  const [highPool, setHighPool] = useState(initialHighPool);
  const [error, setError] = useState("");

  useEffect(() => {
    setFront(initialFrontNumbers);
    setBack(initialBackNumbers);
    setDrawDate(initialDrawDate?.slice(0, 10) ?? "");
    setHighPool(initialHighPool);
  }, [initialBackNumbers, initialDrawDate, initialFrontNumbers, initialHighPool]);

  const summary = useMemo(
    () => ({
      front: [...front].sort((a, b) => a - b),
      back: [...back].sort((a, b) => a - b),
    }),
    [front, back],
  );

  function toggleFront(num: number) {
    setFront((current) => {
      if (current.includes(num)) return current.filter((item) => item !== num);
      if (current.length >= 5) return current;
      return [...current, num];
    });
  }

  function toggleBack(num: number) {
    setBack((current) => {
      if (current.includes(num)) return current.filter((item) => item !== num);
      if (current.length >= 2) return current;
      return [...current, num];
    });
  }

  async function handleSubmit() {
    setError("");
    if (front.length !== 5) {
      setError("请选择 5 个前区开奖号码");
      return;
    }
    if (back.length !== 2) {
      setError("请选择 2 个后区开奖号码");
      return;
    }
    try {
      await onSubmit({
        issue,
        frontNumbers: [...front].sort((a, b) => a - b),
        backNumbers: [...back].sort((a, b) => a - b),
        drawDate: drawDate || undefined,
        highPool,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存开奖结果失败");
    }
  }

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50/70 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-slate-900">{`第 ${issue} 期手动录入开奖号`}</p>
          <p className="mt-1 text-xs text-slate-600">未同步到官方结果前，可先手动兑奖。手动结果会优先参与本期所有已保存方案结算。</p>
        </div>
        <span className="rounded-full border border-amber-200 bg-white px-3 py-1 text-xs text-amber-700">手动结果</span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
        <label className="grid gap-1.5">
          <span className="text-xs text-slate-500">开奖日期（可选）</span>
          <input
            type="date"
            value={drawDate}
            onChange={(event) => setDrawDate(event.target.value)}
            className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm outline-none"
          />
        </label>
        <label className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700">
          <input type="checkbox" checked={highPool} onChange={(event) => setHighPool(event.target.checked)} />
          奖池不低于 8 亿
        </label>
      </div>

      <div className="mt-4">
        <p className="text-xs text-slate-500">{`前区开奖号码 1-35（已选 ${front.length}/5）`}</p>
        <div className="mt-2 grid grid-cols-7 gap-2 sm:grid-cols-10">
          {FRONT_RANGE.map((num) => {
            const active = front.includes(num);
            const disabled = !active && front.length >= 5;
            return (
              <button
                key={`draw-front-${num}`}
                type="button"
                disabled={disabled}
                onClick={() => toggleFront(num)}
                className={`flex justify-center transition ${
                  disabled ? "cursor-not-allowed opacity-35" : active ? "scale-[1.02]" : "hover:scale-[1.02]"
                }`}
              >
                <LottoBall number={num} tone="front" size="sm" highlight={active} />
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-4">
        <p className="text-xs text-slate-500">{`后区开奖号码 1-12（已选 ${back.length}/2）`}</p>
        <div className="mt-2 grid grid-cols-7 gap-2 sm:grid-cols-12">
          {BACK_RANGE.map((num) => {
            const active = back.includes(num);
            const disabled = !active && back.length >= 2;
            return (
              <button
                key={`draw-back-${num}`}
                type="button"
                disabled={disabled}
                onClick={() => toggleBack(num)}
                className={`flex justify-center transition ${
                  disabled ? "cursor-not-allowed opacity-35" : active ? "scale-[1.02]" : "hover:scale-[1.02]"
                }`}
              >
                <LottoBall number={num} tone="back" size="sm" highlight={active} />
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          {summary.front.length > 0 ? summary.front.map((number) => (
            <LottoBall key={`draw-summary-front-${number}`} number={number} tone="front" size="sm" />
          )) : <span>前区 5 个</span>}
          <span className="px-1 text-slate-400">+</span>
          {summary.back.length > 0 ? summary.back.map((number) => (
            <LottoBall key={`draw-summary-back-${number}`} number={number} tone="back" size="sm" />
          )) : <span>后区 2 个</span>}
        </div>
        <div className="flex gap-2">
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600"
            >
              取消
            </button>
          ) : null}
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="rounded-xl border border-amber-300 bg-amber-500 px-4 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "保存中..." : "保存开奖结果"}
          </button>
        </div>
      </div>

      {error ? <p className="mt-2 text-xs text-rose-600">{error}</p> : null}
    </div>
  );
}
