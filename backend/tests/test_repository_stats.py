import unittest
from datetime import date, datetime

from app.models import (
    DivinationRun,
    DivinationRunScheme,
    PrizeEvaluation,
    SavedScheme,
)
from app.services.repository import build_divination_run_stats, build_saved_scheme_stats


class RepositoryStatsTests(unittest.TestCase):
    def test_build_saved_scheme_stats_matches_expected_aggregates(self) -> None:
        items = [
            SavedScheme(
                id=1,
                target_issue="26060",
                seed_mode="issue",
                seed_value="26060",
                moving_line=1,
                ai_engine="local",
                label="A",
                confidence=0.8,
                strategy="smart",
                front_numbers=[1, 2, 3, 4, 5],
                back_numbers=[1, 2],
                rationale="a",
                multiple=1,
                is_additional=False,
                created_at=datetime(2026, 6, 18, 10, 0, 0),
                updated_at=datetime(2026, 6, 18, 10, 0, 0),
                evaluation=PrizeEvaluation(
                    status="won",
                    prize_level="七等奖",
                    prize_amount=5.0,
                    cost_amount=2.0,
                    draw_date=date(2026, 6, 18),
                ),
            ),
            SavedScheme(
                id=2,
                target_issue="26060",
                seed_mode="issue",
                seed_value="26060",
                moving_line=1,
                ai_engine="local",
                label="B",
                confidence=0.6,
                strategy="smart",
                front_numbers=[6, 7, 8, 9, 10],
                back_numbers=[3, 4],
                rationale="b",
                multiple=1,
                is_additional=True,
                created_at=datetime(2026, 6, 18, 10, 1, 0),
                updated_at=datetime(2026, 6, 18, 10, 1, 0),
                evaluation=PrizeEvaluation(
                    status="not_won",
                    cost_amount=3.0,
                    draw_date=date(2026, 6, 18),
                ),
            ),
            SavedScheme(
                id=3,
                target_issue="26061",
                seed_mode="issue",
                seed_value="26061",
                moving_line=1,
                ai_engine="local",
                label="C",
                confidence=0.4,
                strategy="smart",
                front_numbers=[11, 12, 13, 14, 15],
                back_numbers=[5, 6],
                rationale="c",
                multiple=1,
                is_additional=False,
                created_at=datetime(2026, 6, 18, 10, 2, 0),
                updated_at=datetime(2026, 6, 18, 10, 2, 0),
                evaluation=PrizeEvaluation(
                    status="pending",
                    cost_amount=2.0,
                ),
            ),
        ]

        stats = build_saved_scheme_stats(items)

        self.assertEqual(stats.total_saved, 3)
        self.assertEqual(stats.evaluated_count, 2)
        self.assertEqual(stats.pending_count, 1)
        self.assertEqual(stats.won_count, 1)
        self.assertEqual(stats.total_cost, 7.0)
        self.assertEqual(stats.total_prize_amount, 5.0)
        self.assertEqual(stats.basic.total_saved, 2)
        self.assertEqual(stats.basic.evaluated_count, 1)
        self.assertEqual(stats.basic.won_count, 1)
        self.assertEqual(stats.additional.total_saved, 1)
        self.assertEqual(stats.additional.evaluated_count, 1)
        self.assertEqual(stats.additional.won_count, 0)
        prize_rates = {item.level: item.rate for item in stats.prize_rates}
        self.assertEqual(prize_rates["七等奖"], 0.5)

    def test_build_divination_run_stats_matches_expected_aggregates(self) -> None:
        items = [
            DivinationRun(
                id=1,
                target_issue="26060",
                seed_mode="issue",
                seed_value="26060",
                divination_datetime="2026-06-18 10:00",
                target_draw_datetime="2026-06-18 21:30",
                requested_scheme_count=3,
                visible_scheme_count=2,
                requested_strategy_mode="smart_balance",
                effective_strategy_mode="smart_balance",
                moving_line=1,
                ai_engine="local",
                created_at=datetime(2026, 6, 18, 10, 0, 0),
                schemes=[
                    DivinationRunScheme(
                        id=1,
                        run_id=1,
                        scheme_index=1,
                        label="A",
                        confidence=0.9,
                        strategy="smart",
                        front_numbers=[1, 2, 3, 4, 5],
                        back_numbers=[1, 2],
                        rationale="a",
                        evaluation=PrizeEvaluation(status="won", cost_amount=2.0, prize_amount=5.0),
                    ),
                    DivinationRunScheme(
                        id=2,
                        run_id=1,
                        scheme_index=2,
                        label="B",
                        confidence=0.5,
                        strategy="smart",
                        front_numbers=[6, 7, 8, 9, 10],
                        back_numbers=[3, 4],
                        rationale="b",
                        evaluation=PrizeEvaluation(status="pending", cost_amount=2.0),
                    ),
                ],
            ),
            DivinationRun(
                id=2,
                target_issue="26061",
                seed_mode="issue",
                seed_value="26061",
                divination_datetime="2026-06-18 11:00",
                target_draw_datetime="2026-06-20 21:30",
                requested_scheme_count=3,
                visible_scheme_count=1,
                requested_strategy_mode="smart_balance",
                effective_strategy_mode="smart_balance",
                moving_line=2,
                ai_engine="local",
                created_at=datetime(2026, 6, 18, 11, 0, 0),
                schemes=[
                    DivinationRunScheme(
                        id=3,
                        run_id=2,
                        scheme_index=1,
                        label="C",
                        confidence=0.4,
                        strategy="smart",
                        front_numbers=[11, 12, 13, 14, 15],
                        back_numbers=[5, 6],
                        rationale="c",
                        evaluation=PrizeEvaluation(status="not_won", cost_amount=2.0),
                    )
                ],
            ),
        ]

        stats = build_divination_run_stats(items)

        self.assertEqual(stats.total_runs, 2)
        self.assertEqual(stats.evaluated_runs, 2)
        self.assertEqual(stats.pending_runs, 0)
        self.assertEqual(stats.hit_issue_count, 1)
        self.assertEqual(stats.total_scheme_count, 3)
        self.assertEqual(stats.evaluated_scheme_count, 2)
        self.assertEqual(stats.won_scheme_count, 1)
        self.assertEqual(stats.scheme_win_rate, 0.5)
        self.assertEqual(stats.issue_hit_rate, 0.5)


if __name__ == "__main__":
    unittest.main()
