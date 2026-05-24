import { useEffect, useMemo, useRef, useState } from "react";
import { displayHexagramName, displayTrigramName } from "../lib/display";
import type { DivinationResponse } from "../lib/types";
import { LottoBall } from "./LottoBall";

interface DivinationAnimatorProps {
  loading: boolean;
  result: DivinationResponse | null;
}

const steps = [
  "\u53d6\u65f6\u8d77\u6570",
  "\u4e3b\u5366\u6210\u5f62",
  "\u4e92\u5366\u63a8\u6f14",
  "\u52a8\u723b\u53d8\u5366",
  "\u53f7\u7801\u6620\u5c04",
];

function randomFront() {
  return Math.floor(Math.random() * 35) + 1;
}

function randomBack() {
  return Math.floor(Math.random() * 12) + 1;
}

export function DivinationAnimator({ loading, result }: DivinationAnimatorProps) {
  const [activeStep, setActiveStep] = useState(0);
  const [rollingFront, setRollingFront] = useState<number[]>([3, 11, 18, 24, 32]);
  const [rollingBack, setRollingBack] = useState<number[]>([5, 9]);
  const [settledFront, setSettledFront] = useState<boolean[]>([false, false, false, false, false]);
  const [settledBack, setSettledBack] = useState<boolean[]>([false, false]);
  const timersRef = useRef<number[]>([]);

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => window.clearTimeout(timer));
      timersRef.current = [];
    };
  }, []);

  useEffect(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current = [];

    if (!loading) {
      setActiveStep(result ? steps.length - 1 : 0);
      if (!result) {
        return;
      }

      setSettledFront([false, false, false, false, false]);
      setSettledBack([false, false]);

      const fronts = result.front_recommendations.map((item) => item.number);
      const backs = result.back_recommendations.map((item) => item.number);

      fronts.forEach((value, index) => {
        const timer = window.setTimeout(() => {
          setRollingFront((prev) => {
            const next = [...prev];
            next[index] = value;
            return next;
          });
          setSettledFront((prev) => {
            const next = [...prev];
            next[index] = true;
            return next;
          });
        }, 200 * (index + 1));
        timersRef.current.push(timer);
      });

      backs.forEach((value, index) => {
        const timer = window.setTimeout(() => {
          setRollingBack((prev) => {
            const next = [...prev];
            next[index] = value;
            return next;
          });
          setSettledBack((prev) => {
            const next = [...prev];
            next[index] = true;
            return next;
          });
        }, 1200 + 220 * (index + 1));
        timersRef.current.push(timer);
      });
      return;
    }

    setSettledFront([false, false, false, false, false]);
    setSettledBack([false, false]);

    const stepTimer = window.setInterval(() => {
      setActiveStep((prev) => (prev + 1) % steps.length);
    }, 450);

    const rollTimer = window.setInterval(() => {
      setRollingFront(Array.from({ length: 5 }, () => randomFront()).sort((a, b) => a - b));
      setRollingBack(Array.from({ length: 2 }, () => randomBack()).sort((a, b) => a - b));
    }, 120);

    return () => {
      window.clearInterval(stepTimer);
      window.clearInterval(rollTimer);
    };
  }, [loading, result]);

  const summary = useMemo(() => {
    if (!result) {
      return "\u7b49\u5f85\u63a8\u6f14";
    }
    return `${displayHexagramName(result.main_hexagram)} -> ${displayHexagramName(result.changed_hexagram)}`;
  }, [result]);

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-[0_8px_32px_rgba(15,23,42,0.05)] sm:p-7">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-5">
        <div>
          <p className="text-[11px] font-medium tracking-[0.24em] text-slate-500">{"DIVINATION \u00b7 \u8d77\u5366\u63a8\u6f14"}</p>
          <h2 className="mt-1.5 text-xl font-semibold tracking-tight text-slate-900">{"\u6885\u82b1\u6613\u6570\u63a8\u6f14"}</h2>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs ${
          loading
            ? "bg-amber-50 text-amber-700"
            : result
              ? "bg-emerald-50 text-emerald-700"
              : "bg-slate-100 text-slate-500"
        }`}>
          <span className={`h-1.5 w-1.5 rounded-full ${loading ? "animate-pulse bg-amber-500" : result ? "bg-emerald-500" : "bg-slate-400"}`} />
          {loading ? "\u63a8\u7b97\u4e2d" : result ? "\u63a8\u6f14\u5b8c\u6210" : "\u7b49\u5f85\u8f93\u5165"}
        </span>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2">
        {steps.map((step, index) => {
          const isActive = index === activeStep;
          const isDone = !!result && (index < activeStep || (!loading && index <= activeStep));
          return (
            <div key={step} className="flex flex-1 items-center gap-2">
              <div
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-medium transition ${
                  isActive
                    ? "bg-slate-900 text-white"
                    : isDone
                      ? "bg-slate-200 text-slate-700"
                      : "bg-slate-100 text-slate-400"
                }`}
              >
                {String(index + 1).padStart(2, "0")}
              </div>
              <span className={`hidden truncate text-xs lg:inline ${isActive ? "font-medium text-slate-900" : "text-slate-500"}`}>{step}</span>
              {index < steps.length - 1 ? <div className={`h-px flex-1 ${isDone ? "bg-slate-300" : "bg-slate-200"}`} /> : null}
            </div>
          );
        })}
      </div>

      {/* Rolling balls */}
      <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium tracking-[0.18em] text-slate-500">{"\u5f00\u5956\u7403\u843d\u4f4d"}</p>
          <span className="text-[11px] text-slate-400">{loading ? "\u6eda\u7403\u4e2d" : result ? "\u5df2\u843d\u4f4d" : "\u5f85\u8d77\u52a8"}</span>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2 sm:gap-2.5">
          {rollingFront.map((value, index) => (
            <div
              key={`rolling-front-${index}`}
              className={loading ? "animate-[pulse_0.9s_ease-in-out_infinite]" : settledFront[index] ? "ball-drop" : ""}
            >
              <LottoBall number={value} tone="front" size="md" />
            </div>
          ))}
          <span className="mx-0.5 text-xl font-light text-slate-300">+</span>
          {rollingBack.map((value, index) => (
            <div
              key={`rolling-back-${index}`}
              className={loading ? "animate-[pulse_0.9s_ease-in-out_infinite]" : settledBack[index] ? "ball-drop" : ""}
            >
              <LottoBall number={value} tone="back" size="md" />
            </div>
          ))}
        </div>
      </div>

      {/* Hexagram result */}
      <div className="mt-5">
        <div className="rounded-2xl bg-gradient-to-br from-slate-900 to-slate-700 px-5 py-5 text-white">
          <p className="text-[10px] font-medium tracking-[0.24em] text-slate-300">{"\u5366\u8c61\u6d41\u8f6c"}</p>
          <p className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">
            {result ? (
              <>
                <span>{displayHexagramName(result.main_hexagram)}</span>
                <span className="mx-2 text-slate-400">{"\u2192"}</span>
                <span>{displayHexagramName(result.changed_hexagram)}</span>
              </>
            ) : (
              <span className="text-slate-400">{summary}</span>
            )}
          </p>
        </div>

        {result ? (
          <div className="mt-3 grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-[10px] tracking-[0.18em] text-slate-400">{"\u4e0a\u5366"}</p>
              <p className="mt-1 text-base font-semibold text-slate-900">{displayTrigramName(result.main_hexagram.upper_trigram)}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-[10px] tracking-[0.18em] text-slate-400">{"\u4e0b\u5366"}</p>
              <p className="mt-1 text-base font-semibold text-slate-900">{displayTrigramName(result.main_hexagram.lower_trigram)}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
              <p className="text-[10px] tracking-[0.18em] text-slate-400">{"\u52a8\u723b"}</p>
              <p className="mt-1 text-base font-semibold text-slate-900 tabular-nums">{`\u7b2c ${result.moving_line} \u723b`}</p>
            </div>
          </div>
        ) : (
          <div className="mt-3 rounded-xl border border-dashed border-slate-200 bg-slate-50/40 px-4 py-6 text-center text-xs text-slate-500">
            {"\u5f00\u59cb\u63a8\u6f14\u540e\uff0c\u8fd9\u91cc\u4f1a\u663e\u793a\u4e3b\u5366\u3001\u53d8\u5366\u4e0e\u52a8\u723b\u7ed3\u679c\u3002"}
          </div>
        )}
      </div>
    </section>
  );
}
