from fractions import Fraction

import pytest

from model import (DRAWS, SEED, V1, finance, finance_stresses, local_weights,
                   random_weights, rank_slots, rank_v1, score_v1, score_v2, sensitivity)
from run import build_report, by_id


@pytest.fixture(scope="module")
def report():
    return build_report()


def test_all_v1_recalculations(report):
    assert len(report["niches"]) == 20
    assert all(row["delta_v1"] == 0 for row in report["niches"].values())
    assert report["baseline_rank_groups"][:5] == [("03",), ("04",), ("02",), ("05",), ("01",)]
    assert score_v1([5, 3, 2, 4, 4, 3, 2, 4]) == 71


def test_exact_ties_and_e_precedence():
    # Both score 58. E precedes the unresolved CAPEX rule.
    groups = rank_v1({"a": [3, 3, 3, 3, 3, 3, 3, 2], "c": [3, 3, 2, 3, 3, 3, 3, 3],
                      "b": [3, 3, 2, 3, 3, 3, 3, 3]})
    assert groups == [("b", "c"), ("a",)]
    assert rank_slots(groups) == {"a": (3, 3), "b": (1, 2), "c": (1, 2)}


def test_local_weights():
    cases = list(local_weights())
    assert len(cases) == 16
    for index, (_, weights) in enumerate(cases):
        focal = index // 2
        assert sum(weights) == 100
        assert weights[focal] == V1[focal] + (-5 if index % 2 == 0 else 5)
        assert len({Fraction(weights[j], V1[j]) for j in range(8) if j != focal}) == 1


def test_random_weights():
    first = list(random_weights(1000, SEED))
    assert first == list(random_weights(1000, SEED))
    assert first != list(random_weights(1000, SEED + 1))
    assert all(sum(w) == 100 and max(abs(x-y) for x, y in zip(w, V1)) <= 5 for w in first)
    assert len(set(first)) > 900


def test_sensitivity_regression(report):
    result = report["random_weights"]
    assert report["draws"] == DRAWS == 10_000
    assert result["overlap_counts"] == {"4": 414, "9/2": 53, "5": 9533}
    assert sum(row["leader_pct"] for row in result["by_niche"].values()) == pytest.approx(100)
    assert sum(row["top5_pct"] for row in result["by_niche"].values()) == pytest.approx(500)
    assert result["by_niche"]["03"]["leader_pct"] == pytest.approx(70.19)


def test_fractional_credit_at_cutoff():
    result = sensitivity({str(i): [3] * 8 for i in range(6)}, count=2)
    assert result["by_niche"]["1"]["top5_pct"] == pytest.approx(500 / 6)
    assert result["by_niche"]["1"]["leader_pct"] == pytest.approx(100 / 6)


def test_all_v2_and_quality_independence(report):
    assert report["v2_lower_rank_groups"][:5] == [("03",), ("02",), ("05",), ("04",), ("01",)]
    assert all(0 <= r["v2"]["lower"] <= r["v2"]["upper"] <= 100 for r in report["niches"].values())
    assert report["niches"]["03"]["v2"]["confidence"] == pytest.approx(1100 / 27)
    observed = score_v2([4] * 7, [2] * 7)
    more_evidence = score_v2([4] * 7, [3] * 7)
    assert observed["lower"] == more_evidence["lower"] == 80
    assert more_evidence["confidence"] > observed["confidence"]
    missing = score_v2([None] + [4] * 6, [0] + [2] * 6)
    assert missing["lower"] < observed["lower"] < missing["upper"]
    assert score_v2([None] * 7, [0] * 7) == {"lower": 0, "upper": 100, "coverage": 0, "confidence": 0}


def test_all_financial_scenarios(report):
    assert len(report["finance"]) == 5
    for row in report["finance"].values():
        assert len(row["scenarios"]) == 3
        for case in row["scenarios"].values():
            assert case["revenue"] - case["variable_total"] - case["fixed"] == case["contribution"]
            assert case["contribution"] == case["published_contribution"]
            assert case["break_even"] == row["published_break_even"]
    assert finance(20_000, 5_000, 60_000, 6).revenue == 120_000
    assert finance(12_000, 3_000, 45_000, 8).break_even == 5
    assert finance_stresses(12_000, 3_000, 45_000, 8)["price_down_25"].break_even == 8
    assert finance_stresses(30_000, 12_000, 54_000, 5)["cost_up_50"].contribution == 6_000
    assert finance(5, 5, 10, 100).break_even is None
    assert finance(4, 5, 10, 100).break_even is None
    assert finance(4, 5, 0, 0).break_even == 0


@pytest.mark.parametrize("operation", [
    lambda: score_v1([0] * 8),
    lambda: score_v1([3] * 8, [12] * 8),
    lambda: score_v1([3] * 8, [25, -5, 20, 20, 10, 10, 10, 10]),
    lambda: score_v2([None] * 7, [1] * 7),
    lambda: score_v2([3] * 7, [0] * 7),
    lambda: finance(10, -1, 0, 1),
    lambda: finance(10, 0, 0, 1.5),
    lambda: list(random_weights(0)),
    lambda: by_id([{"id": "03"}, {"id": "03"}]),
])
def test_invalid_inputs(operation):
    with pytest.raises(ValueError):
        operation()
