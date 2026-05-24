import unittest
from datetime import date

from app.models import LottoDraw, PrizeLevelItem
from app.services.repository import evaluate_scheme_against_draw


class SavedSchemePromotionTests(unittest.TestCase):
    def test_eligible_saved_scheme_includes_official_promotion_amount(self) -> None:
        draw = LottoDraw(
            issue="26050",
            draw_date=date(2026, 5, 9),
            front_numbers=[1, 2, 3, 4, 5],
            back_numbers=[6, 7],
            prize_level_list=[
                PrizeLevelItem(prize_level="三等奖", award_type=0, stake_amount_format="5000"),
                PrizeLevelItem(prize_level="三等奖派奖", award_type=1, stake_amount_format="2500"),
            ],
        )

        evaluation = evaluate_scheme_against_draw(
            draw,
            front_numbers=[1, 2, 3, 4, 5],
            back_numbers=[8, 9],
            multiple=9,
            is_additional=False,
        )

        self.assertEqual(evaluation.prize_level, "三等奖")
        self.assertTrue(evaluation.promotion_eligible)
        self.assertEqual(evaluation.base_prize_amount, 45000.0)
        self.assertEqual(evaluation.bonus_prize_amount, 22500.0)
        self.assertEqual(evaluation.prize_amount, 67500.0)

    def test_additional_first_prize_uses_official_additional_amount(self) -> None:
        draw = LottoDraw(
            issue="26050",
            draw_date=date(2026, 5, 9),
            front_numbers=[1, 2, 3, 4, 5],
            back_numbers=[6, 7],
            prize_level_list=[
                PrizeLevelItem(prize_level="一等奖", award_type=0, stake_amount_format="8052622"),
                PrizeLevelItem(prize_level="一等奖(追加)", award_type=0, stake_amount_format="6442097"),
            ],
        )

        evaluation = evaluate_scheme_against_draw(
            draw,
            front_numbers=[1, 2, 3, 4, 5],
            back_numbers=[6, 7],
            multiple=1,
            is_additional=True,
        )

        self.assertEqual(evaluation.prize_level, "一等奖")
        self.assertEqual(evaluation.base_prize_amount, 8052622.0)
        self.assertEqual(evaluation.additional_prize_amount, 6442097.0)
        self.assertEqual(evaluation.prize_amount, 14494719.0)
        self.assertFalse(evaluation.promotion_eligible)


if __name__ == "__main__":
    unittest.main()
