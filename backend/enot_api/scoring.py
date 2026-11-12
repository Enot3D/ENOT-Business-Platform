from dataclasses import asdict
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from json import dumps
from pathlib import Path
from sys import modules

from .schemas import Criterion

ROOT = Path(__file__).resolve().parents[2]
CALCULATOR = ROOT / "analysis/TASK-003/calculator/model.py"
SOURCE_COMMIT = "16f6fb59c07dc05f2fe58f26a74306cf97a89d13"
MODEL_VERSION = "2.0-pilot"
FINANCE_VERSION = "1.0"
CALCULATOR_SHA256 = "48c691616dd3f0ccfa21e5a0323335f7c600351da9e83fc4c0f9931b3b11edd9"

if sha256(CALCULATOR.read_bytes()).hexdigest() != CALCULATOR_SHA256:
    raise RuntimeError("TASK-003 calculator does not match the approved checksum")

spec = spec_from_file_location("_enot_task003_model", CALCULATOR)
calculator = module_from_spec(spec)
modules[spec.name] = calculator
spec.loader.exec_module(calculator)


def fingerprint(value: object) -> str:
    return sha256(
        dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def score(criteria: list[Criterion]):
    if tuple(criterion.code for criterion in criteria) != calculator.CRITERIA[:-1]:
        raise ValueError("Unexpected criterion order")
    return calculator.score_v2(
        [item.rating for item in criteria], [item.quality for item in criteria]
    )


def financial_cases(row: dict[str, str]):
    price, variable, fixed = (int(row[key]) for key in ("price", "variable", "fixed"))
    start_min, start_max = (int(row[key]) for key in ("start_min", "start_max"))
    volumes = {key: int(row[key]) for key in ("low", "base", "high")}
    base = volumes["base"]
    if (
        not 0 <= start_min <= start_max
        or not 0 <= volumes["low"] <= base <= volumes["high"]
    ):
        raise ValueError("Invalid startup budget or volume range")
    # TASK-003 returns outputs only. These inputs expose the same stress rounding in the API.
    stress_inputs = {
        "price_down_25": (3 * price // 4, variable, base),
        "price_up_25": ((5 * price + 3) // 4, variable, base),
        "volume_down_25": (price, variable, 3 * base // 4),
        "volume_up_25": (price, variable, (5 * base + 3) // 4),
        "cost_down_50": (price, variable // 2, base),
        "cost_up_50": (price, (3 * variable + 1) // 2, base),
    }
    results = {
        code: calculator.finance(price, variable, fixed, v)
        for code, v in volumes.items()
    }
    results.update(calculator.finance_stresses(price, variable, fixed, base))
    for code, result in results.items():
        case_price, case_variable, volume = (
            (price, variable, volumes[code]) if code in volumes else stress_inputs[code]
        )
        if result != calculator.finance(case_price, case_variable, fixed, volume):
            raise ValueError(f"Stress input disagrees with TASK-003: {code}")
        yield (
            code,
            dict(
                **asdict(result),
                unit=row["unit"],
                currency="RUB",
                start_min=start_min,
                start_max=start_max,
                price=case_price,
                variable=case_variable,
                volume=volume,
                basis_kind="hypothesis",
                finance_version=FINANCE_VERSION,
            ),
        )
