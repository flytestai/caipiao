import unittest
import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch

from app.db import ensure_database
from app.models import BacktestStabilityBreakdown, BacktestTuningSummary
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
        report_file_name = "full_history_cache_3_basic_default_multi.json"
        specs = {
            "default_multi": {
                "candidate_name": "multi_cover:balanced+balanced_combo",
                "strategy_mode": "multi_cover",
                "tuning_profile_override": "balanced+balanced_combo",
                "file_name": report_file_name,
            }
        }
        issue_rows = self._issue_rows_from_history(history, [30, 31])

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_json(
                root,
                report_file_name,
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
                            "file_name": report_file_name,
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

    def test_expected_issue_count_uses_constant_time_formula(self) -> None:
        history = self._make_history(45)

        with patch.object(backtest_service, "_build_history_context_cache", side_effect=AssertionError("should not build history context")):
            issue_count = backtest_service._expected_full_history_cache_issue_count(history)

        self.assertEqual(issue_count, 15)
        self.assertEqual(backtest_service._expected_full_history_cache_issue_count_for_total_draws(45), 15)

    def test_rebuild_job_only_appends_missing_tail(self) -> None:
        history = self._make_history(33)
        latest_issue = str(history[-1].issue)
        expected_issue_count = backtest_service._expected_full_history_cache_issue_count(history)
        report_file_name = "full_history_cache_3_basic_default_multi.json"
        specs = {
            "default_multi": {
                "candidate_name": "multi_cover:balanced+balanced_combo",
                "strategy_mode": "multi_cover",
                "tuning_profile_override": "balanced+balanced_combo",
                "file_name": report_file_name,
            }
        }
        existing_issue_rows = self._issue_rows_from_history(history, [30, 31])
        appended_issue_rows = self._issue_rows_from_history(history, [32])
        run_backtest_calls: list[dict] = []

        def fake_run_backtest(*, recent_issues: int, **_kwargs):
            run_backtest_calls.append(
                {
                    "recent_issues": recent_issues,
                    "skip_auto_tuning_search": _kwargs.get("skip_auto_tuning_search"),
                    "history_context_cache": _kwargs.get("history_context_cache"),
                }
            )
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
                report_file_name,
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
                            "file_name": report_file_name,
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
                    report = backtest_service._load_json_report(report_file_name)
                    report_summary = json.loads((root / report_file_name).read_text(encoding="utf-8"))
                    report_issues = json.loads(
                        (root / backtest_service._full_history_cache_issue_sidecar_file_name(report_file_name)).read_text(
                            encoding="utf-8"
                        )
                    )
                    loaded_issue_rows = backtest_service._load_full_history_cache_issue_rows(report_file_name)
                    candidate_cache = json.loads(
                        (root / backtest_service._smart_balance_candidate_cache_file_name(report_file_name)).read_text(
                            encoding="utf-8"
                        )
                    )
                    manifest = json.loads((root / "full_history_cache_3_basic.manifest.json").read_text(encoding="utf-8"))
                    job = backtest_service._full_history_cache_jobs[job_id]
            finally:
                backtest_service._full_history_cache_jobs.clear()
                backtest_service._full_history_cache_jobs.update(old_jobs)

        self.assertEqual(len(run_backtest_calls), 1)
        self.assertEqual(run_backtest_calls[0]["recent_issues"], 1)
        self.assertTrue(run_backtest_calls[0]["skip_auto_tuning_search"])
        self.assertIsInstance(run_backtest_calls[0]["history_context_cache"], dict)
        self.assertEqual(job.status, "completed")
        self.assertEqual(report["total_issues"], expected_issue_count)
        self.assertEqual(len(report["issues"]), expected_issue_count)
        self.assertEqual(report["issues"][-1]["issue"], latest_issue)
        self.assertNotIn("issues", report_summary)
        self.assertEqual(report_issues["issue_count"], expected_issue_count)
        self.assertEqual(len(loaded_issue_rows or []), expected_issue_count)
        self.assertEqual(report["full_history_cache"]["latest_issue"], latest_issue)
        self.assertEqual(report["full_history_cache"]["requested_issues"], len(history))
        self.assertEqual(candidate_cache["issue_map"][latest_issue]["issue"], latest_issue)
        self.assertEqual(len(candidate_cache["issue_map"]), expected_issue_count)
        self.assertEqual(manifest["latest_issue"], latest_issue)
        self.assertEqual(manifest["expected_issue_count"], expected_issue_count)
        self.assertEqual(manifest["profiles"]["default_multi"]["requested_issues"], len(history))

    def test_rebuild_job_reuses_complete_profile_without_rewriting_report(self) -> None:
        history = self._make_history(33)
        latest_issue = str(history[-1].issue)
        expected_issue_count = backtest_service._expected_full_history_cache_issue_count(history)
        report_file_name = "full_history_cache_3_basic_default_multi.json"
        specs = {
            "default_multi": {
                "candidate_name": "multi_cover:balanced+balanced_combo",
                "strategy_mode": "multi_cover",
                "tuning_profile_override": "balanced+balanced_combo",
                "file_name": report_file_name,
            }
        }
        complete_issue_rows = self._issue_rows_from_history(history, [30, 31, 32])

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_json(
                root,
                report_file_name,
                {
                    "requested_issues": len(history),
                    "scheme_count": 3,
                    "strategy_mode": "multi_cover",
                    "ticket_mode": "basic",
                    "total_issues": expected_issue_count,
                    "total_generated_schemes": 9,
                    "won_schemes": 0,
                    "total_prize_amount": 0.0,
                    "total_cost": 18.0,
                    "net_profit": -18.0,
                    "overall_win_rate": 0.0,
                    "issue_hit_rate": 0.0,
                    "prize_rates": [],
                    "prize_level_breakdown": [],
                    "issues": complete_issue_rows,
                    "coverage_metrics": {},
                    "window_summaries": [],
                    "benchmarks": [],
                    "mode_comparison": [],
                    "issue_comparison": [],
                    "threshold_scan": [],
                    "full_history_cache": {
                        "algorithm_version": backtest_service.FULL_HISTORY_CACHE_ALGORITHM_VERSION,
                        "generated_at": "2026-06-01T12:00:00+08:00",
                        "source_snapshot_at": "2026-06-01T12:00:00+08:00",
                        "latest_issue": latest_issue,
                        "total_draws": len(history),
                        "expected_issue_count": expected_issue_count,
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
                    "algorithm_version": backtest_service.FULL_HISTORY_CACHE_ALGORITHM_VERSION,
                    "generated_at": "2026-06-01T12:00:00+08:00",
                    "source_snapshot_at": "2026-06-01T12:00:00+08:00",
                    "latest_issue": latest_issue,
                    "total_draws": len(history),
                    "expected_issue_count": expected_issue_count,
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "profiles": {
                        "default_multi": {
                            "profile": "default_multi",
                            "file_name": report_file_name,
                            "generated_at": "2026-06-01T12:00:00+08:00",
                            "latest_issue": latest_issue,
                            "scheme_count": 3,
                            "ticket_mode": "basic",
                            "requested_issues": len(history),
                            "total_issues": expected_issue_count,
                            "total_generated_schemes": 9,
                            "issue_hit_rate": 0.0,
                            "overall_win_rate": 0.0,
                            "total_prize_amount": 0.0,
                            "net_profit": -18.0,
                        }
                    },
                },
            )

            report_path = root / report_file_name
            original_report_text = report_path.read_text(encoding="utf-8")

            job_id = "job-reuse-complete"
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
                    patch.object(backtest_service, "run_backtest", side_effect=AssertionError("should not rerun complete profile")),
                    patch.object(backtest_service, "get_meta", return_value=None),
                    patch.object(backtest_service, "_cache_timestamp", return_value="2026-06-01T13:00:00+08:00"),
                    patch.object(backtest_service, "_clear_smart_balance_candidate_cache", return_value=None),
                ):
                    backtest_service._run_full_history_cache_rebuild_job(job_id)

                final_report_text = report_path.read_text(encoding="utf-8")
                manifest = json.loads((root / "full_history_cache_3_basic.manifest.json").read_text(encoding="utf-8"))
                job = backtest_service._full_history_cache_jobs[job_id]
            finally:
                backtest_service._full_history_cache_jobs.clear()
                backtest_service._full_history_cache_jobs.update(old_jobs)

        self.assertEqual(job.status, "completed")
        self.assertEqual(final_report_text, original_report_text)
        self.assertEqual(manifest["profiles"]["default_multi"]["latest_issue"], latest_issue)
        self.assertEqual(manifest["profiles"]["default_multi"]["total_issues"], expected_issue_count)

    def test_large_scheme_count_rebuild_uses_coarse_search_profile(self) -> None:
        history = self._make_history(32)
        latest_issue = str(history[-1].issue)
        expected_issue_count = backtest_service._expected_full_history_cache_issue_count(history)
        spec = backtest_service._full_history_cache_profile_specs(5, "basic")["candidate_multi"]
        issue_rows = self._issue_rows_from_history(history, [30, 31])
        run_backtest_calls: list[dict] = []
        rebuild_context_cache = backtest_service._build_history_context_cache(history, history)
        history_positions = {str(draw.issue): index for index, draw in enumerate(history)}

        def fake_run_backtest(**kwargs):
            run_backtest_calls.append(kwargs)
            response = build_backtest_stats(issue_rows)  # type: ignore[arg-type]
            response.requested_issues = kwargs["recent_issues"]
            response.recent_issues = kwargs["recent_issues"]
            response.scheme_count = 5
            response.strategy_mode = "multi_cover"  # type: ignore[assignment]
            response.ticket_mode = "basic"  # type: ignore[assignment]
            response.ai_replay_mode = "local_only"  # type: ignore[assignment]
            response.benchmarks = []
            response.window_summaries = []
            response.mode_comparison = []
            response.issue_comparison = []
            response.threshold_scan = []
            return response

        with patch.object(backtest_service, "run_backtest", side_effect=fake_run_backtest):
            profile_name, payload, metadata = backtest_service._build_full_history_cache_profile_result(
                profile="candidate_multi",
                spec=spec,
                history_asc=history,
                latest_issue=latest_issue,
                total_draws=len(history),
                expected_issue_count=expected_issue_count,
                scheme_count=5,
                ticket_mode="basic",
                source_snapshot_at="2026-06-20T23:00:00+08:00",
                rebuild_context_cache=rebuild_context_cache,
                manifest_profile=None,
                manifest_source_snapshot_at=None,
                history_positions=history_positions,
            )

        self.assertEqual(profile_name, "candidate_multi")
        self.assertIsInstance(payload, dict)
        self.assertEqual(metadata["requested_issues"], len(history))
        self.assertEqual(len(run_backtest_calls), 1)
        self.assertEqual(run_backtest_calls[0]["search_profile"], "coarse")

    def test_full_history_cache_payload_build_avoids_full_response_model_dump(self) -> None:
        appended_issue_rows = self._issue_rows_from_history(self._make_history(33), [32])
        response = build_backtest_stats(appended_issue_rows)  # type: ignore[arg-type]
        response.requested_issues = 1
        response.recent_issues = 1
        response.scheme_count = 3
        response.strategy_mode = "multi_cover"  # type: ignore[assignment]
        response.ticket_mode = "basic"  # type: ignore[assignment]
        response.ai_replay_mode = "local_only"  # type: ignore[assignment]
        response.benchmarks = []
        response.window_summaries = []
        response.mode_comparison = []
        response.issue_comparison = []
        response.threshold_scan = []
        response.stability_breakdown = BacktestStabilityBreakdown(base_score=1.25, adjusted_score=1.1)
        response.tuning_summary = BacktestTuningSummary(enabled=False, sample_issues=1, weights={"score": 0.5})

        with patch.object(type(response), "model_dump", autospec=True) as model_dump_mock:
            payload = backtest_service._build_full_history_cache_report_payload(
                existing_report=None,
                response=response,
                combined_issue_rows=appended_issue_rows,
                recent_issues=1,
                scheme_count=3,
                strategy_mode="multi_cover",
                ticket_mode="basic",
            )

        model_dump_mock.assert_not_called()
        self.assertEqual(payload["issues"], appended_issue_rows)
        self.assertEqual(payload["stability_breakdown"]["base_score"], 1.25)
        self.assertEqual(payload["tuning_summary"]["weights"]["score"], 0.5)

    def test_run_backtest_forwards_shared_history_context_cache(self) -> None:
        shared_cache = {"26001": ("history", "context")}  # type: ignore[dict-item]
        history_asc = self._make_history(40)

        def fake_run_backtest_core(history_asc, **kwargs):
            self.assertIs(kwargs.get("history_context_cache"), shared_cache)
            response = build_backtest_stats([])  # type: ignore[arg-type]
            response.requested_issues = kwargs["recent_issues"]
            response.recent_issues = kwargs["recent_issues"]
            response.scheme_count = kwargs["scheme_count"]
            response.strategy_mode = kwargs["strategy_mode"]  # type: ignore[assignment]
            response.ticket_mode = kwargs["ticket_mode"]  # type: ignore[assignment]
            response.ai_replay_mode = kwargs["ai_replay_mode"]  # type: ignore[assignment]
            response.benchmarks = []
            response.window_summaries = []
            response.mode_comparison = []
            response.issue_comparison = []
            response.threshold_scan = []
            return response

        with (
            patch.object(backtest_service, "get_all_history_asc", return_value=history_asc),
            patch.object(backtest_service, "_run_backtest_core", side_effect=fake_run_backtest_core),
        ):
            result = backtest_service.run_backtest(
                recent_issues=10,
                scheme_count=3,
                strategy_mode="multi_cover",
                ticket_mode="basic",
                ai_replay_mode="local_only",
                compare_modes=False,
                ai_config=None,
                include_baselines=False,
                include_applied_profile_comparison=False,
                skip_auto_tuning_search=True,
                history_context_cache=shared_cache,
            )

        self.assertEqual(result.requested_issues, 10)

    def test_issue_rows_helper_matches_backtest_response_issue_payloads(self) -> None:
        issue_rows = self._issue_rows_from_history(self._make_history(33), [30, 31, 32])
        response = build_backtest_stats(issue_rows)  # type: ignore[arg-type]

        helper_rows = backtest_service._issue_rows_from_backtest_response(response)

        self.assertEqual([row["issue"] for row in helper_rows], [row["issue"] for row in issue_rows])
        self.assertEqual(helper_rows[0]["won_count"], issue_rows[0]["won_count"])
        self.assertEqual(helper_rows[0]["draw_date"], issue_rows[0]["draw_date"].isoformat())
        helper_rows[0]["prize_level_hits"]["七等奖"] = 1
        self.assertEqual(response.issues[0].prize_level_hits, {})

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

    def test_cached_json_report_is_invalidated_after_atomic_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            file_name = "status_cache.json"
            self._write_json(root, file_name, {"value": 1})
            path = str(root / file_name)

            with patch.object(
                backtest_service,
                "_smart_balance_report_file_path",
                side_effect=lambda target_file_name: str(root / target_file_name),
            ):
                backtest_service._clear_json_dict_file_cache()
                first = backtest_service._load_json_report(file_name)
                backtest_service._write_json_report_atomic(file_name, {"value": 2})
                second = backtest_service._load_json_report(file_name)

        self.assertEqual(first, {"value": 1})
        self.assertEqual(second, {"value": 2})

    def test_full_history_cache_report_uses_issue_sidecar_chunks_and_load_rehydrates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            file_name = "full_history_cache_3_basic_default_multi.json"
            payload = {
                "requested_issues": 33,
                "scheme_count": 3,
                "strategy_mode": "multi_cover",
                "ticket_mode": "basic",
                "total_issues": 3,
                "issues": [
                    {"issue": "26060", "won_count": 0, "total_prize_amount": 0.0},
                    {"issue": "26061", "won_count": 1, "total_prize_amount": 5.0},
                    {"issue": "26062", "won_count": 0, "total_prize_amount": 0.0},
                ],
                "full_history_cache": {
                    "algorithm_version": "full-history-cache-v2026-06-01-02",
                    "generated_at": "2026-06-01T12:00:00+08:00",
                    "latest_issue": "26062",
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "profile": "default_multi",
                },
            }

            with patch.object(
                backtest_service,
                "_smart_balance_report_file_path",
                side_effect=lambda target_file_name: str(root / target_file_name),
            ), patch.object(backtest_service, "FULL_HISTORY_CACHE_ISSUE_CHUNK_SIZE", 2):
                backtest_service._clear_json_dict_file_cache()
                backtest_service._write_json_report_atomic(file_name, payload)
                report_summary = json.loads((root / file_name).read_text(encoding="utf-8"))
                issue_sidecar = json.loads(
                    (root / backtest_service._full_history_cache_issue_sidecar_file_name(file_name)).read_text(
                        encoding="utf-8"
                    )
                )
                first_chunk = json.loads(
                    (root / backtest_service._full_history_cache_issue_chunk_file_name(file_name, 0)).read_text(
                        encoding="utf-8"
                    )
                )
                second_chunk = json.loads(
                    (root / backtest_service._full_history_cache_issue_chunk_file_name(file_name, 1)).read_text(
                        encoding="utf-8"
                    )
                )
                rehydrated = backtest_service._load_json_report(file_name)

        self.assertNotIn("issues", report_summary)
        self.assertTrue(issue_sidecar["sharded_issues"])
        self.assertEqual(issue_sidecar["issue_count"], 3)
        self.assertEqual(len(issue_sidecar["chunks"]), 2)
        self.assertEqual(len(first_chunk["issues"]), 2)
        self.assertEqual(len(second_chunk["issues"]), 1)
        self.assertEqual(rehydrated["issues"][2]["issue"], "26062")

    def test_full_history_cache_issue_sidecar_append_reuses_completed_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            file_name = "full_history_cache_3_basic_default_multi.json"
            initial_payload = {
                "requested_issues": 33,
                "scheme_count": 3,
                "strategy_mode": "multi_cover",
                "ticket_mode": "basic",
                "total_issues": 3,
                "issues": [
                    {"issue": "26060", "won_count": 0, "total_prize_amount": 0.0},
                    {"issue": "26061", "won_count": 1, "total_prize_amount": 5.0},
                    {"issue": "26062", "won_count": 0, "total_prize_amount": 0.0},
                ],
                "full_history_cache": {
                    "algorithm_version": "full-history-cache-v2026-06-01-02",
                    "generated_at": "2026-06-01T12:00:00+08:00",
                    "latest_issue": "26062",
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "profile": "default_multi",
                },
            }
            appended_payload = {
                **initial_payload,
                "total_issues": 4,
                "issues": [
                    *initial_payload["issues"],
                    {"issue": "26063", "won_count": 0, "total_prize_amount": 0.0},
                ],
                "full_history_cache": {
                    **initial_payload["full_history_cache"],
                    "latest_issue": "26063",
                },
            }

            with patch.object(
                backtest_service,
                "_smart_balance_report_file_path",
                side_effect=lambda target_file_name: str(root / target_file_name),
            ), patch.object(backtest_service, "FULL_HISTORY_CACHE_ISSUE_CHUNK_SIZE", 2):
                backtest_service._clear_json_dict_file_cache()
                backtest_service._write_json_report_atomic(file_name, initial_payload)
                backtest_service._clear_json_dict_file_cache()

                original_write_json_file_atomic = backtest_service._write_json_file_atomic
                with patch.object(
                    backtest_service,
                    "_write_json_file_atomic",
                    wraps=original_write_json_file_atomic,
                ) as write_mock:
                    backtest_service._write_json_report_atomic(file_name, appended_payload)

            written_paths = [Path(call.args[0]).name for call in write_mock.call_args_list]
            self.assertNotIn(backtest_service._full_history_cache_issue_chunk_file_name(file_name, 0), written_paths)
            self.assertIn(backtest_service._full_history_cache_issue_chunk_file_name(file_name, 1), written_paths)

    def test_atomic_report_rewrite_clears_signature_cache(self) -> None:
        old_signature_cache = dict(backtest_service._smart_balance_report_signature_cache)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                file_name = "status_cache.json"
                self._write_json(root, file_name, {"value": 1})

                with patch.object(
                    backtest_service,
                    "_smart_balance_report_file_path",
                    side_effect=lambda target_file_name: str(root / target_file_name),
                ):
                    backtest_service._smart_balance_report_signature_cache[(3, "basic")] = (999999.0, (("cached", 1.0, 1),))
                    backtest_service._write_json_report_atomic(file_name, {"value": 2})

                self.assertEqual(backtest_service._smart_balance_report_signature_cache, {})
        finally:
            backtest_service._smart_balance_report_signature_cache.clear()
            backtest_service._smart_balance_report_signature_cache.update(old_signature_cache)

    def test_full_history_cache_status_uses_short_lived_result_cache(self) -> None:
        history = self._make_history(32)
        latest_issue = str(history[-1].issue)
        expected_issue_count = backtest_service._expected_full_history_cache_issue_count(history)
        report_file_name = "full_history_cache_3_basic_default_multi.json"
        specs = {
            "default_multi": {
                "candidate_name": "multi_cover:balanced+balanced_combo",
                "strategy_mode": "multi_cover",
                "tuning_profile_override": "balanced+balanced_combo",
                "file_name": report_file_name,
            }
        }
        issue_rows = self._issue_rows_from_history(history, [30, 31])

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_json(
                root,
                report_file_name,
                {
                    "requested_issues": len(history),
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "total_issues": expected_issue_count,
                    "issues": issue_rows,
                    "full_history_cache": {
                        "algorithm_version": "full-history-cache-v2026-06-01-02",
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
                    "algorithm_version": "full-history-cache-v2026-06-01-02",
                    "generated_at": "2026-06-01T12:00:00+08:00",
                    "source_snapshot_at": "2026-06-01T12:00:00+08:00",
                    "latest_issue": latest_issue,
                    "total_draws": len(history),
                    "expected_issue_count": expected_issue_count,
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "profiles": {"default_multi": {"file_name": report_file_name}},
                },
            )

            with (
                patch.object(backtest_service, "_smart_balance_report_file_path", side_effect=lambda file_name: str(root / file_name)),
                patch.object(backtest_service, "get_all_history_asc", return_value=history),
                patch.object(backtest_service, "get_meta", return_value=None),
                patch.object(backtest_service, "_full_history_cache_profile_specs", return_value=specs),
                patch.object(backtest_service, "_load_full_history_cache_manifest", wraps=backtest_service._load_full_history_cache_manifest) as manifest_mock,
            ):
                backtest_service._clear_full_history_cache_status_cache()
                status_first = backtest_service.get_full_history_cache_status(3, "basic")
                status_second = backtest_service.get_full_history_cache_status(3, "basic")

        self.assertTrue(status_first.valid)
        self.assertTrue(status_second.valid)
        self.assertEqual(manifest_mock.call_count, 1)

    def test_full_history_cache_status_cached_result_is_cloned_per_call(self) -> None:
        cache_key = backtest_service._full_history_cache_key(3, "basic")
        cached_status = backtest_service.FullHistoryCacheStatus(
            algorithm_version="v-test",
            latest_issue="2026001",
            total_draws=1,
            expected_issue_count=1,
            scheme_count=3,
            ticket_mode="basic",
            valid=True,
            stale_reasons=["ok"],
            profiles=[
                backtest_service.FullHistoryCacheProfileStatus(
                    profile="default_multi",
                    mode="multi_cover",
                    file_name="cache.json",
                    exists=True,
                    valid=True,
                    issue_count=1,
                )
            ],
            active_job=backtest_service.FullHistoryCacheRebuildJob(
                job_id="job-1",
                status="running",
                progress=0.5,
                scheme_count=3,
                ticket_mode="basic",
                created_at=datetime.utcnow(),
            ),
        )
        old_cache = dict(backtest_service._full_history_status_cache)
        try:
            backtest_service._full_history_status_cache.clear()
            backtest_service._full_history_status_cache[cache_key] = (monotonic(), cached_status)

            first = backtest_service.get_full_history_cache_status(3, "basic")
            first.stale_reasons.append("mutated")
            first.profiles[0].reason = "changed"
            first.active_job.message = "changed"

            second = backtest_service.get_full_history_cache_status(3, "basic")

            self.assertEqual(second.stale_reasons, ["ok"])
            self.assertIsNone(second.profiles[0].reason)
            self.assertIsNone(second.active_job.message)
        finally:
            backtest_service._full_history_status_cache.clear()
            backtest_service._full_history_status_cache.update(old_cache)

    def test_full_history_cache_status_uses_manifest_profile_summary_without_loading_report(self) -> None:
        history = self._make_history(32)
        latest_issue = str(history[-1].issue)
        expected_issue_count = backtest_service._expected_full_history_cache_issue_count(history)
        report_file_name = "full_history_cache_3_basic_default_multi.json"
        specs = {
            "default_multi": {
                "candidate_name": "multi_cover:balanced+balanced_combo",
                "strategy_mode": "multi_cover",
                "tuning_profile_override": "balanced+balanced_combo",
                "file_name": report_file_name,
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_json(root, report_file_name, {"light": True})
            self._write_json(
                root,
                "full_history_cache_3_basic.manifest.json",
                {
                    "algorithm_version": "full-history-cache-v2026-06-01-02",
                    "generated_at": "2026-06-01T12:00:00+08:00",
                    "source_snapshot_at": "2026-06-01T12:00:00+08:00",
                    "latest_issue": latest_issue,
                    "total_draws": len(history),
                    "expected_issue_count": expected_issue_count,
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "profiles": {
                        "default_multi": {
                            "file_name": report_file_name,
                            "generated_at": "2026-06-01T12:00:00+08:00",
                            "latest_issue": latest_issue,
                            "scheme_count": 3,
                            "ticket_mode": "basic",
                            "requested_issues": len(history),
                            "total_issues": expected_issue_count,
                        }
                    },
                },
            )

            with (
                patch.object(backtest_service, "_smart_balance_report_file_path", side_effect=lambda file_name: str(root / file_name)),
                patch.object(backtest_service, "get_all_history_asc", return_value=history),
                patch.object(backtest_service, "get_meta", return_value=None),
                patch.object(backtest_service, "_full_history_cache_profile_specs", return_value=specs),
                patch.object(backtest_service, "_load_json_dict_file_cached", wraps=backtest_service._load_json_dict_file_cached) as load_mock,
            ):
                backtest_service._clear_full_history_cache_status_cache()
                status = backtest_service.get_full_history_cache_status(3, "basic")

        self.assertTrue(status.valid)
        self.assertEqual(load_mock.call_count, 1)

    def test_full_history_cache_status_falls_back_to_report_load_for_legacy_manifest(self) -> None:
        history = self._make_history(32)
        latest_issue = str(history[-1].issue)
        expected_issue_count = backtest_service._expected_full_history_cache_issue_count(history)
        report_file_name = "full_history_cache_3_basic_default_multi.json"
        specs = {
            "default_multi": {
                "candidate_name": "multi_cover:balanced+balanced_combo",
                "strategy_mode": "multi_cover",
                "tuning_profile_override": "balanced+balanced_combo",
                "file_name": report_file_name,
            }
        }
        issue_rows = self._issue_rows_from_history(history, [30, 31])

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_json(
                root,
                report_file_name,
                {
                    "requested_issues": len(history),
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "total_issues": expected_issue_count,
                    "issues": issue_rows,
                    "full_history_cache": {
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
                    "algorithm_version": "full-history-cache-v2026-06-01-02",
                    "generated_at": "2026-06-01T12:00:00+08:00",
                    "source_snapshot_at": "2026-06-01T12:00:00+08:00",
                    "latest_issue": latest_issue,
                    "total_draws": len(history),
                    "expected_issue_count": expected_issue_count,
                    "scheme_count": 3,
                    "ticket_mode": "basic",
                    "profiles": {"default_multi": {"file_name": report_file_name}},
                },
            )

            with (
                patch.object(backtest_service, "_smart_balance_report_file_path", side_effect=lambda file_name: str(root / file_name)),
                patch.object(backtest_service, "get_all_history_asc", return_value=history),
                patch.object(backtest_service, "get_meta", return_value=None),
                patch.object(backtest_service, "_full_history_cache_profile_specs", return_value=specs),
                patch.object(backtest_service, "_load_json_dict_file_cached", wraps=backtest_service._load_json_dict_file_cached) as load_mock,
            ):
                backtest_service._clear_full_history_cache_status_cache()
                status = backtest_service.get_full_history_cache_status(3, "basic")

        self.assertTrue(status.valid)
        self.assertGreaterEqual(load_mock.call_count, 2)

    def test_report_profile_status_reuses_precomputed_file_signature_for_legacy_report_load(self) -> None:
        signature = (123.0, 456)
        report = {
            "requested_issues": 32,
            "scheme_count": 3,
            "ticket_mode": "basic",
            "total_issues": 2,
            "issues": [
                {"issue": "26031"},
                {"issue": "26032"},
            ],
            "full_history_cache": {
                "generated_at": "2026-06-01T12:00:00+08:00",
                "latest_issue": "26032",
                "scheme_count": 3,
                "ticket_mode": "basic",
                "profile": "default_multi",
            },
        }

        with (
            patch.object(backtest_service, "_smart_balance_report_file_path", return_value="C:\\tmp\\cache_default.json"),
            patch.object(backtest_service, "_json_dict_file_signature", return_value=(signature, True)) as signature_mock,
            patch.object(backtest_service, "_load_json_dict_file_cached", return_value=(report, True)) as load_mock,
        ):
            status = backtest_service._report_profile_status(
                profile="default_multi",
                mode="multi_cover",
                file_name="cache_default.json",
                manifest_profile=None,
                latest_issue="26032",
                total_draws=32,
                expected_issue_count=2,
                scheme_count=3,
                ticket_mode="basic",
            )

        self.assertTrue(status.valid)
        signature_mock.assert_called_once()
        load_mock.assert_called_once_with(
            "C:\\tmp\\cache_default.json",
            warning_label="report cache_default.json",
            signature=signature,
        )

    def test_full_history_cache_status_cache_is_cleared_when_job_updates(self) -> None:
        old_jobs = dict(backtest_service._full_history_cache_jobs)
        old_status_cache = dict(backtest_service._full_history_status_cache)
        try:
            backtest_service._full_history_cache_jobs.clear()
            job = _FullHistoryCacheJobState(job_id="job-cache-clear", scheme_count=3, ticket_mode="basic")
            backtest_service._full_history_cache_jobs[job.job_id] = job
            cache_key = backtest_service._full_history_cache_key(3, "basic")
            backtest_service._full_history_status_cache[cache_key] = (0.0, SimpleNamespace())

            backtest_service._update_full_history_cache_job(job.job_id, status="running", progress=0.3)

            self.assertNotIn(cache_key, backtest_service._full_history_status_cache)
        finally:
            backtest_service._full_history_cache_jobs.clear()
            backtest_service._full_history_cache_jobs.update(old_jobs)
            backtest_service._full_history_status_cache.clear()
            backtest_service._full_history_status_cache.update(old_status_cache)


if __name__ == "__main__":
    unittest.main()
