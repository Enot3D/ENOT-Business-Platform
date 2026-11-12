"""Write the TASK-003 result as JSON. Invoke with python run.py."""
import csv
import json
from dataclasses import asdict
from itertools import groupby
from pathlib import Path

from model import (CRITERIA, DRAWS, SEED, V1, V2, finance, finance_stresses,
                   local_weights, rank_slots, rank_v1, score_v1, score_v2, sensitivity)

DATA = Path(__file__).resolve().parent / "data"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError(f"Empty or malformed CSV: {path}")
    return rows


def by_id(rows: list[dict]) -> dict[str, dict]:
    result = {}
    for row in rows:
        niche = row["id"]
        if len(niche) != 2 or niche not in {f"{i:02d}" for i in range(1, 21)} or niche in result:
            raise ValueError(f"Invalid or duplicate niche ID: {niche!r}")
        result[niche] = row
    return result


def build_report() -> dict:
    original = by_id(json.loads((DATA / "v1.json").read_text(encoding="utf-8")))
    reviewed = by_id(read_csv(DATA / "v2.csv"))
    financial = by_id(read_csv(DATA / "finance.csv"))
    if len(original) != 20 or original.keys() != reviewed.keys() or len(financial) != 5:
        raise ValueError("Expected a complete 20-niche comparison and five finance rows")
    scores = {niche: row["scores"] for niche, row in original.items()}
    groups = rank_v1(scores)
    baseline = rank_slots(groups)
    rows = {}
    review_lower = {}
    for niche, review in reviewed.items():
        raw_scores = [int(review[k]) if review[k] else None for k in CRITERIA[:-1]]
        quality = [int(review[f"q{k}"]) for k in CRITERIA[:-1]]
        v1 = score_v1(scores[niche])
        v2 = score_v2(raw_scores, quality)
        review_lower[niche] = v2["lower"]
        rows[niche] = {
            "name": original[niche]["name"],
            "v1": float(v1),
            "published": original[niche]["published"],
            "delta_v1": float(v1 - original[niche]["published"]),
            "v1_rank_slots": baseline[niche],
            "v2": {key: float(value) for key, value in v2.items()},
            "v2_scores": raw_scores,
            "v2_quality": quality,
            "v2_reasons": review["evidence"],
        }

    review_groups = [
        tuple(group) for _, group in groupby(
            sorted(sorted(review_lower), key=review_lower.__getitem__, reverse=True),
            key=review_lower.__getitem__,
        )
    ]
    for niche, slots in rank_slots(review_groups).items():
        rows[niche]["v2_rank_slots"] = slots

    economics = {}
    for niche, row in financial.items():
        start = [int(row[k]) for k in ("start_min", "start_max")]
        volumes = {case: int(row[case]) for case in ("low", "base", "high")}
        if not 0 <= start[0] <= start[1] or not 0 <= volumes["low"] <= volumes["base"] <= volumes["high"]:
            raise ValueError(f"Invalid startup budget or scenario ordering: {niche}")
        inputs = [int(row[k]) for k in ("price", "variable", "fixed")]
        economics[niche] = {
            "unit": row["unit"],
            "startup": start,
            "scenarios": {
                case: {"volume": volume, **asdict(finance(*inputs, volume)),
                       "published_contribution": int(row[f"published_{case}"])}
                for case, volume in volumes.items()
            },
            "published_break_even": int(row["published_break_even"]),
            "stress": {
                case: asdict(result) for case, result in finance_stresses(*inputs, volumes["base"]).items()
            },
        }

    return {
        "versions": {"original": "1.0", "review": "2.0-pilot", "finance": "1.0", "sensitivity": "1.0"},
        "weights_v1": V1,
        "weights_v2_before_normalization": V2,
        "seed": SEED,
        "draws": DRAWS,
        "baseline_rank_groups": groups,
        "v2_lower_rank_groups": review_groups,
        "niches": rows,
        "local_weights": {
            label: {"weights_pp_exact": [str(w) for w in weights], "rank_groups": rank_v1(scores, weights)}
            for label, weights in local_weights()
        },
        "random_weights": sensitivity(scores),
        "finance": economics,
    }


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
