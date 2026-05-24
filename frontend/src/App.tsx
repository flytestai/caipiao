import { Component, type ErrorInfo, type ReactNode } from "react";
import { HomePage } from "./pages/HomePage";

interface AppErrorBoundaryState {
  hasError: boolean;
  message: string | null;
}

class AppErrorBoundary extends Component<{ children: ReactNode }, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
    message: null,
  };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return {
      hasError: true,
      message: error.message || "未知前端错误",
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("App render failed", error, info);
  }

  handleClearCacheAndReload = () => {
    try {
      const keysToRemove = Object.keys(window.localStorage).filter((key) => key.startsWith("dlt-"));
      keysToRemove.forEach((key) => window.localStorage.removeItem(key));
    } finally {
      window.location.reload();
    }
  };

  render() {
    if (this.state.hasError) {
      return (
        <main className="min-h-screen bg-slate-950 px-4 py-10 text-slate-100">
          <div className="mx-auto max-w-2xl rounded-3xl border border-rose-900/50 bg-slate-900 p-6 shadow-2xl">
            <p className="text-sm font-medium text-rose-300">页面渲染失败</p>
            <p className="mt-3 text-sm leading-7 text-slate-300">
              当前页面在加载本地缓存或渲染结果卡片时触发了异常。先清理本地缓存并刷新，页面应可恢复。
            </p>
            <div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-xs text-slate-400">
              {this.state.message ?? "未知错误"}
            </div>
            <div className="mt-5 flex flex-wrap gap-3">
              <button
                onClick={this.handleClearCacheAndReload}
                className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-rose-500"
              >
                清理本地缓存并刷新
              </button>
              <button
                onClick={() => window.location.reload()}
                className="rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-200 transition hover:bg-slate-700"
              >
                直接刷新
              </button>
            </div>
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <AppErrorBoundary>
      <HomePage />
    </AppErrorBoundary>
  );
}
