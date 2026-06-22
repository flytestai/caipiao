import tempfile
import unittest
from datetime import date
from pathlib import Path

import app.db as db_module
from app.db import ensure_database
from app.models import LottoDraw, PrizeLevelItem, SavedSchemeManualCreateRequest
from app.services.repository import list_saved_schemes, save_manual_scheme, upsert_draws


class ManualIssuePromotionBatchTests(unittest.TestCase):
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

    def test_manual_issue_total_amount_triggers_promotion(self) -> None:
        upsert_draws(
            [
                LottoDraw(
                    issue="26053",
                    draw_date=date(2026, 5, 16),
                    front_numbers=[2, 9, 14, 20, 31],
                    back_numbers=[5, 9],
                    prize_level_list=[
                        PrizeLevelItem(prize_level="\u516d\u7b49\u5956", award_type=0, stake_amount_format="15"),
                        PrizeLevelItem(prize_level="\u516d\u7b49\u5956\u6d3e\u5956", award_type=1, stake_amount_format="7.5"),
                        PrizeLevelItem(prize_level="\u4e03\u7b49\u5956", award_type=0, stake_amount_format="5"),
                        PrizeLevelItem(prize_level="\u4e03\u7b49\u5956\u6d3e\u5956", award_type=1, stake_amount_format="5"),
                    ],
                )
            ]
        )

        entries = [
            ([8, 16, 19, 24, 31], [4, 9]),
            ([9, 14, 16, 30, 31], [5, 10]),
            ([4, 5, 16, 18, 31], [3, 8]),
            ([8, 12, 24, 25, 31], [6, 7]),
            ([8, 14, 16, 29, 31], [1, 5]),
        ]
        for front_numbers, back_numbers in entries:
            save_manual_scheme(
                SavedSchemeManualCreateRequest(
                    target_issue="26053",
                    front_numbers=front_numbers,
                    back_numbers=back_numbers,
                    multiple=3,
                    is_additional=False,
                )
            )

        saved = list_saved_schemes(limit=20)
        winning_item = next(
            item
            for item in saved.items
            if item.front_numbers == [9, 14, 16, 30, 31] and item.back_numbers == [5, 10]
        )

        self.assertEqual(winning_item.evaluation.cost_amount, 6.0)
        self.assertTrue(winning_item.evaluation.promotion_eligible)
        self.assertEqual(winning_item.evaluation.base_prize_amount, 45.0)
        self.assertEqual(winning_item.evaluation.bonus_prize_amount, 22.5)
        self.assertEqual(winning_item.evaluation.prize_amount, 67.5)


if __name__ == "__main__":
    unittest.main()
