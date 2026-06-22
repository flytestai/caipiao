from __future__ import annotations

from collections import Counter

from app.models import AnalyticsResponse, FrequencyItem, LottoDraw, OddEvenStats, OmissionItem


def _build_zone_analytics(draws: list[LottoDraw]) -> tuple[list[FrequencyItem], list[FrequencyItem], list[OmissionItem], list[OmissionItem], OddEvenStats]:
    front_counter: Counter[int] = Counter()
    back_counter: Counter[int] = Counter()
    front_first_seen = {number: None for number in range(1, 36)}
    back_first_seen = {number: None for number in range(1, 13)}
    front_odd = front_even = back_odd = back_even = 0

    for draw_index, draw in enumerate(draws):
        front_counter.update(draw.front_numbers)
        back_counter.update(draw.back_numbers)
        for number in draw.front_numbers:
            if front_first_seen[number] is None:
                front_first_seen[number] = draw_index
            if number % 2 == 1:
                front_odd += 1
            else:
                front_even += 1
        for number in draw.back_numbers:
            if back_first_seen[number] is None:
                back_first_seen[number] = draw_index
            if number % 2 == 1:
                back_odd += 1
            else:
                back_even += 1

    total_draws = len(draws)
    front_frequency = [FrequencyItem(number=n, count=front_counter[n]) for n in range(1, 36)]
    back_frequency = [FrequencyItem(number=n, count=back_counter[n]) for n in range(1, 13)]
    front_omission = [
        OmissionItem(number=n, omission=front_first_seen[n] if front_first_seen[n] is not None else total_draws)
        for n in range(1, 36)
    ]
    back_omission = [
        OmissionItem(number=n, omission=back_first_seen[n] if back_first_seen[n] is not None else total_draws)
        for n in range(1, 13)
    ]
    odd_even = OddEvenStats(
        front_odd=front_odd,
        front_even=front_even,
        back_odd=back_odd,
        back_even=back_even,
        front_ratio=f"{front_odd}:{front_even}",
        back_ratio=f"{back_odd}:{back_even}",
    )
    return front_frequency, back_frequency, front_omission, back_omission, odd_even


def build_analytics(draws: list[LottoDraw]) -> AnalyticsResponse:
    front_frequency, back_frequency, front_omission, back_omission, odd_even = _build_zone_analytics(draws)
    return AnalyticsResponse(
        total_draws=len(draws),
        front_frequency=front_frequency,
        back_frequency=back_frequency,
        front_omission=front_omission,
        back_omission=back_omission,
        odd_even=odd_even,
    )
