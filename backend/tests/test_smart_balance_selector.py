import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.services.backtest_service as backtest_service
from app.services.backtest_service import (
    _active_live_smart_balance_candidate_profiles,
    _candidate_result_summary,
    _candidate_result_summary_from_issue_values,
    _ensure_live_smart_balance_candidate_results,
    _load_smart_balance_candidate_results,
    _scheme_count_for_issue,
    _smart_balance_candidate_profiles,
    _smart_balance_attack_issue_score,
    _smart_balance_issue_score,
    _select_full_history_profile_for_mode,
    _select_smart_balance_candidate_name_from_scores,
)


class SmartBalanceSelectorTests(unittest.TestCase):
    def test_candidate_pool_includes_high_tier_profiles(self) -> None:
        names = {profile_name for profile_name, *_ in _smart_balance_candidate_profiles()}

        self.assertIn("multi_cover:frequency_revert+candidate_focus_jackpot_floor_guarded", names)
        self.assertIn("multi_cover:frequency_revert+three_pack_hybrid_core", names)
        self.assertIn("multi_cover:frequency_revert+ultra_core_jackpot", names)

    def test_live_candidate_pool_skips_empty_profiles(self) -> None:
        candidate_results = {profile_name: {} for profile_name, *_ in _smart_balance_candidate_profiles()}
        candidate_results["multi_cover:balanced+balanced_combo"] = {"26060": {"won_count": 1}}

        active_names = {
            profile_name for profile_name, *_ in _active_live_smart_balance_candidate_profiles(candidate_results)
        }

        self.assertEqual(active_names, {"multi_cover:balanced+balanced_combo"})

    def test_issue_score_rewards_higher_prize_levels(self) -> None:
        seventh = _smart_balance_issue_score(
            {
                "won_count": 1,
                "total_prize_amount": 5.0,
                "prize_level_hits": {"level7": 1},
            }
        )
        sixth = _smart_balance_issue_score(
            {
                "won_count": 1,
                "total_prize_amount": 15.0,
                "prize_level_hits": {"level6": 1},
            }
        )
        fourth = _smart_balance_issue_score(
            {
                "won_count": 1,
                "total_prize_amount": 300.0,
                "prize_level_hits": {"level4": 1},
            }
        )

        self.assertLess(seventh, sixth)
        self.assertLess(sixth, fourth)

    def test_issue_score_rewards_high_tier_proxy_signals_even_without_cash_win(self) -> None:
        baseline = _smart_balance_issue_score(
            {
                "won_count": 0,
                "total_prize_amount": 0.0,
                "prize_level_hits": {},
                "front_best_match_count": 3,
                "back_best_match_count": 1,
                "issue_power_score": 0.18,
            }
        )
        proxy_hit = _smart_balance_issue_score(
            {
                "won_count": 0,
                "total_prize_amount": 0.0,
                "prize_level_hits": {},
                "top4_hit": True,
                "front_5_hit": True,
                "five_plus_one_hit": True,
                "issue_power_score": 0.72,
                "front_best_match_count": 5,
                "back_best_match_count": 1,
            }
        )

        self.assertGreater(proxy_hit, baseline)

    def test_attack_issue_score_is_more_sensitive_to_high_tier_proxy_signals(self) -> None:
        low_tier_hit = {
            "won_count": 1,
            "total_prize_amount": 5.0,
            "prize_level_hits": {"level7": 1},
            "issue_power_score": 0.16,
        }
        proxy_hit = {
            "won_count": 0,
            "total_prize_amount": 0.0,
            "prize_level_hits": {},
            "top4_hit": True,
            "front_5_hit": True,
            "five_plus_one_hit": True,
            "issue_power_score": 0.74,
            "front_best_match_count": 5,
            "back_best_match_count": 1,
        }

        self.assertGreater(_smart_balance_attack_issue_score(proxy_hit), _smart_balance_attack_issue_score(low_tier_hit))

    def test_candidate_summary_prefers_profile_with_real_mid_high_tier_hits(self) -> None:
        low_tier_only = _candidate_result_summary(
            {
                "26001": {
                    "scheme_count": 3,
                    "won_count": 1,
                    "total_prize_amount": 5.0,
                    "prize_level_hits": {"level7": 1},
                },
                "26002": {
                    "scheme_count": 3,
                    "won_count": 1,
                    "total_prize_amount": 5.0,
                    "prize_level_hits": {"level7": 1},
                },
                "26003": {
                    "scheme_count": 3,
                    "won_count": 1,
                    "total_prize_amount": 5.0,
                    "prize_level_hits": {"level7": 1},
                },
            }
        )
        mid_high_tier = _candidate_result_summary(
            {
                "26001": {
                    "scheme_count": 3,
                    "won_count": 1,
                    "total_prize_amount": 300.0,
                    "prize_level_hits": {"level4": 1},
                    "top4_hit": True,
                    "four_plus_two_hit": True,
                    "back_2plus_hit": True,
                    "front_best_match_count": 4,
                    "back_best_match_count": 2,
                },
                "26002": {
                    "scheme_count": 3,
                    "won_count": 0,
                    "total_prize_amount": 0.0,
                    "prize_level_hits": {},
                },
                "26003": {
                    "scheme_count": 3,
                    "won_count": 0,
                    "total_prize_amount": 0.0,
                    "prize_level_hits": {},
                },
            }
        )

        self.assertGreater(mid_high_tier["score"], low_tier_only["score"])
        self.assertGreater(mid_high_tier["high_tier_proxy_score"], low_tier_only["high_tier_proxy_score"])

    def test_candidate_result_summary_iterable_matches_dict_summary(self) -> None:
        profile_results = {
            "26001": {
                "scheme_count": 3,
                "won_count": 1,
                "total_prize_amount": 5.0,
                "prize_level_hits": {"level7": 1},
            },
            "26002": {
                "scheme_count": 3,
                "won_count": 0,
                "total_prize_amount": 0.0,
                "prize_level_hits": {},
                "top4_hit": True,
            },
        }

        self.assertEqual(
            _candidate_result_summary(profile_results),
            _candidate_result_summary_from_issue_values(profile_results.values()),
        )

    def test_live_selector_can_switch_to_high_tier_profile(self) -> None:
        history = [SimpleNamespace(issue=f"2600{i}") for i in range(1, 4)]
        candidate_results = {}
        for profile_name, *_ in _smart_balance_candidate_profiles():
            candidate_results[profile_name] = {}
            for draw in history:
                candidate_results[profile_name][draw.issue] = {
                    "won_count": 1,
                    "total_prize_amount": 5.0,
                    "prize_level_hits": {"level7": 1},
                }

        target_profile = "multi_cover:frequency_revert+ultra_core_jackpot"
        candidate_results[target_profile]["26003"] = {
            "won_count": 1,
            "total_prize_amount": 300.0,
            "prize_level_hits": {"level4": 1},
        }

        chosen_profile, _reason = _select_smart_balance_candidate_name_from_scores(history, candidate_results)
        self.assertEqual(chosen_profile, target_profile)

    def test_live_selector_can_choose_proxy_attack_profile_without_cash_win(self) -> None:
        history = [SimpleNamespace(issue=f"2600{i}") for i in range(1, 5)]
        candidate_results = {}
        for profile_name, *_ in _smart_balance_candidate_profiles():
            candidate_results[profile_name] = {}
            for draw in history:
                candidate_results[profile_name][draw.issue] = {
                    "won_count": 1,
                    "total_prize_amount": 5.0,
                    "prize_level_hits": {"level7": 1},
                    "issue_power_score": 0.14,
                }

        target_profile = "multi_cover:frequency_revert+ultra_core_jackpot"
        candidate_results[target_profile]["26004"] = {
            "won_count": 0,
            "total_prize_amount": 0.0,
            "prize_level_hits": {},
            "top4_hit": True,
            "front_5_hit": True,
            "five_plus_one_hit": True,
            "issue_power_score": 0.82,
            "front_best_match_count": 5,
            "back_best_match_count": 1,
        }

        chosen_profile, reason = _select_smart_balance_candidate_name_from_scores(history, candidate_results)
        self.assertEqual(chosen_profile, target_profile)
        self.assertTrue(reason)

    def test_live_selector_uses_only_latest_common_issues(self) -> None:
        history = [SimpleNamespace(issue=f"2600{i}") for i in range(1, 5)]
        profile_a = "multi_cover:profile_a"
        profile_b = "multi_cover:profile_b"
        candidate_results = {
            profile_a: {
                "26001": {"won_count": 1, "total_prize_amount": 300.0, "prize_level_hits": {"level4": 1}},
                "26002": {"won_count": 0, "total_prize_amount": 0.0, "prize_level_hits": {}},
                "26003": {"won_count": 0, "total_prize_amount": 0.0, "prize_level_hits": {}},
                "26004": {"won_count": 0, "total_prize_amount": 0.0, "prize_level_hits": {}},
            },
            profile_b: {
                "26002": {"won_count": 1, "total_prize_amount": 5.0, "prize_level_hits": {"level7": 1}},
                "26003": {"won_count": 1, "total_prize_amount": 5.0, "prize_level_hits": {"level7": 1}},
                "26004": {"won_count": 1, "total_prize_amount": 300.0, "prize_level_hits": {"level4": 1}},
            },
        }

        with patch.object(
            backtest_service,
            "_smart_balance_candidate_profiles",
            return_value=[
                (profile_a, "multi_cover", "Profile A", {}, {}),
                (profile_b, "multi_cover", "Profile B", {}, {}),
            ],
        ):
            chosen_profile, reason = _select_smart_balance_candidate_name_from_scores(history, candidate_results)

        self.assertEqual(chosen_profile, profile_b)
        self.assertTrue(reason)

    def test_full_history_mode_selection_uses_only_common_issues(self) -> None:
        history = [SimpleNamespace(issue="26001"), SimpleNamespace(issue="26002"), SimpleNamespace(issue="26003")]
        profile_a = "multi_cover:profile_a"
        profile_b = "multi_cover:profile_b"
        candidate_results = {
            profile_a: {
                "26001": {"scheme_count": 3, "won_count": 0, "total_prize_amount": 0.0, "prize_level_hits": {}},
                "26002": {"scheme_count": 3, "won_count": 0, "total_prize_amount": 0.0, "prize_level_hits": {}},
                "26003": {"scheme_count": 3, "won_count": 1, "total_prize_amount": 300.0, "prize_level_hits": {"level4": 1}},
            },
            profile_b: {
                "26001": {"scheme_count": 3, "won_count": 1, "total_prize_amount": 5.0, "prize_level_hits": {"level7": 1}},
                "26002": {"scheme_count": 3, "won_count": 1, "total_prize_amount": 5.0, "prize_level_hits": {"level7": 1}},
            },
        }

        with (
            patch.object(backtest_service, "_load_smart_balance_candidate_results", return_value=candidate_results),
            patch.object(backtest_service, "_ensure_live_smart_balance_candidate_results"),
            patch.object(
                backtest_service,
                "_smart_balance_candidate_profiles",
                return_value=[
                    (profile_a, "multi_cover", "Profile A", {}, {}),
                    (profile_b, "multi_cover", "Profile B", {}, {}),
                ],
            ),
            patch.object(
                backtest_service,
                "_smart_balance_profile_from_candidate_name",
                side_effect=lambda candidate_name, selection_reason: SimpleNamespace(
                    profile_name=candidate_name,
                    selection_reason=selection_reason,
                ),
            ),
        ):
            selected = _select_full_history_profile_for_mode(
                history,
                "multi_cover",
                scheme_count=3,
                ticket_mode="basic",
            )

        self.assertIsNotNone(selected)
        self.assertEqual(selected.profile_name, profile_b)

    def test_live_priority_value_ladder_can_observe_low_margin_round(self) -> None:
        chosen_count = _scheme_count_for_issue(
            issue_confidence=0.238,
            threshold=0.232,
            max_scheme_count=3,
            strategy_mode="multi_cover",
            front_confidence=0.49,
            front_gate=0.55,
            back_confidence=0.44,
            back_gate=0.48,
            count_policy="live_priority_value_ladder",
        )

        self.assertEqual(chosen_count, 0)

    def test_live_priority_value_ladder_keeps_three_on_strong_margin(self) -> None:
        chosen_count = _scheme_count_for_issue(
            issue_confidence=0.326,
            threshold=0.236,
            max_scheme_count=3,
            strategy_mode="multi_cover",
            front_confidence=0.59,
            front_gate=0.55,
            back_confidence=0.52,
            back_gate=0.48,
            count_policy="live_priority_value_ladder",
        )

        self.assertEqual(chosen_count, 3)

    def test_candidate_summary_uses_proxy_signal_rates_from_issue_results(self) -> None:
        summary = _candidate_result_summary(
            {
                "26001": {
                    "scheme_count": 5,
                    "won_count": 0,
                    "total_prize_amount": 0.0,
                    "prize_level_hits": {},
                    "top4_hit": True,
                    "front_5_hit": True,
                    "five_plus_one_hit": True,
                    "issue_power_score": 0.66,
                },
                "26002": {
                    "scheme_count": 5,
                    "won_count": 0,
                    "total_prize_amount": 0.0,
                    "prize_level_hits": {},
                    "five_plus_two_hit": True,
                    "front_5_hit": True,
                    "issue_power_score": 0.88,
                },
            }
        )

        self.assertGreater(summary["high_tier_proxy_score"], 0.0)
        self.assertGreater(summary["top4_hit_rate"], 0.0)
        self.assertGreater(summary["five_plus_one_hit_rate"], 0.0)
        self.assertGreater(summary["five_plus_two_hit_rate"], 0.0)

    def test_live_backfill_does_not_compute_empty_obsolete_profiles(self) -> None:
        history = [SimpleNamespace(issue="26059"), SimpleNamespace(issue="26060")]
        candidate_results = {profile_name: {} for profile_name, *_ in _smart_balance_candidate_profiles()}
        for profile_name in (
            "multi_cover:balanced+balanced_combo",
            "multi_cover:frequency_revert+three_pack_low_tier_cover",
        ):
            candidate_results[profile_name] = {
                "26059": {"issue": "26059"},
                "26060": {"issue": "26060"},
            }

        history_context = SimpleNamespace(history_size=60)
        with (
            patch(
                "app.services.backtest_service._build_history_context_cache",
                return_value={draw.issue: ([draw], history_context) for draw in history},
            ),
            patch("app.services.backtest_service._evaluate_backtest_issue") as evaluate_mock,
        ):
            _ensure_live_smart_balance_candidate_results(history, candidate_results, scheme_count=3, ticket_mode="basic")

        evaluate_mock.assert_not_called()

    def test_live_backfill_only_computes_missing_pairs_and_fills_results(self) -> None:
        history = [SimpleNamespace(issue="26059"), SimpleNamespace(issue="26060")]
        default_profile = "multi_cover:balanced+balanced_combo"
        lowtier_profile = "multi_cover:frequency_revert+three_pack_low_tier_cover"
        candidate_results = {profile_name: {} for profile_name, *_ in _smart_balance_candidate_profiles()}
        candidate_results[default_profile] = {"26059": {"issue": "26059"}}
        candidate_results[lowtier_profile] = {"26060": {"issue": "26060"}}
        active_profiles = [profile_name for profile_name, *_ in _active_live_smart_balance_candidate_profiles(candidate_results)]

        history_context = SimpleNamespace(history_size=60)

        def evaluate_side_effect(index: int, **kwargs):
            target = kwargs["target"]
            return {
                "issue": str(target.issue),
                "draw_date": "2026-06-18",
                "issue_confidence": 0.2,
                "dynamic_threshold": 0.1,
                "front_confidence": 0.3,
                "back_confidence": 0.4,
                "deep_search_triggered": False,
                "deep_search_reason": "",
                "evaluation_summary": {
                    "won_count": 0,
                    "best_prize_level": None,
                    "best_prize_amount": 0.0,
                    "total_prize_amount": 0.0,
                    "winning_scheme_labels": [],
                    "prize_level_hits": {},
                    "prize_level_amounts": {},
                },
                "quality_signals": {
                    "top3_hit": False,
                    "top4_hit": False,
                    "front_4plus_hit": False,
                    "front_5_hit": False,
                    "five_plus_zero_hit": False,
                    "five_plus_one_hit": False,
                    "five_plus_two_hit": False,
                    "four_plus_two_hit": False,
                    "back_2plus_hit": False,
                    "front_best_match_count": 0,
                    "back_best_match_count": 0,
                    "issue_power_score": 0.0,
                },
                "coverage_metrics": SimpleNamespace(
                    front_pairwise_overlap_avg=0.0,
                    back_pairwise_overlap_avg=0.0,
                    back_pair_reuse_rate=0.0,
                    fresh_back_number_rate=0.0,
                ),
            }

        with (
            patch(
                "app.services.backtest_service._build_history_context_cache",
                return_value={draw.issue: ([draw], history_context) for draw in history},
            ),
            patch("app.services.backtest_service._evaluate_backtest_issue", side_effect=evaluate_side_effect) as evaluate_mock,
        ):
            _ensure_live_smart_balance_candidate_results(history, candidate_results, scheme_count=3, ticket_mode="basic")

        expected_calls = len(history) * len(active_profiles) - 2
        self.assertEqual(evaluate_mock.call_count, expected_calls)
        self.assertEqual(candidate_results[default_profile]["26059"]["issue"], "26059")
        self.assertEqual(candidate_results[default_profile]["26060"]["issue"], "26060")
        self.assertEqual(candidate_results[lowtier_profile]["26059"]["issue"], "26059")
        self.assertEqual(candidate_results[lowtier_profile]["26060"]["issue"], "26060")

    def test_candidate_report_loader_populates_multi_and_single_caches(self) -> None:
        default_profile = "multi_cover:balanced+balanced_combo"
        candidate_profile = "multi_cover:frequency_revert+candidate_focus"
        single_profile = "single_hit:balanced+balanced_combo"

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "default_multi.json").write_text(
                json.dumps(
                    {
                        "issues": [
                            {
                                "issue": "26060",
                                "draw_date": "2026-06-18",
                                "won_count": 1,
                                "total_prize_amount": 5.0,
                                "prize_level_hits": {"level7": 1},
                            }
                        ],
                        "issue_comparison": [
                            {
                                "issue": "26060",
                                "draw_date": "2026-06-18",
                                "secondary": {
                                    "won_count": 1,
                                    "best_prize_amount": 5.0,
                                    "best_prize_level": "level7",
                                    "prize_level_hits": {"level7": 1},
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "candidate_multi.json").write_text(
                json.dumps(
                    {
                        "issues": [
                            {
                                "issue": "26061",
                                "draw_date": "2026-06-19",
                                "won_count": 0,
                                "total_prize_amount": 0.0,
                                "prize_level_hits": {},
                                "top4_hit": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with (
                patch.object(backtest_service, "_smart_balance_report_cache_signature", None),
                patch.object(backtest_service, "_smart_balance_report_candidate_cache", None),
                patch.object(
                    backtest_service,
                    "_full_history_cache_candidate_report_files",
                    return_value={
                        "default_multi": "default_multi.json",
                        "candidate_multi": "candidate_multi.json",
                    },
                ),
                patch.object(
                    backtest_service,
                    "_smart_balance_report_file_path",
                    side_effect=lambda file_name: str(root / file_name),
                ),
            ):
                candidate_results = _load_smart_balance_candidate_results(scheme_count=3, ticket_mode="basic")

        self.assertEqual(candidate_results[default_profile]["26060"]["issue"], "26060")
        self.assertEqual(candidate_results[candidate_profile]["26061"]["issue"], "26061")
        self.assertEqual(candidate_results[single_profile]["26060"]["issue"], "26060")
        self.assertEqual(candidate_results[single_profile]["26060"]["won_count"], 1)

    def test_candidate_report_loader_uses_cached_json_report_helper(self) -> None:
        default_profile = "multi_cover:balanced+balanced_combo"
        candidate_report = {
            "issues": [
                {
                    "issue": "26060",
                    "draw_date": "2026-06-18",
                    "won_count": 1,
                    "total_prize_amount": 5.0,
                    "prize_level_hits": {"level7": 1},
                }
            ],
            "issue_comparison": [],
        }

        with (
            patch.object(backtest_service, "_smart_balance_report_cache_signature", None),
            patch.object(backtest_service, "_smart_balance_report_candidate_cache", None),
            patch.object(
                backtest_service,
                "_full_history_cache_candidate_report_files",
                return_value={"default_multi": "default_multi.json"},
            ),
            patch.object(
                backtest_service,
                "_load_or_build_smart_balance_candidate_cache",
                return_value=backtest_service._smart_balance_candidate_cache_payload_from_report(candidate_report),
            ) as load_mock,
        ):
            candidate_results = _load_smart_balance_candidate_results(scheme_count=3, ticket_mode="basic")

        self.assertEqual(candidate_results[default_profile]["26060"]["issue"], "26060")
        load_mock.assert_called_once_with("default_multi.json")

    def test_candidate_report_loader_prefers_sidecar_cache(self) -> None:
        default_profile = "multi_cover:balanced+balanced_combo"

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "default_multi.json").write_text("{}", encoding="utf-8")
            (root / backtest_service._smart_balance_candidate_cache_file_name("default_multi.json")).write_text(
                json.dumps(
                    {
                        "issue_map": {
                            "26060": {
                                "issue": "26060",
                                "draw_date": "2026-06-18",
                                "won_count": 1,
                                "total_prize_amount": 5.0,
                                "prize_level_hits": {},
                            }
                        },
                        "single_hit_issue_map": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with (
                patch.object(backtest_service, "_smart_balance_report_cache_signature", None),
                patch.object(backtest_service, "_smart_balance_report_candidate_cache", None),
                patch.object(
                    backtest_service,
                    "_full_history_cache_candidate_report_files",
                    return_value={"default_multi": "default_multi.json"},
                ),
                patch.object(
                    backtest_service,
                    "_smart_balance_report_file_path",
                    side_effect=lambda file_name: str(root / file_name),
                ),
                patch.object(backtest_service, "_load_json_report", side_effect=AssertionError("should not load full report")),
            ):
                candidate_results = _load_smart_balance_candidate_results(scheme_count=3, ticket_mode="basic")

        self.assertEqual(candidate_results[default_profile]["26060"]["issue"], "26060")

    def test_candidate_report_loader_builds_sidecar_cache_when_missing(self) -> None:
        default_profile = "multi_cover:balanced+balanced_combo"

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "default_multi.json").write_text(
                json.dumps(
                    {
                        "issues": [
                            {
                                "issue": "26060",
                                "draw_date": "2026-06-18",
                                "won_count": 1,
                                "total_prize_amount": 5.0,
                                "prize_level_hits": {},
                            }
                        ],
                        "issue_comparison": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with (
                patch.object(backtest_service, "_smart_balance_report_cache_signature", None),
                patch.object(backtest_service, "_smart_balance_report_candidate_cache", None),
                patch.object(
                    backtest_service,
                    "_full_history_cache_candidate_report_files",
                    return_value={"default_multi": "default_multi.json"},
                ),
                patch.object(
                    backtest_service,
                    "_smart_balance_report_file_path",
                    side_effect=lambda file_name: str(root / file_name),
                ),
            ):
                candidate_results = _load_smart_balance_candidate_results(scheme_count=3, ticket_mode="basic")

            sidecar_payload = json.loads(
                (root / backtest_service._smart_balance_candidate_cache_file_name("default_multi.json")).read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(candidate_results[default_profile]["26060"]["issue"], "26060")
        self.assertEqual(sidecar_payload["issue_map"]["26060"]["issue"], "26060")

    def test_candidate_report_loader_appends_tail_to_existing_sidecar_cache(self) -> None:
        default_profile = "multi_cover:balanced+balanced_combo"

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "default_multi.json").write_text(
                json.dumps(
                    {
                        "issues": [
                            {
                                "issue": "26060",
                                "draw_date": "2026-06-18",
                                "won_count": 1,
                                "total_prize_amount": 5.0,
                                "prize_level_hits": {},
                            },
                            {
                                "issue": "26061",
                                "draw_date": "2026-06-19",
                                "won_count": 0,
                                "total_prize_amount": 0.0,
                                "prize_level_hits": {},
                            },
                        ],
                        "issue_comparison": [
                            {
                                "issue": "26060",
                                "draw_date": "2026-06-18",
                                "secondary": {
                                    "won_count": 1,
                                    "best_prize_amount": 5.0,
                                    "best_prize_level": "level7",
                                    "prize_level_hits": {"level7": 1},
                                },
                            },
                            {
                                "issue": "26061",
                                "draw_date": "2026-06-19",
                                "secondary": {
                                    "won_count": 0,
                                    "best_prize_amount": 0.0,
                                    "best_prize_level": None,
                                    "prize_level_hits": {},
                                },
                            },
                        ],
                        "full_history_cache": {
                            "generated_at": "2026-06-22T01:30:00+08:00",
                            "latest_issue": "26061",
                            "scheme_count": 3,
                            "ticket_mode": "basic",
                            "profile": "default_multi",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / backtest_service._smart_balance_candidate_cache_file_name("default_multi.json")).write_text(
                json.dumps(
                    {
                        "issue_map": {
                            "26060": {
                                "issue": "26060",
                                "draw_date": "2026-06-18",
                                "won_count": 1,
                                "total_prize_amount": 5.0,
                                "prize_level_hits": {},
                            }
                        },
                        "single_hit_issue_map": {
                            "26060": {
                                "issue": "26060",
                                "draw_date": "2026-06-18",
                                "won_count": 1,
                                "total_prize_amount": 5.0,
                                "prize_level_hits": {"level7": 1},
                            }
                        },
                        "issue_count": 1,
                        "single_hit_issue_count": 1,
                        "latest_issue": "26060",
                        "full_history_cache": {
                            "generated_at": "2026-06-21T01:30:00+08:00",
                            "latest_issue": "26060",
                            "scheme_count": 3,
                            "ticket_mode": "basic",
                            "profile": "default_multi",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                patch.object(backtest_service, "_smart_balance_report_cache_signature", None),
                patch.object(backtest_service, "_smart_balance_report_candidate_cache", None),
                patch.object(
                    backtest_service,
                    "_full_history_cache_candidate_report_files",
                    return_value={"default_multi": "default_multi.json"},
                ),
                patch.object(
                    backtest_service,
                    "_smart_balance_report_file_path",
                    side_effect=lambda file_name: str(root / file_name),
                ),
                patch.object(
                    backtest_service,
                    "_json_dict_file_signature",
                    side_effect=lambda path, warning_label: (
                        ((2.0, 200), True)
                        if path.endswith("default_multi.json")
                        else (((1.0, 100), True) if path.endswith("default_multi.candidate-cache.json") else (None, False))
                    ),
                ),
            ):
                candidate_results = _load_smart_balance_candidate_results(scheme_count=3, ticket_mode="basic")

            sidecar_payload = json.loads(
                (root / backtest_service._smart_balance_candidate_cache_file_name("default_multi.json")).read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(candidate_results[default_profile]["26061"]["issue"], "26061")
        self.assertEqual(sidecar_payload["issue_count"], 2)
        self.assertEqual(sidecar_payload["single_hit_issue_count"], 2)
        self.assertEqual(sidecar_payload["latest_issue"], "26061")
        self.assertEqual(sidecar_payload["issue_map"]["26061"]["issue"], "26061")

    def test_candidate_report_loader_supports_legacy_list_sidecar_cache(self) -> None:
        default_profile = "multi_cover:balanced+balanced_combo"

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "default_multi.json").write_text("{}", encoding="utf-8")
            (root / backtest_service._smart_balance_candidate_cache_file_name("default_multi.json")).write_text(
                json.dumps(
                    {
                        "issues": [
                            {
                                "issue": "26060",
                                "draw_date": "2026-06-18",
                                "won_count": 1,
                                "total_prize_amount": 5.0,
                                "prize_level_hits": {},
                            }
                        ],
                        "single_hit_issues": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with (
                patch.object(backtest_service, "_smart_balance_report_cache_signature", None),
                patch.object(backtest_service, "_smart_balance_report_candidate_cache", None),
                patch.object(
                    backtest_service,
                    "_full_history_cache_candidate_report_files",
                    return_value={"default_multi": "default_multi.json"},
                ),
                patch.object(
                    backtest_service,
                    "_smart_balance_report_file_path",
                    side_effect=lambda file_name: str(root / file_name),
                ),
                patch.object(backtest_service, "_load_json_report", side_effect=AssertionError("should not load full report")),
            ):
                candidate_results = _load_smart_balance_candidate_results(scheme_count=3, ticket_mode="basic")

        self.assertEqual(candidate_results[default_profile]["26060"]["issue"], "26060")

    def test_live_calibration_history_cache_hit_returns_isolated_nested_label_hits(self) -> None:
        history = [SimpleNamespace(issue="26060", draw_date="2026-06-18")]
        cache_key = backtest_service._live_calibration_cache_key(
            history,
            sample_issues=1,
            scheme_count=3,
            strategy_mode="multi_cover",
            score_weights={},
            combo_weights={},
        )
        old_cache = dict(backtest_service._live_calibration_history_cache)
        try:
            backtest_service._live_calibration_history_cache.clear()
            backtest_service._live_calibration_history_cache[cache_key] = [
                {
                    "raw_confidence": 0.2,
                    "hit": 1,
                    "raw_front_confidence": 0.3,
                    "front_hit": 1,
                    "raw_back_confidence": 0.4,
                    "back_hit": 1,
                    "issue_mod_7": 1,
                    "label_hits": {"A": 1},
                }
            ]

            first = backtest_service._get_live_calibration_history(
                history,
                sample_issues=1,
                scheme_count=3,
                strategy_mode="multi_cover",
                ai_config=None,
                score_weights={},
                combo_weights={},
            )
            first[0]["label_hits"]["A"] = 0

            second = backtest_service._get_live_calibration_history(
                history,
                sample_issues=1,
                scheme_count=3,
                strategy_mode="multi_cover",
                ai_config=None,
                score_weights={},
                combo_weights={},
            )

            self.assertEqual(second[0]["label_hits"]["A"], 1)
        finally:
            backtest_service._live_calibration_history_cache.clear()
            backtest_service._live_calibration_history_cache.update(old_cache)

    def test_live_calibration_history_cache_store_uses_isolated_nested_label_hits(self) -> None:
        history = [SimpleNamespace(issue="26060", draw_date="2026-06-18")]
        old_cache = dict(backtest_service._live_calibration_history_cache)
        calibration_history = [
            {
                "raw_confidence": 0.2,
                "hit": 1,
                "raw_front_confidence": 0.3,
                "front_hit": 1,
                "raw_back_confidence": 0.4,
                "back_hit": 1,
                "issue_mod_7": 1,
                "label_hits": {"A": 1},
            }
        ]
        try:
            backtest_service._live_calibration_history_cache.clear()
            with patch.object(backtest_service, "_build_live_calibration_history", return_value=calibration_history):
                result = backtest_service._get_live_calibration_history(
                    history,
                    sample_issues=1,
                    scheme_count=3,
                    strategy_mode="multi_cover",
                    ai_config=None,
                    score_weights={},
                    combo_weights={},
                )

            result[0]["label_hits"]["A"] = 0
            cached_history = next(iter(backtest_service._live_calibration_history_cache.values()))
            self.assertEqual(cached_history[0]["label_hits"]["A"], 1)
        finally:
            backtest_service._live_calibration_history_cache.clear()
            backtest_service._live_calibration_history_cache.update(old_cache)

    def test_report_signature_uses_short_ttl_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "default_multi.json").write_text("{}", encoding="utf-8")

            original_stat = backtest_service.os.stat
            stat_paths: list[str] = []

            def tracked_stat(path: str):
                stat_paths.append(path)
                return original_stat(path)

            with (
                patch.object(backtest_service, "_smart_balance_report_signature_cache", {}),
                patch.object(
                    backtest_service,
                    "_full_history_cache_candidate_report_files",
                    return_value={"default_multi": "default_multi.json"},
                ),
                patch.object(
                    backtest_service,
                    "_smart_balance_report_file_path",
                    side_effect=lambda file_name: str(root / file_name),
                ),
                patch.object(backtest_service.os, "stat", side_effect=tracked_stat),
            ):
                first = backtest_service._smart_balance_report_signature(3, "basic")
                second = backtest_service._smart_balance_report_signature(3, "basic")

        self.assertEqual(first, second)
        self.assertEqual(len(stat_paths), 1)


if __name__ == "__main__":
    unittest.main()

