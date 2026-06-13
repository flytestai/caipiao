import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.backtest_service import (
    _active_live_smart_balance_candidate_profiles,
    _candidate_result_summary,
    _ensure_live_smart_balance_candidate_results,
    _smart_balance_candidate_profiles,
    _smart_balance_attack_issue_score,
    _smart_balance_issue_score,
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
                "prize_level_hits": {"七等奖": 1},
            }
        )
        sixth = _smart_balance_issue_score(
            {
                "won_count": 1,
                "total_prize_amount": 15.0,
                "prize_level_hits": {"六等奖": 1},
            }
        )
        fourth = _smart_balance_issue_score(
            {
                "won_count": 1,
                "total_prize_amount": 300.0,
                "prize_level_hits": {"四等奖": 1},
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
            "prize_level_hits": {"七等奖": 1},
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
                    "prize_level_hits": {"七等奖": 1},
                },
                "26002": {
                    "scheme_count": 3,
                    "won_count": 1,
                    "total_prize_amount": 5.0,
                    "prize_level_hits": {"七等奖": 1},
                },
                "26003": {
                    "scheme_count": 3,
                    "won_count": 1,
                    "total_prize_amount": 5.0,
                    "prize_level_hits": {"七等奖": 1},
                },
            }
        )
        mid_high_tier = _candidate_result_summary(
            {
                "26001": {
                    "scheme_count": 3,
                    "won_count": 1,
                    "total_prize_amount": 300.0,
                    "prize_level_hits": {"四等奖": 1},
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

    def test_live_selector_can_switch_to_high_tier_profile(self) -> None:
        history = [SimpleNamespace(issue=f"2600{i}") for i in range(1, 4)]
        candidate_results = {}
        for profile_name, *_ in _smart_balance_candidate_profiles():
            candidate_results[profile_name] = {}
            for draw in history:
                candidate_results[profile_name][draw.issue] = {
                    "won_count": 1,
                    "total_prize_amount": 5.0,
                    "prize_level_hits": {"七等奖": 1},
                }

        target_profile = "multi_cover:frequency_revert+ultra_core_jackpot"
        candidate_results[target_profile]["26003"] = {
            "won_count": 1,
            "total_prize_amount": 300.0,
            "prize_level_hits": {"四等奖": 1},
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
                    "prize_level_hits": {"七等奖": 1},
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
        self.assertIn("智能平衡按当前已知历史重算", reason)

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


if __name__ == "__main__":
    unittest.main()
