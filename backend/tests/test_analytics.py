import unittest
from datetime import date

from app.models import LottoDraw
from app.services.analytics import build_analytics


class AnalyticsTests(unittest.TestCase):
    def test_build_analytics_matches_expected_counts_and_omissions(self) -> None:
        draws = [
            LottoDraw(
                issue="26003",
                draw_date=date(2026, 6, 3),
                front_numbers=[1, 2, 3, 4, 5],
                back_numbers=[1, 2],
            ),
            LottoDraw(
                issue="26002",
                draw_date=date(2026, 6, 1),
                front_numbers=[6, 7, 8, 9, 10],
                back_numbers=[3, 4],
            ),
            LottoDraw(
                issue="26001",
                draw_date=date(2026, 5, 30),
                front_numbers=[1, 11, 12, 13, 14],
                back_numbers=[1, 5],
            ),
        ]

        analytics = build_analytics(draws)
        front_frequency = {item.number: item.count for item in analytics.front_frequency}
        back_frequency = {item.number: item.count for item in analytics.back_frequency}
        front_omission = {item.number: item.omission for item in analytics.front_omission}
        back_omission = {item.number: item.omission for item in analytics.back_omission}

        self.assertEqual(analytics.total_draws, 3)
        self.assertEqual(front_frequency[1], 2)
        self.assertEqual(front_frequency[6], 1)
        self.assertEqual(front_frequency[15], 0)
        self.assertEqual(back_frequency[1], 2)
        self.assertEqual(back_frequency[4], 1)
        self.assertEqual(back_frequency[12], 0)
        self.assertEqual(front_omission[1], 0)
        self.assertEqual(front_omission[6], 1)
        self.assertEqual(front_omission[11], 2)
        self.assertEqual(front_omission[15], 3)
        self.assertEqual(back_omission[1], 0)
        self.assertEqual(back_omission[3], 1)
        self.assertEqual(back_omission[5], 2)
        self.assertEqual(back_omission[12], 3)
        self.assertEqual(analytics.odd_even.front_odd, 8)
        self.assertEqual(analytics.odd_even.front_even, 7)
        self.assertEqual(analytics.odd_even.back_odd, 4)
        self.assertEqual(analytics.odd_even.back_even, 2)


if __name__ == "__main__":
    unittest.main()
