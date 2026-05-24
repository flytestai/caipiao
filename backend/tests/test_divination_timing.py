import unittest
from datetime import date, datetime

from app.models import LottoDraw
from app.services.meihua import _seed_from_request, generate_divination
from app.services.repository import _build_next_draw_info


class DivinationTimingTests(unittest.TestCase):
    def test_seed_includes_issue_divination_and_draw_time(self) -> None:
        seed = _seed_from_request(
            "26054",
            "2026-05-17T09:18",
            target_draw_datetime=datetime(2026, 5, 18, 21, 30),
        )

        self.assertEqual(seed.mode, "issue")
        self.assertEqual(seed.seed_value, "26054")
        self.assertEqual(
            seed.numbers,
            [2, 6, 0, 5, 4, 2026, 5, 17, 9, 18, 2026, 5, 18, 21, 30],
        )
        self.assertEqual(seed.divination_datetime, datetime(2026, 5, 17, 9, 18))
        self.assertEqual(seed.target_draw_datetime, datetime(2026, 5, 18, 21, 30))

    def test_generate_divination_exposes_timing_basis(self) -> None:
        history = [
            LottoDraw(
                issue="26053",
                draw_date=date(2026, 5, 16),
                front_numbers=[2, 9, 14, 20, 31],
                back_numbers=[5, 9],
            )
        ]

        result = generate_divination(history, issue="26054", timestamp="2026-05-17T09:18")

        self.assertEqual(result.divination_datetime, "2026-05-17 09:18")
        self.assertEqual(result.target_draw_datetime, "2026-05-18 21:30")
        self.assertIn("本次起卦取推算时点 2026-05-17 09:18，应期开奖时点取 2026-05-18 21:30", result.summary.explanation)

    def test_next_draw_info_uses_2130(self) -> None:
        next_issue, next_draw_datetime = _build_next_draw_info("26053", date(2026, 5, 16))

        self.assertEqual(next_issue, "26054")
        self.assertIsNotNone(next_draw_datetime)
        assert next_draw_datetime is not None
        self.assertEqual(next_draw_datetime.isoformat(timespec="minutes"), "2026-05-18T21:30+08:00")


if __name__ == "__main__":
    unittest.main()
