import math
import unittest
from datetime import date

from app.db import ensure_database
from app.services.backtest_service import _build_issue_results_for_threshold_resolver, run_backtest


class BacktestTicketModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_database()

    def test_additional_ticket_mode_changes_costs(self) -> None:
        basic = run_backtest(
            recent_issues=5,
            scheme_count=2,
            strategy_mode="multi_cover",
            ticket_mode="basic",
            compare_modes=False,
        )
        additional = run_backtest(
            recent_issues=5,
            scheme_count=2,
            strategy_mode="multi_cover",
            ticket_mode="additional",
            compare_modes=False,
        )

        self.assertEqual(basic.ticket_mode, "basic")
        self.assertEqual(additional.ticket_mode, "additional")
        self.assertEqual(len(basic.issues), len(additional.issues))
        self.assertGreater(len(basic.issues), 0)

        self.assertTrue(math.isclose(basic.total_cost, sum(item.cost for item in basic.issues), rel_tol=1e-9))
        self.assertTrue(math.isclose(additional.total_cost, sum(item.cost for item in additional.issues), rel_tol=1e-9))
        self.assertGreater(additional.total_cost, 0)

        for basic_issue, additional_issue in zip(basic.issues, additional.issues):
            self.assertEqual(basic_issue.issue, additional_issue.issue)
            self.assertEqual(basic_issue.ticket_mode, "basic")
            self.assertEqual(additional_issue.ticket_mode, "additional")
            self.assertTrue(math.isclose(basic_issue.cost, basic_issue.scheme_count * 2.0, rel_tol=1e-9))
            self.assertTrue(math.isclose(additional_issue.cost, additional_issue.scheme_count * 3.0, rel_tol=1e-9))

    def test_local_only_ai_replay_mode_is_default(self) -> None:
        response = run_backtest(
            recent_issues=5,
            scheme_count=2,
            strategy_mode="multi_cover",
            ticket_mode="basic",
            compare_modes=False,
        )

        self.assertEqual(response.ai_replay_mode, "local_only")

    def test_main_backtest_uses_fixed_full_count_policy(self) -> None:
        response = run_backtest(
            recent_issues=5,
            scheme_count=3,
            strategy_mode="multi_cover",
            ticket_mode="basic",
            compare_modes=False,
        )

        self.assertEqual(response.count_policy, "fixed_full_count")
        self.assertEqual(response.skipped_issues, 0)
        self.assertGreater(response.total_issues, 0)
        self.assertEqual(response.total_generated_schemes, response.total_issues * 3)
        self.assertTrue(all(item.scheme_count == 3 for item in response.issues))
        self.assertTrue(all(item.count_policy == "fixed_full_count" for item in response.issues))

    def test_threshold_resolver_keeps_observe_issue_in_denominator(self) -> None:
        issue_results, skipped_issues, avg_scheme_count, avg_applied_threshold = _build_issue_results_for_threshold_resolver(
            [
                {
                    "issue": "26001",
                    "draw_date": date(2026, 1, 1),
                    "issue_confidence": 0.11,
                    "calibrated_confidence": 0.11,
                    "front_confidence": 0.10,
                    "front_calibrated_confidence": 0.10,
                    "front_gate": 0.20,
                    "back_confidence": 0.10,
                    "back_calibrated_confidence": 0.10,
                    "back_gate": 0.20,
                    "decision_tier": "observe",
                    "deep_search_triggered": False,
                    "deep_search_reason": None,
                    "decision_reason": "below threshold",
                    "schemes": [],
                    "evaluations": [],
                }
            ],
            strategy_mode="multi_cover",
            max_scheme_count=5,
            ticket_mode="basic",
            threshold_resolver=lambda _confidence: 0.20,
            count_policy="baseline",
        )

        self.assertEqual(skipped_issues, 1)
        self.assertEqual(len(issue_results), 1)
        self.assertEqual(issue_results[0]["scheme_count"], 0)
        self.assertEqual(issue_results[0]["won_count"], 0)
        self.assertEqual(issue_results[0]["cost"], 0.0)
        self.assertEqual(avg_scheme_count, 0.0)
        self.assertEqual(avg_applied_threshold, 0.0)

    def test_external_rerank_requires_complete_ai_config(self) -> None:
        with self.assertRaisesRegex(ValueError, "AI 重排"):
            run_backtest(
                recent_issues=5,
                scheme_count=2,
                strategy_mode="multi_cover",
                ticket_mode="basic",
                ai_replay_mode="external_rerank",
                compare_modes=False,
            )


if __name__ == "__main__":
    unittest.main()
