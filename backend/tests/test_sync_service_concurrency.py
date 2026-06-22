import unittest
from datetime import date
from unittest.mock import patch

from app.models import LottoDraw
from app.services.official_source import fetch_history_pages
from app.services.sync_service import sync_official_history


class SyncServiceConcurrencyTests(unittest.TestCase):
    def _draw_for_page(self, page_no: int) -> LottoDraw:
        return LottoDraw(
            issue=f"26{page_no:03d}",
            draw_date=date(2026, 1, min(page_no, 28)),
            front_numbers=[1, 2, 3, 4, 5],
            back_numbers=[1, 2],
            raw_result="01 02 03 04 05 01 02",
            pool_balance_afterdraw=None,
            prize_level_list=[],
        )

    def test_fetch_history_pages_preserves_input_page_order(self) -> None:
        def fake_fetch_history_page(*, page_no: int, page_size: int):
            return [self._draw_for_page(page_no)], 5

        with patch("app.services.official_source.fetch_history_page", side_effect=fake_fetch_history_page):
            draws = fetch_history_pages([3, 2, 5])

        self.assertEqual([item.issue for item in draws], ["26003", "26002", "26005"])

    def test_sync_official_history_uses_batched_page_fetch_for_full_refresh(self) -> None:
        first_page_draws = [self._draw_for_page(1)]
        extra_draws = [self._draw_for_page(2), self._draw_for_page(3), self._draw_for_page(4)]

        with (
            patch("app.services.sync_service.fetch_history_page", return_value=(first_page_draws, 4)),
            patch("app.services.sync_service.fetch_history_pages", return_value=extra_draws) as fetch_pages_mock,
            patch("app.services.sync_service.upsert_draws", return_value=(0, 0)),
            patch("app.services.sync_service.set_meta", return_value=None),
            patch("app.services.sync_service.get_sync_status", return_value=type("SyncStatusStub", (), {"total_draws": 4, "latest_issue": "26004"})()),
        ):
            result = sync_official_history(full_refresh=True)

        fetch_pages_mock.assert_called_once_with([2, 3, 4])
        self.assertEqual(result.fetched_pages, 4)
        self.assertEqual(result.latest_issue, "26004")

    def test_sync_official_history_uses_batched_page_fetch_for_recent_sync(self) -> None:
        first_page_draws = [self._draw_for_page(1)]
        extra_draws = [self._draw_for_page(2), self._draw_for_page(3)]

        with (
            patch("app.services.sync_service.fetch_history_page", return_value=(first_page_draws, 8)),
            patch("app.services.sync_service.fetch_history_pages", return_value=extra_draws) as fetch_pages_mock,
            patch("app.services.sync_service.upsert_draws", return_value=(0, 0)),
            patch("app.services.sync_service.set_meta", return_value=None),
            patch("app.services.sync_service.get_sync_status", return_value=type("SyncStatusStub", (), {"total_draws": 8, "latest_issue": "26008"})()),
        ):
            result = sync_official_history(full_refresh=False)

        fetch_pages_mock.assert_called_once_with([2, 3])
        self.assertEqual(result.fetched_pages, 3)
        self.assertEqual(result.total_in_db, 8)


if __name__ == "__main__":
    unittest.main()
