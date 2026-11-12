"""ENOT TASK-003 calculation methods. See ../data-dictionary.md."""
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import groupby
from math import ceil, floor
from random import Random
from statistics import mean

CRITERIA = ("D", "U", "C", "P", "I", "S", "R", "E")
V1 = (20, 15, 10, 15, 10, 10, 10, 10)
V2 = V1[:-1]
SEED = 20261112
DRAWS = 10_000


def _integer(value: int, minimum: int, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"Expected integer in [{minimum}, {maximum}]: {value!r}")


def _weights(weights: Sequence[int | Fraction]) -> None:
    if (
        len(weights) != len(V1)
        or any(type(w) not in (int, Fraction) or w < 0 for w in weights)
        or sum(weights) != 100
    ):
        raise ValueError("Expected eight nonnegative rational weights summing to 100")


def _scores(scores: Sequence[int]) -> None:
    if len(scores) != len(V1):
        raise ValueError("Expected eight v1 scores")
    for score in scores:
        _integer(score, 1, 5)


def score_v1(scores: Sequence[int], weights: Sequence[int | Fraction] = V1) -> Fraction:
    """Return the exact score on a scale from 20 to 100."""
    _scores(scores)
    _weights(weights)
    return Fraction(sum(w * s for w, s in zip(weights, scores)), 5)


def _rank(rows: dict[str, Sequence[int]], weights: Sequence[int | Fraction]) -> list[tuple[str, ...]]:
    # Use numerator before dividing by 5. The division cannot change ordering.
    keys = {niche: (sum(w * s for w, s in zip(weights, scores)), scores[-1])
            for niche, scores in rows.items()}
    return [tuple(group) for _, group in groupby(
        sorted(sorted(rows), key=keys.__getitem__, reverse=True),
        key=keys.__getitem__,
    )]


def rank_v1(rows: dict[str, Sequence[int]], weights: Sequence[int | Fraction] = V1) -> list[tuple[str, ...]]:
    """Rank by score and E. Unresolved CAPEX ties form groups sorted by ID."""
    _weights(weights)
    for scores in rows.values():
        _scores(scores)
    return _rank(rows, weights)


def local_weights() -> Iterable[tuple[str, tuple[int | Fraction, ...]]]:
    """Shift one weight by five points; rescale the other seven proportionally."""
    for index, criterion in enumerate(CRITERIA):
        for delta in (-5, 5):
            factor = Fraction(100 - V1[index] - delta, 100 - V1[index])
            yield f"{criterion}{delta:+d}", tuple(
                weight + delta if index == j else weight * factor
                for j, weight in enumerate(V1)
            )


def random_weights(count: int = DRAWS, seed: int = SEED) -> Iterable[tuple[int, ...]]:
    """Uniform draws with replacement on the integer grid within ±5 p.p. of v1."""
    _integer(count, 1)
    if type(seed) is not int:
        raise ValueError("Expected integer seed")
    rng = Random(seed)
    for _ in range(count):
        while True:
            # random() has a stable sequence for a given seed across Python versions.
            # Discard the remainder so the 11 buckets have equal cardinality.
            offsets = []
            while len(offsets) < len(V1) - 1:
                value = int(rng.random() * (1 << 53))
                if value < (1 << 53) - ((1 << 53) % 11):
                    offsets.append(value % 11 - 5)
            last = -sum(offsets)
            if abs(last) <= 5:
                yield tuple(weight + delta for weight, delta in zip(V1, [*offsets, last]))
                break


def rank_slots(groups: list[tuple[str, ...]]) -> dict[str, tuple[int, int]]:
    slots = {}
    first = 1
    for group in groups:
        last = first + len(group) - 1
        slots.update({niche: (first, last) for niche in group})
        first = last + 1
    return slots


def _top5_credit(first: int, last: int) -> Fraction:
    return Fraction(max(0, min(5, last) - first + 1), last - first + 1)


def sensitivity(rows: dict[str, Sequence[int]], count: int = DRAWS, seed: int = SEED) -> dict:
    baseline = rank_slots(rank_v1(rows))
    top5 = Counter()
    leads = Counter()
    overlaps = Counter()
    rank_ranges = {niche: Counter() for niche in rows}
    displacements = {niche: [] for niche in rows}
    baseline_top = {niche: _top5_credit(*span) for niche, span in baseline.items()}
    for weights in random_weights(count, seed):
        slots = rank_slots(_rank(rows, weights))
        overlap = Fraction()
        for niche, (first, last) in slots.items():
            tie_size = last - first + 1
            credit = _top5_credit(first, last)
            top5[niche] += credit
            overlap += credit * baseline_top[niche]
            if first == 1:
                leads[niche] += Fraction(1, tie_size)
            rank_ranges[niche][(first, last)] += 1
            base_first, base_last = baseline[niche]
            displacements[niche].append(abs((first + last - base_first - base_last) / 2))
        overlaps[str(overlap)] += 1
    return {
        "overlap_counts": dict(sorted(overlaps.items(), key=lambda item: Fraction(item[0]))),
        "by_niche": {
            niche: {
                "top5_pct": float(100 * top5[niche] / count),
                "leader_pct": float(100 * leads[niche] / count),
                "best_rank": min(a for a, _ in rank_ranges[niche]),
                "worst_rank": max(b for _, b in rank_ranges[niche]),
                "mean_abs_rank_shift": mean(displacements[niche]),
            }
            for niche in rows
        },
    }


def score_v2(scores: Sequence[int | None], quality: Sequence[int]) -> dict[str, Fraction]:
    """Return score bounds, observed weight, and confidence, each in 0..100."""
    if len(scores) != len(V2) or len(quality) != len(V2):
        raise ValueError("Expected seven v2 assessments")
    known_weight = 0
    points = 0
    support = 0
    for weight, score, tier in zip(V2, scores, quality):
        _integer(tier, 0, 3)
        if score is None:
            if tier:
                raise ValueError("A missing score must have zero evidence quality")
            continue
        _integer(score, 1, 5)
        _integer(tier, 1, 3)
        known_weight += weight
        points += weight * score
        support += weight * tier
    total = sum(V2)
    lower = Fraction(100 * points, 5 * total)
    missing_weight = total - known_weight
    return {
        "lower": lower,
        "upper": lower + Fraction(100 * missing_weight, total),
        "coverage": Fraction(100 * known_weight, total),
        "confidence": Fraction(100 * support, 3 * total),
    }


@dataclass(frozen=True)
class FinancialResult:
    revenue: int
    variable_total: int
    fixed: int
    contribution: int
    unit_margin: int
    break_even: int | None


def finance(price: int, variable: int, fixed: int, volume: int) -> FinancialResult:
    """Return monthly figures in whole RUB at an integer paid volume."""
    for value in (price, variable, fixed, volume):
        _integer(value, 0)
    unit_margin = price - variable
    threshold = ceil(Fraction(fixed, unit_margin)) if unit_margin > 0 else None
    if fixed == 0:
        threshold = 0  # Zero volume gives zero contribution even with negative unit margin.
    return FinancialResult(price * volume, variable * volume, fixed,
                           unit_margin * volume - fixed, unit_margin, threshold)


def finance_stresses(price: int, variable: int, fixed: int, volume: int) -> dict[str, FinancialResult]:
    """Change one base input at a time using the documented rounding rules."""
    finance(price, variable, fixed, volume)
    return {
        "price_down_25": finance(floor(Fraction(3 * price, 4)), variable, fixed, volume),
        "price_up_25": finance(ceil(Fraction(5 * price, 4)), variable, fixed, volume),
        "volume_down_25": finance(price, variable, fixed, floor(Fraction(3 * volume, 4))),
        "volume_up_25": finance(price, variable, fixed, ceil(Fraction(5 * volume, 4))),
        "cost_down_50": finance(price, floor(Fraction(variable, 2)), fixed, volume),
        "cost_up_50": finance(price, ceil(Fraction(3 * variable, 2)), fixed, volume),
    }
