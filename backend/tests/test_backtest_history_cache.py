import unittest

from app.db import ensure_database
from app.services.backtest_service import (
    BACKTEST_HISTORY_RECENT_WINDOW,
    _build_history_context_cache,
    _window_model_schemes,
)
from app.services.meihua import build_history_feature_context
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


if __name__ == "__main__":
    unittest.main()
