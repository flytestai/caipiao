import unittest
from collections import Counter

from app.db import ensure_database
from app.services.backtest_service import (
    COMBO_WEIGHT_PROFILES,
    LOW_TIER_PRIZE_LEVELS,
    SCORE_WEIGHT_PROFILES,
    _full_history_cache_profile_specs,
    _issue_quality_signals_from_evaluations,
    _pick_guarded_high_tier_candidate,
    _pick_guarded_overall_win_candidate,
)
from app.services.meihua import _enumerate_scored_combinations, _score_candidates, build_history_feature_context, generate_divination
from app.services.repository import get_history


class FrontCoreProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_database()

    def test_ultra_core_profile_keeps_strong_front_core_with_back_variants(self) -> None:
        history = get_history(limit=500)
        score_weights = next(weights for name, _display, weights in SCORE_WEIGHT_PROFILES if name == "frequency_revert")
        combo_weights = next(weights for name, weights in COMBO_WEIGHT_PROFILES if name == "ultra_core_jackpot")

        response = generate_divination(
            history,
            issue=history[0].issue,
            timestamp="2025-01-01T20:30:00",
            scheme_count=5,
            strategy_mode="multi_cover",
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=build_history_feature_context(history),
            search_profile="full",
        )

        self.assertEqual(len(response.final_schemes), 5)

        front_tickets = [tuple(item.front_numbers) for item in response.final_schemes]
        back_tickets = [tuple(item.back_numbers) for item in response.final_schemes]
        front_number_usage = Counter(number for ticket in front_tickets for number in ticket)

        self.assertGreaterEqual(len(set(front_tickets)), 4)
        self.assertEqual(len(set(back_tickets)), 5)
        self.assertGreaterEqual(sum(1 for count in front_number_usage.values() if count >= 4), 3)

    def test_multi_cover_reserves_first_scheme_for_high_tier_and_rest_for_floor(self) -> None:
        history = get_history(limit=500)
        score_weights = next(weights for name, _display, weights in SCORE_WEIGHT_PROFILES if name == "balanced")
        combo_weights = next(weights for name, weights in COMBO_WEIGHT_PROFILES if name == "balanced_combo")

        response = generate_divination(
            history,
            issue=history[0].issue,
            timestamp="2025-01-01T20:30:00",
            scheme_count=3,
            strategy_mode="multi_cover",
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=build_history_feature_context(history),
            search_profile="full",
        )

        self.assertEqual(len(response.final_schemes), 3)
        attack_flags = ["1-4" in item.strategy for item in response.final_schemes]
        self.assertEqual(attack_flags, [True, False, False])

    def test_candidate_focus_jackpot_floor_guarded_blends_reserved_attack_with_floor_tail(self) -> None:
        history = get_history(limit=500)
        score_weights = next(weights for name, _display, weights in SCORE_WEIGHT_PROFILES if name == "frequency_revert")
        combo_weights = next(
            weights for name, weights in COMBO_WEIGHT_PROFILES if name == "candidate_focus_jackpot_floor_guarded"
        )

        response = generate_divination(
            history,
            issue=history[0].issue,
            timestamp="2025-01-01T20:30:00",
            scheme_count=5,
            strategy_mode="multi_cover",
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=build_history_feature_context(history),
            search_profile="full",
        )

        self.assertEqual(len(response.final_schemes), 5)
        attack_flags = ["1-4" in item.strategy for item in response.final_schemes]
        self.assertEqual(attack_flags[:2], [True, True])
        self.assertTrue(not any(attack_flags[2:]))

    def test_full_history_cache_profile_specs_include_hybrid_guarded_multi(self) -> None:
        specs = _full_history_cache_profile_specs(5, "basic")

        self.assertIn("hybrid_guarded_multi", specs)
        self.assertEqual(
            specs["hybrid_guarded_multi"]["candidate_name"],
            "multi_cover:frequency_revert+candidate_focus_jackpot_floor_guarded",
        )
        self.assertEqual(
            specs["hybrid_guarded_multi"]["tuning_profile_override"],
            "frequency_revert+candidate_focus_jackpot_floor_guarded",
        )

    def test_full_history_cache_default_profile_specs_use_balanced_combo(self) -> None:
        specs = _full_history_cache_profile_specs(5, "basic")

        self.assertEqual(
            specs["default_multi"]["candidate_name"],
            "multi_cover:balanced+balanced_combo",
        )
        self.assertEqual(
            specs["default_multi"]["tuning_profile_override"],
            "balanced+balanced_combo",
        )

    def test_front_back_split_profile_expands_front_and_keeps_back_pairs_independent(self) -> None:
        history = get_history(limit=500)
        score_weights = next(weights for name, _display, weights in SCORE_WEIGHT_PROFILES if name == "frequency_revert")
        combo_weights = next(weights for name, weights in COMBO_WEIGHT_PROFILES if name == "front_back_split")

        response = generate_divination(
            history,
            issue=history[0].issue,
            timestamp="2025-01-01T20:30:00",
            scheme_count=5,
            strategy_mode="multi_cover",
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=build_history_feature_context(history),
            search_profile="full",
        )

        self.assertEqual(len(response.final_schemes), 5)

        front_tickets = [tuple(item.front_numbers) for item in response.final_schemes]
        back_tickets = [tuple(item.back_numbers) for item in response.final_schemes]
        anchor_front = set(front_tickets[0])
        front_overlaps = [len(anchor_front.intersection(ticket)) for ticket in front_tickets[1:]]
        front_number_usage = Counter(number for ticket in front_tickets for number in ticket)
        back_number_usage = Counter(number for ticket in back_tickets for number in ticket)

        self.assertEqual(len(set(back_tickets)), 5)
        self.assertGreaterEqual(len(back_number_usage), 6)
        self.assertGreaterEqual(len(front_number_usage), 7)
        self.assertGreaterEqual(sum(1 for overlap in front_overlaps if overlap >= 4), 2)

    def test_front_wheel_profile_builds_five_subsets_from_six_front_numbers(self) -> None:
        history = get_history(limit=500)
        score_weights = next(weights for name, _display, weights in SCORE_WEIGHT_PROFILES if name == "frequency_revert")
        combo_weights = {
            **next(weights for name, weights in COMBO_WEIGHT_PROFILES if name == "front_wheel_split_guarded"),
            "floor_harvest_slots": 0.0,
        }

        response = generate_divination(
            history,
            issue=history[0].issue,
            timestamp="2025-01-01T20:30:00",
            scheme_count=5,
            strategy_mode="multi_cover",
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=build_history_feature_context(history),
            search_profile="full",
        )

        self.assertEqual(len(response.final_schemes), 5)

        front_tickets = [tuple(item.front_numbers) for item in response.final_schemes]
        front_number_usage = Counter(number for ticket in front_tickets for number in ticket)

        self.assertEqual(len(set(front_tickets)), 5)
        self.assertEqual(len(front_number_usage), 6)
        self.assertEqual(sum(1 for count in front_number_usage.values() if count == 5), 1)
        self.assertEqual(sum(1 for count in front_number_usage.values() if count == 4), 5)

    def test_core_back_wheel_profile_clusters_back_pairs_inside_four_numbers(self) -> None:
        history = get_history(limit=500)
        score_weights = next(weights for name, _display, weights in SCORE_WEIGHT_PROFILES if name == "frequency_revert")
        combo_weights = next(weights for name, weights in COMBO_WEIGHT_PROFILES if name == "core_back_wheel_guarded")

        response = generate_divination(
            history,
            issue=history[0].issue,
            timestamp="2025-01-01T20:30:00",
            scheme_count=5,
            strategy_mode="multi_cover",
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=build_history_feature_context(history),
            search_profile="full",
        )

        self.assertEqual(len(response.final_schemes), 5)

        back_tickets = [tuple(item.back_numbers) for item in response.final_schemes]
        back_number_usage = Counter(number for ticket in back_tickets for number in ticket)

        self.assertEqual(len(set(back_tickets)), 5)
        self.assertEqual(len(back_number_usage), 4)
        self.assertTrue(all(count >= 2 for count in back_number_usage.values()))

    def test_anchor_back_ladder_profile_repeats_front_anchor_with_clustered_back_pairs(self) -> None:
        history = get_history(limit=500)
        score_weights = next(weights for name, _display, weights in SCORE_WEIGHT_PROFILES if name == "frequency_revert")
        combo_weights = next(weights for name, weights in COMBO_WEIGHT_PROFILES if name == "anchor_back_ladder_guarded")

        response = generate_divination(
            history,
            issue=history[0].issue,
            timestamp="2025-01-01T20:30:00",
            scheme_count=5,
            strategy_mode="multi_cover",
            score_weights=score_weights,
            combo_weights=combo_weights,
            history_context=build_history_feature_context(history),
            search_profile="full",
        )

        self.assertEqual(len(response.final_schemes), 5)

        front_tickets = [tuple(item.front_numbers) for item in response.final_schemes]
        back_tickets = [tuple(item.back_numbers) for item in response.final_schemes]
        back_number_usage = Counter(number for ticket in back_tickets for number in ticket)

        self.assertEqual(front_tickets[0], front_tickets[1])
        self.assertEqual(front_tickets[1], front_tickets[2])
        self.assertEqual(len(set(back_tickets)), 5)
        self.assertEqual(len(back_number_usage), 4)

    def test_score_candidates_prefers_moderate_reversion_over_extreme_cold_numbers(self) -> None:
        tail_weights = {tail: 0.0 for tail in range(10)}
        omission_map = {number: 6 for number in range(1, 36)}
        frequency_map = {number: 10 for number in range(1, 36)}
        recent_hits = {number: 4 for number in range(1, 36)}

        omission_map[7] = 24
        frequency_map[7] = 3
        recent_hits[7] = 0

        omission_map[11] = 1
        frequency_map[11] = 17
        recent_hits[11] = 9

        scored = _score_candidates(
            range(1, 36),
            tail_weights,
            omission_map,
            frequency_map,
            recent_hits,
        )
        rank_map = {item.number: index for index, item in enumerate(scored)}

        self.assertLess(rank_map[1], rank_map[7])
        self.assertLess(rank_map[1], rank_map[11])

    def test_history_feature_context_tracks_multi_window_hits(self) -> None:
        history = get_history(limit=160)
        context = build_history_feature_context(history)

        self.assertEqual(sorted(context.front_window_hits), [12, 36, 108])
        self.assertEqual(sorted(context.back_window_hits), [12, 36, 108])
        self.assertEqual(sorted(context.front_pair_window_hits), [12, 36, 108])
        self.assertEqual(sorted(context.back_pair_window_hits), [12, 36, 108])
        self.assertEqual(
            context.front_window_hits[12][1],
            sum(1 for draw in history[:12] if 1 in draw.front_numbers),
        )
        self.assertEqual(
            context.back_window_hits[36][1],
            sum(1 for draw in history[:36] if 1 in draw.back_numbers),
        )
        self.assertEqual(
            context.front_pair_window_hits[12].get((1, 2), 0),
            sum(1 for draw in history[:12] if 1 in draw.front_numbers and 2 in draw.front_numbers),
        )
        self.assertEqual(
            context.back_pair_window_hits[12].get((1, 2), 0),
            sum(1 for draw in history[:12] if tuple(sorted(draw.back_numbers)) == (1, 2)),
        )

    def test_score_candidates_prefers_stable_multi_window_underhit_over_short_window_spike(self) -> None:
        tail_weights = {tail: 0.0 for tail in range(10)}
        omission_map = {number: 6 for number in range(1, 36)}
        frequency_map = {number: 10 for number in range(1, 36)}
        recent_hits = {number: 4 for number in range(1, 36)}
        window_hits = {
            12: {number: 2 for number in range(1, 36)},
            36: {number: 5 for number in range(1, 36)},
            108: {number: 15 for number in range(1, 36)},
        }

        window_hits[12][1] = 1
        window_hits[36][1] = 4
        window_hits[108][1] = 13

        window_hits[12][7] = 4
        window_hits[36][7] = 5
        window_hits[108][7] = 15

        window_hits[12][11] = 0
        window_hits[36][11] = 1
        window_hits[108][11] = 4

        scored = _score_candidates(
            range(1, 36),
            tail_weights,
            omission_map,
            frequency_map,
            recent_hits,
            history_size=108,
            window_hits=window_hits,
        )
        rank_map = {item.number: index for index, item in enumerate(scored)}

        self.assertLess(rank_map[1], rank_map[7])

    def test_back_combo_scoring_prefers_historically_supported_pair(self) -> None:
        source = [
            type("C", (), {"number": 5, "score": 0.72})(),
            type("C", (), {"number": 7, "score": 0.72})(),
            type("C", (), {"number": 8, "score": 0.72})(),
            type("C", (), {"number": 9, "score": 0.72})(),
        ]
        pair_window_hits = {
            12: {(5, 8): 2, (7, 9): 1},
            36: {(5, 8): 4, (7, 9): 1},
            108: {(5, 8): 10, (7, 9): 2},
        }

        combos = _enumerate_scored_combinations(
            source,
            pick_count=2,
            strategy_mode="multi_cover",
            zone="back",
            history_size=108,
            pair_window_hits=pair_window_hits,
        )

        rank_map = {tuple(item[0]): index for index, item in enumerate(combos)}
        self.assertLess(rank_map[(5, 8)], rank_map[(7, 9)])

    def test_score_candidates_prefers_front_number_with_stable_pair_cluster_support(self) -> None:
        tail_weights = {tail: 0.0 for tail in range(10)}
        omission_map = {number: 6 for number in range(1, 36)}
        frequency_map = {number: 10 for number in range(1, 36)}
        recent_hits = {number: 4 for number in range(1, 36)}
        window_hits = {
            12: {number: 2 for number in range(1, 36)},
            36: {number: 5 for number in range(1, 36)},
            108: {number: 15 for number in range(1, 36)},
        }
        pair_window_hits = {12: {}, 36: {}, 108: {}}

        for window_size, base_hits in ((12, 2), (36, 5), (108, 15)):
            pair_window_hits[window_size] = {
                (1, 2): base_hits,
                (1, 3): base_hits,
                (1, 4): base_hits,
                (1, 5): base_hits,
                (7, 20): base_hits,
                (7, 21): max(0, base_hits - 1),
            }

        scored = _score_candidates(
            range(1, 36),
            tail_weights,
            omission_map,
            frequency_map,
            recent_hits,
            history_size=108,
            window_hits=window_hits,
            pair_window_hits=pair_window_hits,
        )
        rank_map = {item.number: index for index, item in enumerate(scored)}

        self.assertLess(rank_map[1], rank_map[7])

    def test_issue_quality_signals_track_high_tier_same_ticket_proxies(self) -> None:
        signals = _issue_quality_signals_from_evaluations(
            [
                {"front_match_count": 5, "back_match_count": 1, "prize_level": "二等奖"},
                {"front_match_count": 4, "back_match_count": 2, "prize_level": "三等奖"},
                {"front_match_count": 3, "back_match_count": 0, "prize_level": None},
            ]
        )

        self.assertTrue(signals["top3_hit"])
        self.assertTrue(signals["top4_hit"])
        self.assertTrue(signals["front_5_hit"])
        self.assertTrue(signals["five_plus_one_hit"])
        self.assertFalse(signals["five_plus_two_hit"])
        self.assertTrue(signals["four_plus_two_hit"])
        self.assertTrue(signals["back_2plus_hit"])

    def test_guarded_high_tier_selection_requires_no_lower_tier_regression(self) -> None:
        fifth_level, sixth_level, seventh_level = LOW_TIER_PRIZE_LEVELS
        baseline_summary = {
            "top3_hit_issues": 0,
            "top4_hit_issues": 0,
            "front_5_hit_issues": 1,
            "five_plus_zero_hit_issues": 0,
            "five_plus_one_hit_issues": 0,
            "five_plus_two_hit_issues": 0,
            "four_plus_two_hit_issues": 0,
            "back_2plus_hit_issues": 2,
            "high_tier_proxy_score": 0.05,
            "total_prize_amount": 1000.0,
            "issue_hit_rate": 0.62,
            "won_schemes": 40,
            f"{fifth_level}_wins": 4,
            f"{fifth_level}_amount": 1200.0,
            f"{sixth_level}_wins": 10,
            f"{sixth_level}_amount": 1800.0,
            f"{seventh_level}_wins": 26,
            f"{seventh_level}_amount": 4200.0,
        }
        records = [
            {
                "name": HIGH_TIER_FALLBACK_PROFILE,
                "display_name": "baseline",
                "summary": baseline_summary,
                "stage_score": 0.11,
                "train_score": 0.11,
            },
            {
                "name": "guarded_upgrade",
                "display_name": "guarded",
                "summary": {
                    **baseline_summary,
                    "five_plus_one_hit_issues": 1,
                    "high_tier_proxy_score": 0.12,
                    "total_prize_amount": 1080.0,
                    "won_schemes": 41,
                },
                "stage_score": 0.10,
                "train_score": 0.10,
            },
            {
                "name": "regressing_upgrade",
                "display_name": "regressing",
                "summary": {
                    **baseline_summary,
                    "five_plus_two_hit_issues": 1,
                    "high_tier_proxy_score": 0.18,
                    f"{sixth_level}_wins": 9,
                    f"{sixth_level}_amount": 1700.0,
                },
                "stage_score": 0.13,
                "train_score": 0.13,
            },
        ]

        selected = _pick_guarded_high_tier_candidate(records, baseline_name=HIGH_TIER_FALLBACK_PROFILE)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["name"], "guarded_upgrade")

    def test_guarded_overall_win_selection_prefers_threshold_candidate_without_low_tier_regression(self) -> None:
        baseline_summary = {
            "top3_hit_issues": 0,
            "top4_hit_issues": 0,
            "front_5_hit_issues": 0,
            "five_plus_zero_hit_issues": 0,
            "five_plus_one_hit_issues": 0,
            "five_plus_two_hit_issues": 0,
            "four_plus_two_hit_issues": 0,
            "back_2plus_hit_issues": 2,
            "high_tier_proxy_score": 0.02,
            "overall_win_rate": 0.092,
            "total_prize_amount": 2640.0,
            "issue_hit_rate": 0.34,
            "won_schemes": 46,
        }
        for level, wins, amount in zip(LOW_TIER_PRIZE_LEVELS, (0, 2, 44), (0.0, 33.0, 2607.0)):
            baseline_summary[f"{level}_wins"] = wins
            baseline_summary[f"{level}_amount"] = amount
        records = [
            {
                "name": HIGH_TIER_FALLBACK_PROFILE,
                "display_name": "baseline",
                "summary": baseline_summary,
                "stage_score": 0.12,
                "train_score": 0.12,
            },
            {
                "name": "overall_upgrade",
                "display_name": "overall",
                "summary": {
                    **baseline_summary,
                    "overall_win_rate": 0.1,
                    "total_prize_amount": 3531.0,
                    "won_schemes": 50,
                    f"{LOW_TIER_PRIZE_LEVELS[1]}_wins": 5,
                    f"{LOW_TIER_PRIZE_LEVELS[1]}_amount": 818.0,
                    f"{LOW_TIER_PRIZE_LEVELS[2]}_wins": 45,
                    f"{LOW_TIER_PRIZE_LEVELS[2]}_amount": 2713.0,
                },
                "stage_score": 0.11,
                "train_score": 0.11,
            },
            {
                "name": "regressing_upgrade",
                "display_name": "regressing",
                "summary": {
                    **baseline_summary,
                    "overall_win_rate": 0.102,
                    "won_schemes": 51,
                    f"{LOW_TIER_PRIZE_LEVELS[2]}_wins": 43,
                },
                "stage_score": 0.13,
                "train_score": 0.13,
            },
        ]

        selected = _pick_guarded_overall_win_candidate(records, baseline_name=HIGH_TIER_FALLBACK_PROFILE)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["name"], "overall_upgrade")

    def test_guarded_overall_win_selection_allows_better_low_tier_mix_when_aggregate_improves(self) -> None:
        baseline_summary = {
            "top3_hit_issues": 0,
            "top4_hit_issues": 0,
            "front_5_hit_issues": 0,
            "five_plus_zero_hit_issues": 0,
            "five_plus_one_hit_issues": 0,
            "five_plus_two_hit_issues": 0,
            "four_plus_two_hit_issues": 0,
            "back_2plus_hit_issues": 3,
            "high_tier_proxy_score": 0.0067,
            "overall_win_rate": 0.0444,
            "total_prize_amount": 900.0,
            "issue_hit_rate": 0.1944,
            "won_schemes": 8,
        }
        for level, wins, amount in zip(LOW_TIER_PRIZE_LEVELS, (0, 1, 7), (0.0, 200.0, 700.0)):
            baseline_summary[f"{level}_wins"] = wins
            baseline_summary[f"{level}_amount"] = amount
        records = [
            {
                "name": HIGH_TIER_FALLBACK_PROFILE,
                "display_name": "baseline",
                "summary": baseline_summary,
                "stage_score": 0.12,
                "train_score": 0.12,
            },
            {
                "name": "aggregate_upgrade",
                "display_name": "aggregate",
                "summary": {
                    **baseline_summary,
                    "overall_win_rate": 0.1167,
                    "total_prize_amount": 2100.0,
                    "issue_hit_rate": 0.3889,
                    "won_schemes": 21,
                    f"{LOW_TIER_PRIZE_LEVELS[1]}_wins": 0,
                    f"{LOW_TIER_PRIZE_LEVELS[1]}_amount": 0.0,
                    f"{LOW_TIER_PRIZE_LEVELS[2]}_wins": 21,
                    f"{LOW_TIER_PRIZE_LEVELS[2]}_amount": 2100.0,
                },
                "stage_score": 0.15,
                "train_score": 0.15,
            },
        ]

        selected = _pick_guarded_overall_win_candidate(records, baseline_name=HIGH_TIER_FALLBACK_PROFILE)

        self.assertIsNotNone(selected)
        self.assertEqual(selected["name"], "aggregate_upgrade")


if __name__ == "__main__":
    unittest.main()
