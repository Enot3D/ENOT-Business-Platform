import csv
import json
import platform
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from . import schemas as s
from .db import now, transaction_lock
from .scoring import (
    CALCULATOR,
    FINANCE_VERSION,
    MODEL_VERSION,
    ROOT,
    SOURCE_COMMIT,
    calculator,
    file_digest,
    financial_cases,
    fingerprint,
    score,
)

AUDIT = "analysis/TASK-003/source-audit.md"
CALC_DATA = "analysis/TASK-003/calculator/data/"
REGISTRY = "research/TASK-002/sources.md"
OVERVIEW = "research/TASK-002/market-overview.md"
CURATED = "backend/data/"
INPUTS = [
    AUDIT,
    REGISTRY,
    OVERVIEW,
    CALC_DATA + "v1.json",
    CALC_DATA + "v2.csv",
    CALC_DATA + "finance.csv",
    str(CALCULATOR.relative_to(ROOT)),
    CURATED + "niche-evidence.csv",
    CURATED + "source-observations.tsv",
]
SOURCE_CODES = {f"S{i:02d}" for i in range(1, 31)}
NICHE_CODES = {f"{i:02d}" for i in range(1, 21)}
FINANCE_CODES = {"01", "02", "03", "04", "05"}
UNAVAILABLE = {"S07", "S12", "S14", "S15", "S18", "S25"}
SHELL = {"S16", "S17"}
REVIEW_DATE = date(2026, 11, 12)
IMPORTER_VERSION = "1.0"


def csv_rows(root: Path, relative: str, delimiter: str = ",") -> list[dict[str, str]]:
    with (root / relative).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=delimiter))
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError(f"Malformed input: {relative}")
    return rows


def index(rows: list[dict], codes: set[str]) -> dict[str, dict]:
    keyed = {row["id"]: row for row in rows}
    if len(keyed) != len(rows) or keyed.keys() != codes:
        raise ValueError("Missing, unexpected or duplicate dataset IDs")
    return keyed


def markdown_rows(root: Path, relative: str, pattern: str) -> dict[str, list[str]]:
    rows = {}
    for line in (root / relative).read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        match = re.match(pattern, cells[0])
        if match:
            key = match[1]
            if key in rows or len(cells) != (5 if relative == OVERVIEW else 4):
                raise ValueError(f"Malformed row: {relative} {key}")
            rows[key] = cells
    return rows


def audit_sources(
    db: Session, root: Path, dataset: m.Dataset
) -> dict[str, m.SourceVersion]:
    audit = markdown_rows(root, AUDIT, r"^\[(S\d{2})\]")
    registry = markdown_rows(root, REGISTRY, r"^(S\d{2})$")
    if audit.keys() != SOURCE_CODES or registry.keys() != SOURCE_CODES:
        raise ValueError("Expected all 30 audited sources")
    versions = {}
    for code, (link, publisher_kind, period, caveats) in sorted(audit.items()):
        url = link.split("](", 1)[1][:-1]
        title = registry[code][1].split("](", 1)[0].lstrip("[")
        publisher, kind = publisher_kind.rsplit(", ", 1)
        found = db.scalar(select(m.Source).where(m.Source.source_code == code))
        source = found or m.Source(
            id=uuid4(), source_code=code, publisher=publisher, title=title, kind=kind
        )
        if found is None:
            db.add(source)
            db.flush()
        date_match = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", period.split(" / ", 1)[0])
        previous = versions.get("S01") if code == "S02" else None
        availability = (
            "unavailable"
            if code in UNAVAILABLE
            else "shell"
            if code in SHELL
            else "readable"
        )
        fields = s.SourceVersion(
            id=uuid4(),
            source_code=code,
            publisher=publisher,
            title=title,
            kind=kind,
            version=f"{dataset.version}:{code}",
            url=url,
            published_on=datetime.strptime(date_match[0], "%d.%m.%Y").date()
            if date_match and code not in {"S11", "S13"}
            else None,
            retrieved_on=REVIEW_DATE,
            retrieved_at=None,
            availability=availability,
            access_mode="web_review"
            if availability == "readable"
            else "audit_index_or_alternate",
            license_note="Ссылка и краткий пересказ. Условия массового извлечения и перераспространения требуют проверки.",
            caveats=caveats,
        )
        version = m.SourceVersion(
            **fields.model_dump(
                exclude={"url", "publisher", "title", "kind", "source_code"}
            ),
            url=url,
            source_id=source.id,
            dataset_id=dataset.id,
            artifact_locator=f"{AUDIT} · {code}",
            supersedes_id=previous.id if previous else None,
        )
        db.add(version)
        versions[code] = version
    db.flush()
    return versions


def add_observations(
    db: Session, root: Path, versions: dict, market: m.Market
) -> dict[str, list]:
    result = {key: [] for key in versions}
    wb_locale = db.scalar(
        select(m.Market).where(
            m.Market.country_code == "AM", m.Market.region_code.is_(None)
        )
    )
    if wb_locale is None:
        wb_locale = m.Market(
            id=uuid4(), country_code="AM", name="Локаль справки Wildberries /ru/am/"
        )
        db.add(wb_locale)
        db.flush()
    money = {
        "ecommerce_turnover_original": 11_500_000_000_000,
        "ecommerce_turnover_current": 7_200_000_000_000,
        "ecommerce_turnover_revised": 13_200_000_000_000,
    }
    periods = {
        "2025": (date(2025, 1, 1), date(2025, 12, 31)),
        "2026-H1": (date(2026, 1, 1), date(2026, 6, 30)),
        "I–III кварталы 2026": (date(2026, 1, 1), date(2026, 9, 30)),
        "IV квартал 2025": (date(2025, 10, 1), date(2025, 12, 31)),
        "II квартал 2025": (date(2025, 4, 1), date(2025, 6, 30)),
    }
    seen = set()
    for row in csv_rows(root, CURATED + "source-observations.tsv", "\t"):
        version = versions[row["source"]]
        metric = row["metric"]
        if metric in seen:
            raise ValueError(f"Duplicate observation: {metric}")
        seen.add(metric)
        value = money.get(metric)
        start, end = periods.get(row["period"], (None, None))
        if row["precision"] == "day":
            match = re.search(r"\d{2}\.\d{2}\.\d{4}", row["period"])
            start = end = datetime.strptime(match[0], "%d.%m.%Y").date()
        item = m.Observation(
            id=uuid4(),
            source_version_id=version.id,
            market_id=wb_locale.id if row["source"] == "S27" else market.id,
            kind="fact" if version.availability == "readable" else "hypothesis",
            metric=metric,
            value=value,
            text_value=row["statement"],
            unit="RUB" if value is not None else None,
            currency="RUB" if value is not None else None,
            basis="nominal" if value is not None else None,
            period_start=start,
            period_end=end,
            period_label=row["period"],
            period_precision=row["precision"],
            population=row["population"],
            locator=f"{AUDIT} · {row['source']} · {row['locator']}",
            method_version="TASK-003 audit",
            limitations=version.caveats,
            input_ids=[],
        )
        db.add(item)
        result[row["source"]].append(item)
    db.flush()
    return result


def local_observation(db, revision, kind, metric, statement, locator, limitations):
    item = m.Observation(
        id=uuid4(),
        market_id=revision.market_id,
        kind=kind,
        metric=metric,
        text_value=statement,
        period_label="Пилот 2026–2027",
        period_precision="unknown",
        population=revision.segment,
        locator=locator,
        method_version="TASK-003 pilot",
        limitations=limitations,
        input_ids=[],
    )
    db.add(item)
    db.flush()
    return item


def add_claim(db, revision, section, kind, statement, local, observations=(), gap=None):
    claim = m.Claim(
        id=uuid4(),
        niche_revision_id=revision.id,
        section=section,
        kind=kind,
        statement=statement,
        gap_reason=gap,
    )
    db.add(claim)
    db.flush()
    items = [(local, "supports", "Основание экспертной оценки")] if local else []
    items.extend(
        (obs, "qualifies", "Контекст из аудита с указанными ограничениями")
        for obs in observations
    )
    for obs, relation, note in items:
        db.add(
            m.Evidence(
                claim_id=claim.id,
                observation_id=obs.id,
                relation=relation,
                locator=obs.locator,
                reviewer="TASK-003 audit",
                reviewed_at=revision.updated_at,
                note=note,
            )
        )
    return claim.id


def niche_claims(db, revision, code, review, mapping, observations, finance_row, risk):
    note = review["evidence"]
    local = local_observation(
        db,
        revision,
        "estimate",
        "expert_review",
        note,
        f"{CALC_DATA}v2.csv · {code}",
        "Экспертные оценки для скрининга.",
    )
    risk_basis = local_observation(
        db,
        revision,
        "hypothesis",
        "screening_risk",
        risk,
        f"{OVERVIEW} · {code}",
        "Риски предварительного скрининга TASK-002.",
    )
    sections = {"D": "demand", "C": "competition", "R": "risk"}
    gap_labels = {
        "D": "Прямой сигнал спроса отсутствует.",
        "U": "Неудовлетворённость клиентов требует проверки.",
        "C": "Сопоставимые конкуренты не установлены.",
        "P": "Готовность платить требует проверки.",
        "I": "Стартовые расходы не оценены.",
        "S": "Повторяемость не оценена.",
        "R": "Риски не оценены.",
    }
    criteria = []
    for key in calculator.CRITERIA[:-1]:
        rating = int(review[key]) if review[key] else None
        section = sections.get(key, "criterion")
        evidence = []
        for source in mapping.get(section, "").split():
            if not observations[source]:
                raise ValueError(f"Missing curated observation for {source}")
            evidence.extend(observations[source])
        if key == "R":
            evidence.append(risk_basis)
        gap = gap_labels[key] if rating is None else None
        statement = (
            gap
            if gap
            else f"{key}: экспертная оценка {rating}/5. {risk if key == 'R' else note}"
        )
        claim_id = add_claim(
            db,
            revision,
            section if not gap else "gap",
            "hypothesis" if gap else "estimate",
            statement,
            local,
            evidence,
            gap,
        )
        criteria.append(
            s.Criterion(
                code=key,
                rating=rating,
                quality=int(review[f"q{key}"]),
                claim_ids=[claim_id],
                gap_reason=gap,
            )
        )
    if finance_row:
        finance_note = (
            f"Допущения на оплачиваемую единицу «{finance_row['unit']}»: "
            f"цена {finance_row['price']} ₽, переменные затраты {finance_row['variable']} ₽; "
            f"фиксированные затраты {finance_row['fixed']} ₽/мес.; "
            f"объёмы {finance_row['low']}/{finance_row['base']}/{finance_row['high']} ед./мес.; "
            f"старт {finance_row['start_min']}–{finance_row['start_max']} ₽."
        )
        obs = local_observation(
            db,
            revision,
            "hypothesis",
            "finance_inputs",
            finance_note,
            f"{CALC_DATA}finance.csv · {code}",
            "Номинальные RUB. Сценарные допущения.",
        )
        add_claim(db, revision, "economics", "hypothesis", finance_note, obs)
    else:
        gap = "В TASK-003 отсутствует финансовая модель для этой ниши."
        add_claim(db, revision, "gap", "hypothesis", gap, None, gap=gap)
    return criteria


def publish(
    db: Session, version: str = "task-002-003-pilot-1", root: Path = ROOT
) -> m.Dataset:
    """Stage approved local inputs and publish them in the caller's transaction."""
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", version):
        raise ValueError("Invalid dataset version")
    files = {path: file_digest(root / path) for path in INPUTS}
    calculator_hash = files[str(CALCULATOR.relative_to(ROOT))]
    if calculator_hash != file_digest(CALCULATOR):
        raise ValueError("Release calculator differs from the backend calculator")
    manifest = {
        "version": version,
        "files": files,
        "source_commit": SOURCE_COMMIT,
        "importer_version": IMPORTER_VERSION,
        "model_version": MODEL_VERSION,
        "finance_version": FINANCE_VERSION,
    }
    manifest_hash = fingerprint(manifest)
    transaction_lock(db, "dataset-publication")
    existing = db.scalar(select(m.Dataset).where(m.Dataset.version == version))
    if existing:
        if existing.manifest_sha256 != manifest_hash:
            raise ValueError("Dataset version already exists with different inputs")
        return existing

    original = index(
        json.loads((root / (CALC_DATA + "v1.json")).read_text(encoding="utf-8")),
        NICHE_CODES,
    )
    reviewed = index(csv_rows(root, CALC_DATA + "v2.csv"), NICHE_CODES)
    finances = index(csv_rows(root, CALC_DATA + "finance.csv"), FINANCE_CODES)
    mapping = index(csv_rows(root, CURATED + "niche-evidence.csv"), NICHE_CODES)
    overview = markdown_rows(root, OVERVIEW, r"^(\d\d)\. ")
    if overview.keys() != NICHE_CODES:
        raise ValueError("Expected all 20 overview records")

    stamp = now()
    dataset = m.Dataset(
        id=uuid4(),
        version=version,
        manifest_sha256=manifest_hash,
        source_commit=SOURCE_COMMIT,
        published_at=stamp,
        manifest_json=manifest,
        importer_version=IMPORTER_VERSION,
    )
    market = db.scalar(
        select(m.Market).where(
            m.Market.country_code == "RU", m.Market.region_code.is_(None)
        )
    )
    if market is None:
        market = m.Market(id=uuid4(), country_code="RU", name="Россия")
        db.add(market)
    db.add(dataset)
    model_rows = {}
    for model_version, weights in [
        ("1.0", calculator.V1),
        (MODEL_VERSION, calculator.V2),
    ]:
        stored = db.scalar(
            select(m.ScoringModel).where(m.ScoringModel.version == model_version)
        )
        if stored is None:
            stored = m.ScoringModel(
                id=uuid4(),
                version=model_version,
                calculator_commit=SOURCE_COMMIT,
                calculator_sha256=calculator_hash,
                rubric_json={"locator": "analysis/TASK-003/data-dictionary.md"},
                criteria_order=list(calculator.CRITERIA[: len(weights)]),
                weights_json=list(weights),
                runtime_version=platform.python_version(),
                published_at=stamp,
            )
            db.add(stored)
        elif stored.calculator_sha256 != calculator_hash:
            raise ValueError(
                "Scoring model version already binds a different calculator"
            )
        model_rows[model_version] = stored
    db.flush()

    versions = audit_sources(db, root, dataset)
    observations = add_observations(db, root, versions, market)
    for code, row in sorted(original.items()):
        niche = db.scalar(select(m.Niche).where(m.Niche.legacy_code == code))
        if niche is None:
            niche = m.Niche(id=uuid4(), legacy_code=code, slug=f"niche-{code}")
            db.add(niche)
            db.flush()
        _, segment, _, risk, _ = overview[code]
        revision = m.NicheRevision(
            id=uuid4(),
            niche_id=niche.id,
            dataset_id=dataset.id,
            market_id=market.id,
            title=row["name"],
            industry_code=mapping[code]["industry"],
            segment=segment,
            summary=reviewed[code]["evidence"],
            updated_at=stamp,
        )
        db.add(revision)
        db.flush()
        finance_row = finances.get(code)
        criteria = niche_claims(
            db,
            revision,
            code,
            reviewed[code],
            mapping[code],
            observations,
            finance_row,
            risk,
        )
        inputs = {
            "criteria": [c.model_dump(mode="json") for c in criteria],
            "calculator_sha256": calculator_hash,
        }
        exact = {
            f"{name}_{part}": getattr(value, attribute)
            for name, value in score(criteria).items()
            for part, attribute in [("num", "numerator"), ("den", "denominator")]
        }
        current = m.ScoreResult(
            id=uuid4(),
            niche_revision_id=revision.id,
            scoring_model_id=model_rows[MODEL_VERSION].id,
            input_hash=fingerprint(inputs),
            inputs_json=inputs,
            calculated_at=stamp,
            **exact,
        )
        legacy = {
            "scores": row["scores"],
            "published": row["published"],
            "calculator_sha256": calculator_hash,
        }
        db.add_all(
            [
                current,
                m.ScoreResult(
                    niche_revision_id=revision.id,
                    scoring_model_id=model_rows["1.0"].id,
                    input_hash=fingerprint(legacy),
                    inputs_json=legacy,
                    calculated_at=stamp,
                    legacy_score=Decimal(str(calculator.score_v1(row["scores"]))),
                ),
            ]
        )
        db.flush()
        if finance_row:
            for scenario, values in financial_cases(finance_row):
                db.add(
                    m.FinancialScenario(
                        score_result_id=current.id,
                        scenario_code=scenario,
                        calculated_at=stamp,
                        input_hash=fingerprint(
                            {
                                "scenario": scenario,
                                "inputs": finance_row,
                                "calculator": calculator_hash,
                            }
                        ),
                        **values,
                    )
                )
    db.flush()
    if files != {path: file_digest(root / path) for path in INPUTS}:
        raise ValueError("Dataset files changed during import")
    return dataset
