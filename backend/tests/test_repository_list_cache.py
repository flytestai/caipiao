import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import app.db as db_module
from app.db import ensure_database
from app.models import (
    AIAnalysis,
    DivinationResponse,
    FinalScheme,
    ManualDrawResultUpsertRequest,
    RecommendationSummary,
    SavedSchemeCreateRequest,
    TailWeightItem,
)
import app.services.repository as repository


def _build_divination_response(issue: str) -> DivinationResponse:
    return DivinationResponse(
        seed_mode="issue",
        seed_value=issue,
        divination_datetime="2026-06-18 10:00",
        target_draw_datetime="2026-06-18 21:30",
        strategy_mode="smart_balance",
        moving_line=1,
        main_hexagram={"code": "1", "name": "乾", "upper_trigram": "乾", "lower_trigram": "乾", "element": "金", "lines": [1, 1, 1, 1, 1, 1]},
        mutual_hexagram={"code": "43", "name": "夬", "upper_trigram": "乾", "lower_trigram": "兑", "element": "金", "lines": [1, 1, 1, 1, 1, 0]},
        changed_hexagram={"code": "14", "name": "大有", "upper_trigram": "离", "lower_trigram": "乾", "element": "火", "lines": [1, 1, 1, 1, 0, 1]},
        active_elements=["金"],
        favored_tails=[1, 2],
        tail_weights=[TailWeightItem(tail=1, weight=0.7)],
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
            "tail_weights": [TailWeightItem(tail=1, weight=0.7)],
        },
        back_signal={
            "zone": "back",
            "main_hexagram": {"code": "1", "name": "乾", "upper_trigram": "乾", "lower_trigram": "乾", "element": "金", "lines": [1, 1, 1, 1, 1, 1]},
            "mutual_hexagram": {"code": "43", "name": "夬", "upper_trigram": "乾", "lower_trigram": "兑", "element": "金", "lines": [1, 1, 1, 1, 1, 0]},
            "changed_hexagram": {"code": "14", "name": "大有", "upper_trigram": "离", "lower_trigram": "乾", "element": "火", "lines": [1, 1, 1, 1, 0, 1]},
            "active_elements": ["金"],
            "favored_tails": [6, 7],
            "tail_weights": [TailWeightItem(tail=6, weight=0.6)],
        },
        summary=RecommendationSummary(
            front_sum=15,
            back_sum=13,
            front_span=4,
            back_span=1,
            front_odd_even="3:2",
            back_odd_even="1:1",
            favored_tails=[1, 2],
            explanation="cache test",
        ),
        ai_analysis=AIAnalysis(engine="local", overview="ok", key_factors=["a"], final_advice="go"),
        final_schemes=[
            FinalScheme(
                label="A",
                confidence=0.9,
                strategy="smart",
                front_numbers=[1, 2, 3, 4, 5],
                back_numbers=[6, 7],
                rationale="cache",
            )
        ],
    )


class RepositoryListCacheTests(unittest.TestCase):
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

    def setUp(self) -> None:
        repository._invalidate_cached_list_responses()
        repository._invalidate_history_query_caches()
        repository._invalidate_sync_status_cache()
        with db_module.get_connection() as conn:
            conn.execute("DELETE FROM divination_run_schemes")
            conn.execute("DELETE FROM divination_runs")
            conn.execute("DELETE FROM saved_schemes")
            conn.execute("DELETE FROM lotto_draws")
            conn.execute("DELETE FROM sync_meta")
            conn.commit()

    def test_list_saved_schemes_uses_short_ttl_cache(self) -> None:
        payload = SavedSchemeCreateRequest.model_validate(
            {
                "target_issue": "26068",
                "seed_mode": "issue",
                "seed_value": "26068",
                "moving_line": 1,
                "ai_engine": "local",
                "scheme": {
                    "label": "A",
                    "confidence": 0.8,
                    "strategy": "smart",
                    "front_numbers": [1, 2, 3, 4, 5],
                    "back_numbers": [6, 7],
                    "rationale": "cache",
                },
                "multiple": 1,
                "is_additional": False,
            }
        )
        repository.save_scheme(payload)

        with patch("app.services.repository.get_effective_draws_by_issues", wraps=repository.get_effective_draws_by_issues) as fetch_mock:
            first = repository.list_saved_schemes(limit=20)
            second = repository.list_saved_schemes(limit=20)

        self.assertEqual(len(first.items), 1)
        self.assertIs(first, second)
        self.assertEqual(fetch_mock.call_count, 1)

    def test_save_scheme_invalidates_saved_scheme_cache(self) -> None:
        first_payload = SavedSchemeCreateRequest.model_validate(
            {
                "target_issue": "26068",
                "seed_mode": "issue",
                "seed_value": "26068",
                "moving_line": 1,
                "ai_engine": "local",
                "scheme": {
                    "label": "A",
                    "confidence": 0.8,
                    "strategy": "smart",
                    "front_numbers": [1, 2, 3, 4, 5],
                    "back_numbers": [6, 7],
                    "rationale": "cache",
                },
                "multiple": 1,
                "is_additional": False,
            }
        )
        second_payload = SavedSchemeCreateRequest.model_validate(
            {
                "target_issue": "26068",
                "seed_mode": "issue",
                "seed_value": "26068",
                "moving_line": 1,
                "ai_engine": "local",
                "scheme": {
                    "label": "B",
                    "confidence": 0.7,
                    "strategy": "smart",
                    "front_numbers": [8, 9, 10, 11, 12],
                    "back_numbers": [1, 2],
                    "rationale": "cache2",
                },
                "multiple": 1,
                "is_additional": False,
            }
        )
        repository.save_scheme(first_payload)
        first = repository.list_saved_schemes(limit=20)
        repository.save_scheme(second_payload)
        second = repository.list_saved_schemes(limit=20)

        self.assertEqual(len(first.items), 1)
        self.assertEqual(len(second.items), 2)
        self.assertIsNot(first, second)

    def test_list_divination_runs_uses_short_ttl_cache(self) -> None:
        repository.save_divination_run(_build_divination_response("26068"), target_issue="26068")

        with patch("app.services.repository.get_effective_draws_by_issues", wraps=repository.get_effective_draws_by_issues) as fetch_mock:
            first = repository.list_divination_runs(limit=20)
            second = repository.list_divination_runs(limit=20)

        self.assertEqual(len(first.items), 1)
        self.assertIs(first, second)
        self.assertEqual(fetch_mock.call_count, 1)

    def test_save_divination_run_invalidates_run_cache(self) -> None:
        repository.save_divination_run(_build_divination_response("26068"), target_issue="26068")
        first = repository.list_divination_runs(limit=20)
        repository.save_divination_run(_build_divination_response("26069"), target_issue="26069")
        second = repository.list_divination_runs(limit=20)

        self.assertEqual(len(first.items), 1)
        self.assertEqual(len(second.items), 2)
        self.assertIsNot(first, second)

    def test_upsert_manual_draw_result_returns_inserted_and_updated_values(self) -> None:
        first = repository.upsert_manual_draw_result(
            "26068",
            ManualDrawResultUpsertRequest(
                draw_date=date(2026, 6, 18),
                front_numbers=[1, 2, 3, 4, 5],
                back_numbers=[6, 7],
                high_pool=False,
            ),
        )
        second = repository.upsert_manual_draw_result(
            "26068",
            ManualDrawResultUpsertRequest(
                draw_date=date(2026, 6, 19),
                front_numbers=[8, 9, 10, 11, 12],
                back_numbers=[1, 2],
                high_pool=True,
            ),
        )

        self.assertEqual(first.issue, "26068")
        self.assertEqual(first.draw_date, date(2026, 6, 18))
        self.assertFalse(first.high_pool)
        self.assertEqual(second.issue, "26068")
        self.assertEqual(second.draw_date, date(2026, 6, 19))
        self.assertEqual(second.front_numbers, [8, 9, 10, 11, 12])
        self.assertEqual(second.back_numbers, [1, 2])
        self.assertTrue(second.high_pool)
        self.assertEqual(first.created_at, second.created_at)
        self.assertGreaterEqual(second.updated_at, first.updated_at)

    def test_get_history_uses_short_ttl_cache(self) -> None:
        repository.upsert_draws(
            [
                repository.LottoDraw(
                    issue="26068",
                    draw_date=date(2026, 6, 18),
                    front_numbers=[1, 2, 3, 4, 5],
                    back_numbers=[6, 7],
                    raw_result="01 02 03 04 05 06 07",
                    prize_level_list=[],
                )
            ]
        )

        with patch("app.services.repository.get_connection", wraps=db_module.get_connection) as conn_mock:
            first = repository.get_history(limit=20)
            second = repository.get_history(limit=20)

        self.assertEqual(len(first), 1)
        self.assertIs(first, second)
        self.assertEqual(conn_mock.call_count, 1)

    def test_save_schemes_batch_prefetches_existing_ids_once_and_reuses_row_within_batch(self) -> None:
        first_payload = SavedSchemeCreateRequest.model_validate(
            {
                "target_issue": "26068",
                "seed_mode": "issue",
                "seed_value": "26068",
                "moving_line": 1,
                "ai_engine": "local",
                "scheme": {
                    "label": "A",
                    "confidence": 0.8,
                    "strategy": "smart",
                    "front_numbers": [1, 2, 3, 4, 5],
                    "back_numbers": [6, 7],
                    "rationale": "cache",
                },
                "multiple": 1,
                "is_additional": False,
            }
        )
        second_payload = SavedSchemeCreateRequest.model_validate(
            {
                "target_issue": "26068",
                "seed_mode": "issue",
                "seed_value": "26068",
                "moving_line": 1,
                "ai_engine": "local",
                "scheme": {
                    "label": "B",
                    "confidence": 0.8,
                    "strategy": "smart",
                    "front_numbers": [1, 2, 3, 4, 5],
                    "back_numbers": [6, 7],
                    "rationale": "cache2",
                },
                "multiple": 2,
                "is_additional": True,
            }
        )

        with patch.object(
            repository,
            "_load_existing_saved_scheme_id_map",
            wraps=repository._load_existing_saved_scheme_id_map,
        ) as load_mock:
            items = repository.save_schemes([first_payload, second_payload])

        self.assertEqual(load_mock.call_count, 1)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].id, items[1].id)
        listed = repository.list_saved_schemes(limit=20)
        self.assertEqual(len(listed.items), 1)
        self.assertEqual(listed.items[0].label, "B")
        self.assertEqual(listed.items[0].multiple, 2)
        self.assertTrue(listed.items[0].is_additional)


if __name__ == "__main__":
    unittest.main()
