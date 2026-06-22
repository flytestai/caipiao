import unittest
from datetime import date
from unittest.mock import patch

from app.models import LottoDraw, PrizeLevelItem
from app.services.repository import (
    _deserialize_numbers,
    _deserialize_prize_levels,
    _deserialize_prize_levels_cached,
    _draw_number_sets,
    _parse_iso_datetime,
    _promotion_rule_for_issue,
    evaluate_scheme_against_draw,
)


class RepositoryPrizeCacheTests(unittest.TestCase):
    def test_number_deserialize_cache_preserves_values(self) -> None:
        self.assertEqual(_deserialize_numbers("[1, 2, 3, 4, 5]"), [1, 2, 3, 4, 5])
        self.assertEqual(_deserialize_numbers("[6,7]"), [6, 7])

    def test_iso_datetime_cache_preserves_values(self) -> None:
        parsed = _parse_iso_datetime("2026-06-18T12:34:56+08:00")
        self.assertEqual(parsed.isoformat(), "2026-06-18T12:34:56+08:00")

    def test_prize_level_deserialize_cache_preserves_values(self) -> None:
        _deserialize_prize_levels_cached.cache_clear()
        before = _deserialize_prize_levels_cached.cache_info()

        first = _deserialize_prize_levels(
            '[{"prize_level":"一等奖","award_type":0,"stake_amount_format":"1000000"}]'
        )
        second = _deserialize_prize_levels(
            '[{"prize_level":"一等奖","award_type":0,"stake_amount_format":"1000000"}]'
        )
        after = _deserialize_prize_levels_cached.cache_info()

        self.assertEqual(first[0].prize_level, "一等奖")
        self.assertEqual(first[0].stake_amount_format, "1000000")
        self.assertEqual(second[0].prize_level, "一等奖")
        self.assertEqual(after.misses - before.misses, 1)
        self.assertEqual(after.hits - before.hits, 1)

    def test_evaluate_scheme_reuses_prize_amount_index_for_same_draw(self) -> None:
        draw = LottoDraw(
            issue="26054",
            draw_date=date(2026, 5, 18),
            front_numbers=[1, 2, 3, 4, 5],
            back_numbers=[6, 7],
            prize_level_list=[
                PrizeLevelItem(prize_level="一等奖", award_type=0, stake_amount_format="1000000"),
                PrizeLevelItem(prize_level="一等奖(追加)", award_type=0, stake_amount_format="800000"),
                PrizeLevelItem(prize_level="一等奖派奖", award_type=1, stake_amount_format="100000"),
            ],
        )

        with patch("app.services.repository._parse_amount", wraps=__import__("app.services.repository", fromlist=["_parse_amount"])._parse_amount) as parse_mock:
            first = evaluate_scheme_against_draw(
                draw,
                front_numbers=[1, 2, 3, 4, 5],
                back_numbers=[6, 7],
                is_additional=True,
                promotion_ticket_amount=20.0,
            )
            first_calls = parse_mock.call_count
            second = evaluate_scheme_against_draw(
                draw,
                front_numbers=[1, 2, 3, 4, 5],
                back_numbers=[6, 7],
                is_additional=True,
                promotion_ticket_amount=20.0,
            )

        self.assertEqual(first.prize_amount, second.prize_amount)
        self.assertEqual(first.additional_prize_amount, second.additional_prize_amount)
        self.assertEqual(parse_mock.call_count, first_calls)

    def test_draw_number_sets_are_cached_per_draw(self) -> None:
        draw = LottoDraw(
            issue="26054",
            draw_date=date(2026, 5, 18),
            front_numbers=[1, 2, 3, 4, 5],
            back_numbers=[6, 7],
            prize_level_list=[],
        )

        first = _draw_number_sets(draw)
        second = _draw_number_sets(draw)

        self.assertIs(first, second)

    def test_promotion_rule_lookup_is_lru_cached(self) -> None:
        _promotion_rule_for_issue.cache_clear()
        before = _promotion_rule_for_issue.cache_info()
        first = _promotion_rule_for_issue("26054")
        second = _promotion_rule_for_issue("26054")
        after = _promotion_rule_for_issue.cache_info()

        self.assertEqual(first, second)
        self.assertEqual(after.misses - before.misses, 1)
        self.assertEqual(after.hits - before.hits, 1)


if __name__ == "__main__":
    unittest.main()
