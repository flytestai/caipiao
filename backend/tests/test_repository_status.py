import unittest
from datetime import date
from unittest.mock import patch

import app.services.repository as repository
from app.services.repository import get_sync_status


class RepositoryStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        repository._invalidate_sync_status_cache()

    def test_get_sync_status_uses_latest_issue_and_total_count(self) -> None:
        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query, params=()):
                self.last_query = query
                self.last_params = params
                return self

            def fetchone(self):
                return {
                    "issue": "26067",
                    "draw_date": "2026-06-18",
                    "total_draws": 3210,
                }

        fake_conn = FakeConnection()
        with (
            patch("app.services.repository.get_connection", return_value=fake_conn),
            patch("app.services.repository.get_meta", return_value="2026-06-18T12:00:00+08:00"),
        ):
            status = get_sync_status()

        self.assertEqual(status.total_draws, 3210)
        self.assertEqual(status.latest_issue, "26067")
        self.assertEqual(status.latest_draw_date, date(2026, 6, 18))
        self.assertEqual(status.next_issue, "26068")

    def test_get_sync_status_uses_short_ttl_cache(self) -> None:
        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query, params=()):
                self.last_query = query
                self.last_params = params
                return self

            def fetchone(self):
                return {
                    "issue": "26067",
                    "draw_date": "2026-06-18",
                    "total_draws": 3210,
                }

        fake_conn = FakeConnection()
        with (
            patch("app.services.repository.get_connection", return_value=fake_conn) as conn_mock,
            patch("app.services.repository.get_meta", return_value="2026-06-18T12:00:00+08:00") as meta_mock,
        ):
            first = get_sync_status()
            second = get_sync_status()

        self.assertIs(first, second)
        self.assertEqual(conn_mock.call_count, 1)
        self.assertEqual(meta_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
