import unittest
import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.db import ensure_database
import app.services.backtest_service as backtest_service
from app.services.backtest_service import (
    BACKTEST_HISTORY_RECENT_WINDOW,
    _FullHistoryCacheJobState,
    _build_history_context_cache,
    _incremental_full_history_cache_window,
    _window_model_schemes,
)
from app.services.meihua import build_history_feature_context
from app.services.repository import build_backtest_stats
from app.services.repository import get_all_history_asc


class BacktestHistoryCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_database()
        cls.history_asc = get_all_history_asc()

    def test_history_context_cache_matches_feature_builder(self) -> None:
        targets = [self.history_asc[160], self.history_asc[420]]
        cache = _build_history_context_cache(self.history_asc, targets)

        for target in targets:
            expected_history_desc = [draw for draw in self.history_asc if draw.issue < target.issue][::-1]
            expected_context = build_history_feature_context(expected_history_desc)
            recent_history_desc, actual_context = cache[target.issue]

            self.assertEqual(actual_context, expected_context)
            self.assertEqual(recent_history_desc, expected_history_desc[:BACKTEST_HISTORY_RECENT_WINDOW])

    def test_window_model_schemes_match_with_limited_history_cache(self) -> None:
        target = self.history_asc[420]
        full_history_desc = [draw for draw in self.history_asc if draw.issue < target.issue][::-1]
        history_context = build_history_feature_context(full_history_desc)

        full_schemes = _window_model_schemes(full_history_desc, 5)
        limited_schemes = _window_model_schemes(
            full_history_desc[:BACKTEST_HISTORY_RECENT_WINDOW],
            5,
            history_context=history_context,
        )

        self.assertEqual(limited_schemes, full_schemes)

class FullHistoryCacheIncrementalTests(unittest.TestCase):
    def _make_history(self, total_draws: int) -> list[SimpleNamespace]:
        start = date(2026, 1, 1)
        history: list[SimpleNamespace] = []
        for index in range(total_draws):
            history.append(
                SimpleNamespace(
                    issue=f"{26000 + index + 1}",
                    draw_date=start + timedelta(days=index),
                    front_numbers=[1, 2, 3, 4, 5],
                    back_numbers=[1, 2],
                )
            )
        return history

    def _issue_rows_from_history(self, history: list[SimpleNamespace], issue_indexes: list[int]) -> list[dict]:
        rows: list[dict] = []
        for history_index in issue_indexes:
            draw = history[history_index]
            rows.append(
                {
                    "issue": str(draw.issue),
                    "draw_date": draw.draw_date,
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "won_count": 0,
                    "total_prize_amount": 0.0,
                    "prize_level_hits": {},
                    "prize_level_amounts": {},
                    "cost": 6.0,
                }
            )
        return rows

    def _write_json(self, root: Path, file_name: str, payload: dict) -> None:
        path = root / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")

    def test_status_allows_algorithm_version_mismatch_when_cache_is_complete(self) -> None:
        history = self._make_history(32)
        latest_issue = str(history[-1].issue)
        expected_issue_count = backtest_service._expected_full_history_cache_issue_count(history)
        specs = {
            "default_multi": {
                "candidate_name": "multi_cover:balanced+balanced_combo",
                "strategy_mode": "multi_cover",
                "tuning_profile_override": "balanced+balanced_combo",
                "file_name": "cache_default.json",
            }
        }
        issue_rows = self._issue_rows_from_history(history, [30, 31])

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_json(
                root,
                "cache_default.json",
                {
                    "requested_issues": len(history),
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "total_issues": expected_issue_count,
                    "issues": issue_rows,
                    "full_history_cache": {
                        "algorithm_version": "full-history-cache-v2026-06-01-01",
                        "generated_at": "2026-06-01T12:00:00+08:00",
                        "latest_issue": latest_issue,
                        "scheme_count": 3,
                        "ticket_mode": "basic",
                        "profile": "default_multi",
                    },
                },
            )
            self._write_json(
                root,
                "full_history_cache_3_basic.manifest.json",
                {
                    "algorithm_version": "full-history-cache-v2026-06-01-01",
                    "generated_at": "2026-06-01T12:00:00+08:00",
                    "source_snapshot_at": "2026-06-01T12:00:00+08:00",
                    "latest_issue": latest_issue,
                    "total_draws": len(history),
                    "expected_issue_count": expected_issue_count,
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "profiles": {
                        "default_multi": {
                            "file_name": "cache_default.json",
                        }
                    },
                },
            )

            with (
                patch.object(
                    backtest_service,
                    "_smart_balance_report_file_path",
                    side_effect=lambda file_name: str(root / file_name),
                ),
                patch.object(backtest_service, "get_all_history_asc", return_value=history),
                patch.object(backtest_service, "get_meta", return_value=None),
                patch.object(backtest_service, "_full_history_cache_profile_specs", return_value=specs),
            ):
                status = backtest_service.get_full_history_cache_status(3, "basic")

            self.assertTrue(status.valid)
            self.assertEqual(status.stale_reasons, [])
            self.assertEqual(status.profiles[0].latest_issue, latest_issue)

    def test_incremental_window_detects_missing_tail_issues(self) -> None:
        history = self._make_history(33)
        expected_issue_count = backtest_service._expected_full_history_cache_issue_count(history)
        report = {
            "issues": self._issue_rows_from_history(history, [30, 31]),
        }

        cached_issues, missing_recent_issues = _incremental_full_history_cache_window(
            report=report,
            history_asc=history,
            latest_issue=str(history[-1].issue),
            expected_issue_count=expected_issue_count,
        )

        self.assertEqual(len(cached_issues), 2)
        self.assertEqual(missing_recent_issues, 1)

    def test_rebuild_job_only_appends_missing_tail(self) -> None:
        history = self._make_history(33)
        latest_issue = str(history[-1].issue)
        expected_issue_count = backtest_service._expected_full_history_cache_issue_count(history)
        specs = {
            "default_multi": {
                "candidate_name": "multi_cover:balanced+balanced_combo",
                "strategy_mode": "multi_cover",
                "tuning_profile_override": "balanced+balanced_combo",
                "file_name": "cache_default.json",
            }
        }
        existing_issue_rows = self._issue_rows_from_history(history, [30, 31])
        appended_issue_rows = self._issue_rows_from_history(history, [32])
        run_backtest_calls: list[int] = []

        def fake_run_backtest(*, recent_issues: int, **_kwargs):
            run_backtest_calls.append(recent_issues)
            response = build_backtest_stats(appended_issue_rows)  # type: ignore[arg-type]
            response.requested_issues = recent_issues
            response.recent_issues = recent_issues
            response.scheme_count = 3
            response.strategy_mode = "multi_cover"  # type: ignore[assignment]
            response.ticket_mode = "basic"  # type: ignore[assignment]
            response.ai_replay_mode = "local_only"  # type: ignore[assignment]
            response.benchmarks = []
            response.window_summaries = []
            response.mode_comparison = []
            response.issue_comparison = []
            response.threshold_scan = []
            return response

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_json(
                root,
                "cache_default.json",
                {
                    "requested_issues": 32,
                    "scheme_count": 3,
                    "strategy_mode": "multi_cover",
                    "ticket_mode": "basic",
                    "total_issues": 2,
                    "total_generated_schemes": 6,
                    "won_schemes": 0,
                    "total_prize_amount": 0.0,
                    "total_cost": 12.0,
                    "net_profit": -12.0,
                    "overall_win_rate": 0.0,
                    "issue_hit_rate": 0.0,
                    "prize_rates": [],
                    "prize_level_breakdown": [],
                    "issues": existing_issue_rows,
                    "coverage_metrics": {},
                    "window_summaries": [],
                    "benchmarks": [],
                    "mode_comparison": [],
                    "issue_comparison": [],
                    "threshold_scan": [],
                    "full_history_cache": {
                        "algorithm_version": "full-history-cache-v2026-06-01-01",
                        "generated_at": "2026-06-01T12:00:00+08:00",
                        "source_snapshot_at": "2026-06-01T12:00:00+08:00",
                        "latest_issue": str(history[31].issue),
                        "total_draws": 32,
                        "expected_issue_count": 2,
                        "scheme_count": 3,
                        "ticket_mode": "basic",
                        "profile": "default_multi",
                    },
                },
            )
            self._write_json(
                root,
                "full_history_cache_3_basic.manifest.json",
                {
                    "algorithm_version": "full-history-cache-v2026-06-01-01",
                    "generated_at": "2026-06-01T12:00:00+08:00",
                    "source_snapshot_at": "2026-06-01T12:00:00+08:00",
                    "latest_issue": str(history[31].issue),
                    "total_draws": 32,
                    "expected_issue_count": 2,
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "profiles": {
                        "default_multi": {
                            "file_name": "cache_default.json",
                        }
                    },
                },
            )

            job_id = "job-incremental"
            old_jobs = dict(backtest_service._full_history_cache_jobs)
            try:
                backtest_service._full_history_cache_jobs.clear()
                backtest_service._full_history_cache_jobs[job_id] = _FullHistoryCacheJobState(
                    job_id=job_id,
                    scheme_count=3,
                    ticket_mode="basic",
                )

                with (
                    patch.object(
                        backtest_service,
                        "_smart_balance_report_file_path",
                        side_effect=lambda file_name: str(root / file_name),
                    ),
                    patch.object(backtest_service, "get_all_history_asc", return_value=history),
                    patch.object(backtest_service, "_full_history_cache_profile_specs", return_value=specs),
                    patch.object(backtest_service, "run_backtest", side_effect=fake_run_backtest),
                    patch.object(backtest_service, "get_meta", return_value=None),
                    patch.object(backtest_service, "_cache_timestamp", return_value="2026-06-01T13:00:00+08:00"),
                    patch.object(backtest_service, "_clear_smart_balance_candidate_cache", return_value=None),
                ):
                    backtest_service._run_full_history_cache_rebuild_job(job_id)

                report = json.loads((root / "cache_default.json").read_text(encoding="utf-8"))
                manifest = json.loads((root / "full_history_cache_3_basic.manifest.json").read_text(encoding="utf-8"))
                job = backtest_service._full_history_cache_jobs[job_id]
            finally:
                backtest_service._full_history_cache_jobs.clear()
                backtest_service._full_history_cache_jobs.update(old_jobs)

        self.assertEqual(run_backtest_calls, [1])
        self.assertEqual(job.status, "completed")
        self.assertEqual(report["total_issues"], expected_issue_count)
        self.assertEqual(len(report["issues"]), expected_issue_count)
        self.assertEqual(report["issues"][-1]["issue"], latest_issue)
        self.assertEqual(report["full_history_cache"]["latest_issue"], latest_issue)
        self.assertEqual(manifest["latest_issue"], latest_issue)
        self.assertEqual(manifest["expected_issue_count"], expected_issue_count)

    def test_rebuild_now_skips_when_cache_already_valid(self) -> None:
        valid_status = SimpleNamespace(valid=True, marker="ready")

        with patch.object(backtest_service, "get_full_history_cache_status", return_value=valid_status):
            result = backtest_service.rebuild_full_history_cache_now(3, "basic")

        self.assertIs(result, valid_status)

    def test_rebuild_now_runs_synchronously(self) -> None:
        invalid_status = SimpleNamespace(valid=False)
        valid_status = SimpleNamespace(valid=True, marker="done")
        old_jobs = dict(backtest_service._full_history_cache_jobs)
        seen_job_ids: list[str] = []

        def fake_run(job_id: str) -> None:
            seen_job_ids.append(job_id)
            job = backtest_service._full_history_cache_jobs[job_id]
            job.status = "completed"
            job.progress = 1.0
            job.finished_at = datetime.utcnow()

        try:
            backtest_service._full_history_cache_jobs.clear()
            with (
                patch.object(
                    backtest_service,
                    "get_full_history_cache_status",
                    side_effect=[invalid_status, valid_status],
                ),
                patch.object(backtest_service, "_run_full_history_cache_rebuild_job", side_effect=fake_run) as run_mock,
            ):
                result = backtest_service.rebuild_full_history_cache_now(8, "basic")
        finally:
            backtest_service._full_history_cache_jobs.clear()
            backtest_service._full_history_cache_jobs.update(old_jobs)

        self.assertIs(result, valid_status)
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[0], seen_job_ids[0])


if __name__ == "__main__":
    unittest.main()
