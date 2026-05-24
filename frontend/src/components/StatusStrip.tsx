import type { SyncStatus } from "../lib/types";

interface StatusStripProps {
  status: SyncStatus | null;
  syncing: boolean;
  onSync: () => void;
}

export function StatusStrip({ status, syncing, onSync }: StatusStripProps) {
  const formatDateTime = (value?: string | null) =>
    value
      ? new Date(value).toLocaleString("zh-CN", {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        })
      : "--";

  return (
    <section className="rounded-[28px] border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,0.06)]">
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs tracking-[0.3em] text-cyan-700/70">{"\u6570\u636e\u8fd0\u884c"}</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-900">{"\u5f00\u5956\u6e90\u4e0e\u540c\u6b65\u72b6\u6001"}</h2>
            <p className="mt-2 text-sm text-slate-600">{"\u67e5\u770b\u5f53\u524d\u5168\u91cf\u5386\u53f2\u8986\u76d6\u3001\u4e0b\u4e00\u671f\u76ee\u6807\u4e0e\u6700\u540e\u540c\u6b65\u65f6\u95f4\u3002"}</p>
          </div>

          <button
            onClick={onSync}
            disabled={syncing}
            className="h-12 rounded-2xl border border-cyan-200 bg-cyan-50 px-5 text-sm font-medium text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {syncing ? "\u540c\u6b65\u4e2d..." : "\u7acb\u5373\u540c\u6b65\u5f00\u5956\u6570\u636e"}
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <div className="rounded-[24px] border border-cyan-200 bg-cyan-50 px-4 py-3">
            <p className="text-xs tracking-[0.24em] text-slate-500">{"\u4e0b\u4e00\u671f\u76ee\u6807"}</p>
            <p className="mt-1.5 text-2xl font-semibold text-cyan-700">{status?.next_issue ?? "--"}</p>
            <p className="mt-1.5 text-sm text-slate-600">
              {formatDateTime(status?.next_draw_datetime)}
            </p>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-xs tracking-[0.24em] text-slate-500">{"\u6570\u636e\u6e90"}</p>
            <p className="mt-1.5 text-sm font-medium text-slate-900">{status?.source ?? "\u52a0\u8f7d\u4e2d..."}</p>
            <p className="mt-1.5 text-xs text-slate-500">{"\u6700\u65b0\u671f\u53f7"}</p>
            <p className="mt-1 text-sm text-slate-700">{status?.latest_issue ?? "--"}</p>
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-xs tracking-[0.24em] text-slate-500">{"\u6570\u636e\u5e93\u8986\u76d6"}</p>
            <p className="mt-1.5 text-2xl font-semibold text-slate-900">{status?.total_draws ?? "--"}</p>
            <p className="mt-1.5 text-sm text-slate-600">{"\u5b98\u65b9\u5f00\u5956\u6570\u636e\u5df2\u5165\u5e93"}</p>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-xs tracking-[0.24em] text-slate-500">{"\u6700\u540e\u540c\u6b65"}</p>
            <p className="mt-1.5 text-sm font-medium text-slate-900">
              {status?.last_synced_at ? new Date(status.last_synced_at).toLocaleString("zh-CN") : "--"}
            </p>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-xs tracking-[0.24em] text-slate-500">{"\u540c\u6b65\u72b6\u6001"}</p>
            <p className="mt-1.5 text-sm font-medium text-slate-900">{syncing ? "\u6b63\u5728\u62c9\u53d6\u6700\u65b0\u5f00\u5956\u6570\u636e" : "\u5f53\u524d\u6570\u636e\u5df2\u5c31\u7eea"}</p>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p className="text-xs tracking-[0.24em] text-slate-500">{"\u5f53\u524d\u7528\u9014"}</p>
            <p className="mt-1.5 text-sm font-medium text-slate-900">{"\u4e3a\u4e0b\u4e00\u671f\u4e00\u7b49\u5956\u76ee\u6807\u63a8\u6f14\u63d0\u4f9b\u6837\u672c"}</p>
          </div>
        </div>
      </div>
    </section>
  );
}
