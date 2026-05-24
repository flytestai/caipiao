from __future__ import annotations

from collections import Counter

from app.models import AnalyticsResponse, FrequencyItem, LottoDraw, OddEvenStats, OmissionItem


def _frequency(draws: list[LottoDraw], *, zone: str) -> list[FrequencyItem]:
    pool = range(1, 36) if zone == "front" else range(1, 13)
    counter = Counter()
    for draw in draws:
        counter.update(draw.front_numbers if zone == "front" else draw.back_numbers)
    return [FrequencyItem(number=n, count=counter[n]) for n in pool]


def _omission(draws: list[LottoDraw], *, zone: str) -> list[OmissionItem]:
    pool = range(1, 36) if zone == "front" else range(1, 13)
    omissions: list[OmissionItem] = []
    for n in pool:
        miss = 0
        # `draws` are consumed newest-first across the app, so omission must count
        # consecutive misses from the latest draw backward.
        for draw in draws:
            values = draw.front_numbers if zone == "front" else draw.back_numbers
            if n in values:
                break
            miss += 1
        omissions.append(OmissionItem(number=n, omission=miss))
    return omissions


def _odd_even(draws: list[LottoDraw]) -> OddEvenStats:
    front_odd = front_even = back_odd = back_even = 0
    for draw in draws:
        front_odd += sum(1 for n in draw.front_numbers if n % 2 == 1)
        front_even += sum(1 for n in draw.front_numbers if n % 2 == 0)
        back_odd += sum(1 for n in draw.back_numbers if n % 2 == 1)
        back_even += sum(1 for n in draw.back_numbers if n % 2 == 0)

    return OddEvenStats(
        front_odd=front_odd,
        front_even=front_even,
        back_odd=back_odd,
        back_even=back_even,
        front_ratio=f"{front_odd}:{front_even}",
        back_ratio=f"{back_odd}:{back_even}",
    )


def build_analytics(draws: list[LottoDraw]) -> AnalyticsResponse:
    return AnalyticsResponse(
        total_draws=len(draws),
        front_frequency=_frequency(draws, zone="front"),
        back_frequency=_frequency(draws, zone="back"),
        front_omission=_omission(draws, zone="front"),
        back_omission=_omission(draws, zone="back"),
        odd_even=_odd_even(draws),
    )
