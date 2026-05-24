"""Run a backtest in-process so the freshly edited backtest_service is used."""
import json
import os
import sys

from app.services.backtest_service import run_backtest

recent_issues = int(sys.argv[1]) if len(sys.argv) > 1 else 100
scheme_count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
strategy_mode = sys.argv[3] if len(sys.argv) > 3 else "multi_cover"
tuning_profile_override = sys.argv[4] if len(sys.argv) > 4 else None
os.environ.setdefault("BACKTEST_RAW_DIAG_PATH", "_bt_raw_diag.json")

print(
    f"[run] recent_issues={recent_issues} scheme_count={scheme_count} "
    f"strategy_mode={strategy_mode} tuning_profile_override={tuning_profile_override}"
)
resp = run_backtest(
    recent_issues=recent_issues,
    scheme_count=scheme_count,
    strategy_mode=strategy_mode,
    ticket_mode="basic",
    ai_replay_mode="local_only",
    compare_modes=False,
    tuning_profile_override=tuning_profile_override,
)
data = resp.model_dump(mode="json")
with open("_bt_result.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, default=str)
print("[run] saved _bt_result.json")
