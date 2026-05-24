import type { ReactNode } from "react";
import { useState } from "react";
import { Bot, CheckSquare, KeyRound, Link2, LoaderCircle, RefreshCw, Square, WandSparkles } from "lucide-react";
import { fetchAIModels } from "../lib/api";
import type { AIConfig, AIModelItem } from "../lib/types";

interface AIConfigPanelProps {
  value: AIConfig;
  onChange: (next: AIConfig) => void;
  footer?: ReactNode;
}

function updateField(value: AIConfig, patch: Partial<AIConfig>): AIConfig {
  return { ...value, ...patch };
}

export function AIConfigPanel({ value, onChange, footer }: AIConfigPanelProps) {
  const [availableModels, setAvailableModels] = useState<AIModelItem[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelError, setModelError] = useState("");

  async function handleFetchModels() {
    if (!value.baseUrl.trim() || !value.apiKey.trim()) {
      setModelError("\u8bf7\u5148\u586b\u5199\u63a5\u53e3\u5730\u5740\u548c API Key\u3002");
      return;
    }

    setLoadingModels(true);
    setModelError("");
    try {
      const data = await fetchAIModels(value.baseUrl.trim(), value.apiKey.trim());
      setAvailableModels(data.models);
      const nextSelected =
        value.selectedModels.length > 0
          ? value.selectedModels.filter((item) => data.models.some((model) => model.id === item))
          : [];
      onChange(
        updateField(value, {
          selectedModels: nextSelected,
          model: nextSelected[0] ?? value.model,
        }),
      );
    } catch (error) {
      setModelError(error instanceof Error ? error.message : "\u83b7\u53d6\u6a21\u578b\u5217\u8868\u5931\u8d25\u3002");
    } finally {
      setLoadingModels(false);
    }
  }

  function toggleModel(modelId: string) {
    const exists = value.selectedModels.includes(modelId);
    const selectedModels = exists
      ? value.selectedModels.filter((item) => item !== modelId)
      : [...value.selectedModels, modelId];
    onChange(
      updateField(value, {
        selectedModels,
        model: selectedModels[0] ?? "",
      }),
    );
  }

  return (
    <section className="rounded-[30px] border border-slate-200 bg-white p-5 shadow-[0_16px_45px_rgba(15,23,42,0.06)]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs tracking-[0.3em] text-cyan-700/70">{"\u0041\u0049 \u63a5\u5165\u7f51\u5173"}</p>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">{"\u0041\u0049\u63a5\u53e3\u914d\u7f6e"}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            {
              "\u5728\u8fd9\u91cc\u7ef4\u62a4\u5916\u90e8\u6a21\u578b\u7f51\u5173\u3001\u4e3b\u6a21\u578b\u4e0e\u63d0\u793a\u8bcd\u3002\u53ea\u6709\u52fe\u9009\u201c\u542f\u7528\u5916\u90e8AI\u201d\u540e\uff0c\u63a8\u6f14\u548c\u56de\u6d4b\u624d\u4f1a\u8c03\u7528\u5916\u90e8\u6a21\u578b\uff1b\u672a\u52fe\u9009\u65f6\u7ee7\u7eed\u4f7f\u7528\u672c\u5730\u5206\u6790\u3002"
            }
          </p>
        </div>
        <label className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          <input
            type="checkbox"
            checked={value.enabled}
            onChange={(event) => onChange(updateField(value, { enabled: event.target.checked }))}
            className="h-4 w-4 rounded border-slate-300 bg-white"
          />
          {"\u542f\u7528\u5916\u90e8\u0041\u0049"}
        </label>
      </div>

      <div className="mt-5 grid gap-4">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs text-slate-500">{"\u5f53\u524d\u72b6\u6001"}</p>
            <p className="mt-2 text-sm font-medium text-slate-900">
              {value.enabled ? "\u5df2\u542f\u7528" : "\u672a\u542f\u7528"}
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs text-slate-500">{"\u5df2\u9009\u6a21\u578b"}</p>
            <p className="mt-2 text-sm font-medium text-slate-900">{value.selectedModels.length || 0}</p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs text-slate-500">{"\u4e3b\u5206\u6790\u6a21\u578b"}</p>
            <p className="mt-2 text-sm font-medium text-slate-900">{value.model || "\u672c\u5730\u7ec4\u5408\u5206\u6790"}</p>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="grid gap-2 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <span className="text-xs text-slate-500">{"\u63a5\u53e3\u5730\u5740"}</span>
            <div className="relative">
              <Link2 className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input
                value={value.baseUrl}
                onChange={(event) => onChange(updateField(value, { baseUrl: event.target.value }))}
                placeholder="https://api.openai.com/v1"
                className="h-11 w-full rounded-xl border border-slate-200 bg-white pl-11 pr-4 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-cyan-300"
              />
            </div>
          </label>
          <label className="grid gap-2 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <span className="text-xs text-slate-500">{"\u6a21\u578b\u540d\u79f0"}</span>
            <div className="relative">
              <Bot className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input
                value={value.model}
                onChange={(event) => onChange(updateField(value, { model: event.target.value }))}
                placeholder="gpt-4.1 / deepseek-chat / qwen-plus"
                className="h-11 w-full rounded-xl border border-slate-200 bg-white pl-11 pr-4 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-cyan-300"
              />
            </div>
          </label>
        </div>

        <label className="grid gap-2 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
          <span className="text-xs text-slate-500">{"\u0041\u0050\u0049\u0020\u004b\u0065\u0079"}</span>
          <div className="relative">
            <KeyRound className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              type="password"
              value={value.apiKey}
              onChange={(event) => onChange(updateField(value, { apiKey: event.target.value }))}
              placeholder="sk-..."
              className="h-11 w-full rounded-xl border border-slate-200 bg-white pl-11 pr-4 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-cyan-300"
            />
          </div>
        </label>

        <label className="grid gap-2 rounded-[24px] border border-slate-200 bg-slate-50 p-4">
          <span className="text-xs text-slate-500">{"\u7cfb\u7edf\u63d0\u793a\u8bcd"}</span>
          <div className="relative">
            <WandSparkles className="pointer-events-none absolute left-4 top-4 h-4 w-4 text-slate-500" />
            <textarea
              value={value.systemPrompt}
              onChange={(event) => onChange(updateField(value, { systemPrompt: event.target.value }))}
              placeholder={"\u4f8b\u5982\uff1a\u8bf7\u57fa\u4e8e\u5168\u5386\u53f2\u6570\u636e\u3001\u6885\u82b1\u6613\u6570\u548c\u7edf\u8ba1\u7279\u5f81\u7ed9\u51fa\u7b80\u6d01\u7ed3\u8bba\u3002"}
              className="min-h-24 w-full rounded-2xl border border-slate-200 bg-white py-3 pl-11 pr-4 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-cyan-300"
            />
          </div>
        </label>

        <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-slate-900">{"\u53ef\u7528\u5927\u6a21\u578b\u5217\u8868"}</p>
              <p className="mt-1 text-xs leading-6 text-slate-500">
                {"\u70b9\u51fb\u83b7\u53d6\u6a21\u578b\u5217\u8868\u540e\uff0c\u53ef\u52fe\u9009\u8981\u914d\u7f6e\u7684\u5927\u6a21\u578b\u3002\u9996\u4e2a\u52fe\u9009\u6a21\u578b\u4f1a\u4f5c\u4e3a\u5f53\u524d\u4e3b\u5206\u6790\u6a21\u578b\u3002"}
              </p>
            </div>
            <button
              onClick={handleFetchModels}
              disabled={loadingModels}
              className="inline-flex h-10 items-center gap-2 rounded-2xl border border-cyan-200 bg-cyan-50 px-4 text-sm text-cyan-700 transition hover:bg-cyan-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loadingModels ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              <span>{loadingModels ? "\u83b7\u53d6\u4e2d..." : "\u83b7\u53d6\u6a21\u578b\u5217\u8868"}</span>
            </button>
          </div>

          {modelError ? <p className="mt-3 text-xs text-rose-600">{modelError}</p> : null}

          <div className="mt-4 grid gap-2">
            {availableModels.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-5 text-sm text-slate-500">
                {"\u6682\u672a\u83b7\u53d6\u5230\u6a21\u578b\u5217\u8868\u3002"}
              </div>
            ) : (
              availableModels.map((model) => {
                const checked = value.selectedModels.includes(model.id);
                return (
                  <button
                    key={model.id}
                    onClick={() => toggleModel(model.id)}
                    className={`flex items-center justify-between rounded-2xl border px-4 py-3 text-left transition ${
                      checked
                        ? "border-cyan-300 bg-cyan-50 text-cyan-700"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      {checked ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                      <div>
                        <p className="text-sm font-medium">{model.id}</p>
                        <p className="text-xs text-slate-500">{model.owned_by || "\u672a\u77e5\u63d0\u4f9b\u65b9"}</p>
                      </div>
                    </div>
                    {value.model === model.id ? (
                      <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs text-amber-700">
                        {"\u4e3b\u6a21\u578b"}
                      </span>
                    ) : null}
                  </button>
                );
              })
            )}
          </div>
        </div>

        {footer ? <div className="pt-2">{footer}</div> : null}
      </div>
    </section>
  );
}
