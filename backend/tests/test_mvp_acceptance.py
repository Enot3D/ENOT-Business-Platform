"""Independent acceptance oracles for the published TASK-003 pilot."""

import csv
import hashlib
import json
from fractions import Fraction
from math import ceil, floor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import ORIGIN, PASSWORD
from enot_api.db import session_factory
from enot_api.importer import publish
from enot_api.main import app
from enot_api.models import ScoreResult

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "analysis/TASK-003/calculator/data"
API = "/api/v1"
WEIGHTS = dict(zip("DUCPISR", (20, 15, 10, 15, 10, 10, 10)))


def rows(filename):
    with (INPUTS / filename).open(encoding="utf-8", newline="") as handle:
        return {row["id"]: row for row in csv.DictReader(handle)}


@pytest.fixture
def client(initial, app_config):
    with TestClient(app, base_url=ORIGIN) as session:
        response = session.post(
            API + "/session",
            json={"login": "owner", "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200, response.text
        session.headers.update(
            {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}
        )
        yield session


def get(client, path, **params):
    response = client.get(API + path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def expected_score(row):
    known = [key for key in WEIGHTS if row[key]]
    coverage = Fraction(sum(WEIGHTS[key] for key in known), 90)
    lower = Fraction(sum(WEIGHTS[key] * int(row[key]) for key in known), 450)
    confidence = Fraction(sum(WEIGHTS[key] * int(row[f"q{key}"]) for key in known), 270)
    return {
        "lower": lower * 100,
        "upper": (lower + 1 - coverage) * 100,
        "coverage": coverage * 100,
        "confidence": confidence * 100,
    }


def expected_cases(row):
    price, variable, fixed, base = (
        int(row[key]) for key in ("price", "variable", "fixed", "base")
    )
    inputs = {
        "low": (price, variable, int(row["low"])),
        "base": (price, variable, base),
        "high": (price, variable, int(row["high"])),
        "price_down_25": (floor(Fraction(3, 4) * price), variable, base),
        "price_up_25": (ceil(Fraction(5, 4) * price), variable, base),
        "volume_down_25": (price, variable, floor(Fraction(3, 4) * base)),
        "volume_up_25": (price, variable, ceil(Fraction(5, 4) * base)),
        "cost_down_50": (price, floor(Fraction(1, 2) * variable), base),
        "cost_up_50": (price, ceil(Fraction(3, 2) * variable), base),
    }
    for case, (p, v, volume) in inputs.items():
        margin = p - v
        threshold = (
            0 if fixed == 0 else ceil(Fraction(fixed, margin)) if margin > 0 else None
        )
        yield (
            case,
            {
                "price": p,
                "variable": v,
                "fixed": fixed,
                "volume": volume,
                "revenue": p * volume,
                "variable_total": v * volume,
                "unit_margin": margin,
                "contribution": margin * volume - fixed,
                "break_even": threshold,
                "unit": row["unit"],
                "currency": "RUB",
                "start_min": int(row["start_min"]),
                "start_max": int(row["start_max"]),
            },
        )


def test_r2_r7_original_inputs_match_release(client, initial):
    expected = {code: expected_score(row) for code, row in rows("v2.csv").items()}
    finance = rows("finance.csv")
    catalog = get(client, "/niches", country="RU", limit=100)
    items = catalog["items"]
    assert len(items) == 20
    assert {item["legacy_code"] for item in items} == set(expected)
    order = [expected[item["legacy_code"]]["lower"] for item in items]
    assert order == sorted(order, reverse=True)
    assert [item["legacy_code"] for item in items[:5]] == ["03", "02", "05", "04", "01"]
    for item in items:
        code = item["legacy_code"]
        actual = item["score"]
        values = expected[code]
        assert {name: actual[name] for name in values} == {
            name: float(value) for name, value in values.items()
        }, code
        lower = values["lower"]
        assert (actual["rank_from"], actual["rank_to"]) == (
            1 + sum(value > lower for value in order),
            sum(value >= lower for value in order),
        ), code
        detail = get(client, f"/niches/{item['id']}")
        actual_cases = {case["code"]: case for case in detail["finance"]}
        if code not in finance:
            assert not actual_cases and detail["finance_gap"], code
            continue
        cases = dict(expected_cases(finance[code]))
        assert len(detail["finance"]) == len(cases) == 9, code
        assert actual_cases.keys() == cases.keys(), code
        for case, result in cases.items():
            assert {key: actual_cases[case][key] for key in result} == result, (
                code,
                case,
            )
        assert detail["finance_gap"] is None, code

    manifest = initial.manifest_json
    assert manifest["model_version"] == "2.0-pilot"
    assert manifest["finance_version"] == "1.0"
    assert {
        f"analysis/TASK-003/calculator/data/{name}"
        for name in ("v1.json", "v2.csv", "finance.csv")
    } <= manifest["files"].keys()
    for path, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    canonical = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == initial.manifest_sha256

    with session_factory()() as db:
        original = json.loads((INPUTS / "v1.json").read_text(encoding="utf-8"))
        stored = {str(result.id): result for result in db.scalars(select(ScoreResult))}
        for item in items:
            score = stored[item["score"]["id"]]
            for name, value in expected[item["legacy_code"]].items():
                assert (
                    Fraction(
                        getattr(score, f"{name}_num"), getattr(score, f"{name}_den")
                    )
                    == value
                )
        v1_by_code = {
            row["id"]: Fraction(
                sum(w * s for w, s in zip((*WEIGHTS.values(), 10), row["scores"])), 5
            )
            for row in original
        }
        legacy = {
            result.niche_revision_id: result.legacy_score
            for result in stored.values()
            if result.legacy_score is not None
        }
        assert len(legacy) == len(v1_by_code) == 20
        for item in items:
            revision = stored[item["score"]["id"]].niche_revision_id
            assert Fraction(legacy[revision]) == v1_by_code[item["legacy_code"]]


def test_r1_cursor_survives_publication(client):
    filters = {"country": "RU", "industry": "manufacturing"}
    expected = get(client, "/niches", **filters, limit=100)
    assert 2 < len(expected["items"]) < 20
    first = get(client, "/niches", **filters, limit=2)
    assert first["next_cursor"]
    assert get(client, "/niches", country="DE")["items"] == []

    with session_factory().begin() as db:
        new_id = str(publish(db, version="qa-acceptance-next").id)
    assert get(client, "/niches", **filters)["dataset_id"] == new_id

    cursor = first["next_cursor"]
    items = first["items"]
    while cursor:
        following = get(client, "/niches", **filters, limit=3, cursor=cursor)
        assert following["dataset_id"] == first["dataset_id"] != new_id
        items.extend(following["items"])
        cursor = following["next_cursor"]
    assert items == expected["items"]
    assert (
        client.get(
            API + "/niches",
            params={**filters, "cursor": first["next_cursor"], "budget_rub": 99999},
        ).status_code
        == 422
    )


def test_r4_original_and_revised_sources_are_traceable(client):
    sources = get(client, "/sources", limit=100)["items"]
    by_id = {row["id"]: row for row in sources}
    assert len(sources) == len(by_id) == 30
    assert {row["source_code"] for row in sources} == {
        f"S{i:02d}" for i in range(1, 31)
    }
    unavailable = [row for row in sources if row["availability"] == "unavailable"]
    assert len(unavailable) == 6
    assert all(row["caveats"] and row["retrieved_on"] for row in unavailable)
    commerce = next(
        row
        for row in get(client, "/niches", industry="ecommerce")["items"]
        if row["legacy_code"] == "04"
    )
    detail = get(client, f"/niches/{commerce['id']}")
    observations = {
        item["observation"]["metric"]: item["observation"]
        for claim in detail["claims"]
        for item in claim["evidence"]
        if item["observation"]["metric"].startswith("ecommerce_turnover_")
    }
    for suffix, (amount, source_code, period) in {
        "original": (11_500_000_000_000, "S01", "2025"),
        "revised": (13_200_000_000_000, "S02", "2025"),
        "current": (7_200_000_000_000, "S02", "2026-H1"),
    }.items():
        observation = observations[f"ecommerce_turnover_{suffix}"]
        source = get(client, f"/sources/{observation['source_version_id']}")
        assert (
            observation["value"],
            source["source_code"],
            observation["period_label"],
        ) == (amount, source_code, period)
        assert observation["market"]["country"] == "RU"
        assert source == by_id[source["id"]]
        assert source["publisher"] == "АКИТ"
        assert source["retrieved_on"] and source["version"]
