import math
import unittest

from app.db import ensure_database
from app.services.backtest_service import run_backtest


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
