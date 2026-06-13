from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="同步更新全历史缓存")
    parser.add_argument("scheme_count", type=int, help="组数")
    parser.add_argument("--ticket-mode", default="basic", help="票型，默认 basic")
    parser.add_argument("--force", action="store_true", help="即使当前有效也强制执行")
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parent
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from app.services.backtest_service import rebuild_full_history_cache_now

    status = rebuild_full_history_cache_now(
        scheme_count=args.scheme_count,
        ticket_mode=args.ticket_mode,
        force=args.force,
    )
    print(json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
