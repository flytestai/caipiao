import tempfile
import unittest
from datetime import date
from pathlib import Path

import app.db as db_module
from app.db import ensure_database
from app.models import AIAnalysis, DivinationResponse, FinalScheme, RecommendationSummary, TailWeightItem
from app.services.repository import list_divination_runs, save_divination_run, upsert_draws
from app.models import LottoDraw, PrizeLevelItem


class DivinationRunLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._original_data_dir = db_module.DATA_DIR
        cls._original_db_path = db_module.DB_PATH
        cls._tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        db_module.DATA_DIR = Path(cls._tempdir.name)
        db_module.DB_PATH = Path(cls._tempdir.name) / "lotto.db"
        ensure_database()

    @classmethod
    def tearDownClass(cls) -> None:
        db_module.DATA_DIR = cls._original_data_dir
        db_module.DB_PATH = cls._original_db_path
        cls._tempdir.cleanup()

    def test_save_and_list_divination_runs(self) -> None:
        upsert_draws(
            [
                LottoDraw(
                    issue="26054",
                    draw_date=date(2026, 5, 18),
                    front_numbers=[1, 2, 3, 4, 5],
                    back_numbers=[6, 7],
                    prize_level_list=[
                        PrizeLevelItem(prize_level="一等奖", award_type=0, stake_amount_format="1000000"),
                    ],
                )
            ]
        )
        response = DivinationResponse(
            seed_mode="issue",
            seed_value="26054",
            divination_datetime="2026-05-17 09:18",
            target_draw_datetime="2026-05-18 21:30",
            strategy_mode="smart_balance",
            moving_line=3,
            main_hexagram={"code": "1", "name": "乾", "upper_trigram": "乾", "lower_trigram": "乾", "element": "金", "lines": [1, 1, 1, 1, 1, 1]},
            mutual_hexagram={"code": "43", "name": "夬", "upper_trigram": "乾", "lower_trigram": "兑", "element": "金", "lines": [1, 1, 1, 1, 1, 0]},
            changed_hexagram={"code": "14", "name": "大有", "upper_trigram": "离", "lower_trigram": "乾", "element": "火", "lines": [1, 1, 1, 1, 0, 1]},
            active_elements=["金"],
            favored_tails=[1, 2],
            tail_weights=[TailWeightItem(tail=1, weight=0.8)],
            front_recommendations=[],
            back_recommendations=[],
            front_candidates=[],
            back_candidates=[],
            front_signal={
                "zone": "front",
                "main_hexagram": {"code": "1", "name": "乾", "upper_trigram": "乾", "lower_trigram": "乾", "element": "金", "lines": [1, 1, 1, 1, 1, 1]},
                "mutual_hexagram": {"code": "43", "name": "夬", "upper_trigram": "乾", "lower_trigram": "兑", "element": "金", "lines": [1, 1, 1, 1, 1, 0]},
                "changed_hexagram": {"code": "14", "name": "大有", "upper_trigram": "离", "lower_trigram": "乾", "element": "火", "lines": [1, 1, 1, 1, 0, 1]},
                "active_elements": ["金"],
                "favored_tails": [1, 2],
                "tail_weights": [TailWeightItem(tail=1, weight=0.8)],
            },
            back_signal={
                "zone": "back",
                "main_hexagram": {"code": "1", "name": "乾", "upper_trigram": "乾", "lower_trigram": "乾", "element": "金", "lines": [1, 1, 1, 1, 1, 1]},
                "mutual_hexagram": {"code": "43", "name": "夬", "upper_trigram": "乾", "lower_trigram": "兑", "element": "金", "lines": [1, 1, 1, 1, 1, 0]},
                "changed_hexagram": {"code": "14", "name": "大有", "upper_trigram": "离", "lower_trigram": "乾", "element": "火", "lines": [1, 1, 1, 1, 0, 1]},
                "active_elements": ["金"],
                "favored_tails": [6, 7],
                "tail_weights": [TailWeightItem(tail=6, weight=0.7)],
            },
            summary=RecommendationSummary(
                front_sum=15,
                back_sum=13,
                front_span=4,
                back_span=1,
                front_odd_even="3:2",
                back_odd_even="1:1",
                favored_tails=[1, 2],
                explanation="test summary",
            ),
            ai_analysis=AIAnalysis(engine="local", overview="ok", key_factors=["a"], final_advice="go"),
            final_schemes=[
                FinalScheme(
                    label="A",
                    confidence=0.9,
                    strategy="smart",
                    front_numbers=[1, 2, 3, 4, 5],
                    back_numbers=[6, 7],
                    rationale="match",
                ),
                FinalScheme(
                    label="B",
                    confidence=0.5,
                    strategy="smart",
                    front_numbers=[8, 9, 10, 11, 12],
                    back_numbers=[1, 2],
                    rationale="miss",
                ),
            ],
            tuning_profile="profile",
            issue_confidence=0.7,
            calibrated_confidence=0.68,
            applied_threshold=0.6,
            should_observe=False,
            front_confidence=0.71,
            front_calibrated_confidence=0.69,
            front_gate=0.55,
            back_confidence=0.66,
            back_calibrated_confidence=0.62,
            back_gate=0.5,
            count_policy="fixed",
            decision_tier="A",
            deep_search_triggered=False,
            deep_search_reason=None,
            decision_reason="test",
        )

        saved = save_divination_run(
            response,
            target_issue="26054",
            requested_scheme_count=3,
            requested_strategy_mode="smart_balance",
            ai_enabled=False,
        )
        self.assertEqual(saved.target_issue, "26054")
        self.assertEqual(len(saved.schemes), 2)
        self.assertEqual(saved.schemes[0].evaluation.status, "won")
        self.assertEqual(saved.schemes[1].evaluation.status, "not_won")

        listed = list_divination_runs(limit=20)
        self.assertEqual(len(listed.items), 1)
        self.assertEqual(listed.stats.total_runs, 1)
        self.assertEqual(listed.stats.evaluated_runs, 1)
        self.assertEqual(listed.stats.hit_issue_count, 1)
        self.assertEqual(listed.stats.total_scheme_count, 2)
        self.assertEqual(listed.stats.won_scheme_count, 1)


if __name__ == "__main__":
    unittest.main()
