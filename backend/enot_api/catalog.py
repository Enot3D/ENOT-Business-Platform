from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations, groupby
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from . import models as m
from . import schemas as s
from .scoring import (
    CALCULATOR,
    MODEL_VERSION,
    calculator,
    file_digest,
    fingerprint,
    score,
)
from .security import (
    APIError,
    Current,
    Db,
    Writer,
    decode_cursor,
    encode_cursor,
    invalid,
    missing,
)

router = APIRouter()
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=1024)]


def columns(row, dto, **extra):
    """Project ORM fields explicitly through the public schema's field list."""
    return dto.model_validate(
        {
            key: extra[key] if key in extra else getattr(row, key)
            for key in dto.model_fields
        }
    )


def market_view(row: m.Market) -> s.Market:
    return s.Market(country=row.country_code, region=row.region_code, name=row.name)


def get_dataset(db: Session, dataset_id: UUID | None) -> m.Dataset:
    statement = select(m.Dataset)
    if dataset_id is None:
        statement = statement.order_by(
            m.Dataset.published_at.desc(), m.Dataset.id.desc()
        ).limit(1)
    else:
        statement = statement.where(m.Dataset.id == dataset_id)
    dataset = db.scalar(statement)
    if dataset is None:
        raise missing()
    return dataset


def dataset_view(db: Session, dataset: m.Dataset) -> s.Dataset:
    items = db.execute(
        select(m.Market, m.NicheRevision.industry_code)
        .join(m.NicheRevision, m.NicheRevision.market_id == m.Market.id)
        .where(m.NicheRevision.dataset_id == dataset.id)
        .distinct()
    ).all()
    markets = {row.id: market_view(row) for row, _ in items}
    return columns(
        dataset,
        s.Dataset,
        markets=sorted(
            markets.values(), key=lambda item: (item.country, item.region or "")
        ),
        industries=sorted({industry for _, industry in items}),
    )


def exact(result: m.ScoreResult, field: str) -> Fraction:
    return Fraction(getattr(result, field + "_num"), getattr(result, field + "_den"))


@dataclass(frozen=True)
class CatalogEntry:
    revision: m.NicheRevision
    result: m.ScoreResult
    view: s.Niche


def entries(db: Session, dataset_id: UUID) -> dict[UUID, CatalogEntry]:
    rows = db.execute(
        select(
            m.NicheRevision,
            m.Niche,
            m.Market,
            m.ScoreResult,
            m.FinancialScenario.start_min,
            m.FinancialScenario.start_max,
        )
        .join(m.Niche, m.Niche.id == m.NicheRevision.niche_id)
        .join(m.Market, m.Market.id == m.NicheRevision.market_id)
        .join(m.ScoreResult, m.ScoreResult.niche_revision_id == m.NicheRevision.id)
        .join(m.ScoringModel, m.ScoringModel.id == m.ScoreResult.scoring_model_id)
        .outerjoin(
            m.FinancialScenario,
            and_(
                m.FinancialScenario.score_result_id == m.ScoreResult.id,
                m.FinancialScenario.scenario_code == "base",
            ),
        )
        .where(
            m.NicheRevision.dataset_id == dataset_id,
            m.ScoringModel.version == MODEL_VERSION,
        )
    ).all()
    rows.sort(key=lambda row: (-exact(row[3], "lower"), row[1].id))
    slots = calculator.rank_slots(
        [
            tuple(row[1].id for row in group)
            for _, group in groupby(rows, key=lambda row: exact(row[3], "lower"))
        ]
    )
    result = {}
    for revision, niche, market, calculation, start_min, start_max in rows:
        rank_from, rank_to = slots[niche.id]
        score_view = columns(
            calculation,
            s.Score,
            model_version=MODEL_VERSION,
            rank_from=rank_from,
            rank_to=rank_to,
            **{
                name: float(exact(calculation, name))
                for name in ("lower", "upper", "coverage", "confidence")
            },
        )
        view = columns(
            revision,
            s.Niche,
            id=niche.id,
            legacy_code=niche.legacy_code,
            market=market_view(market),
            industry=revision.industry_code,
            score=score_view,
            start_min=start_min,
            start_max=start_max,
        )
        result[niche.id] = CatalogEntry(revision, calculation, view)
    return result


def detail(db: Session, entry: CatalogEntry) -> s.NicheDetail:
    claim_rows = db.scalars(
        select(m.Claim)
        .where(m.Claim.niche_revision_id == entry.revision.id)
        .order_by(m.Claim.section, m.Claim.id)
    ).all()
    evidence_rows = db.execute(
        select(m.Evidence, m.Observation, m.Market)
        .join(m.Observation, m.Observation.id == m.Evidence.observation_id)
        .join(m.Market, m.Market.id == m.Observation.market_id)
        .where(m.Evidence.claim_id.in_([row.id for row in claim_rows]))
        .order_by(m.Observation.metric, m.Evidence.id)
    )
    evidence = {row.id: [] for row in claim_rows}
    for link, observation, market in evidence_rows:
        evidence[link.claim_id].append(
            columns(
                link,
                s.Evidence,
                observation=columns(
                    observation, s.Observation, market=market_view(market)
                ),
            )
        )
    finances = db.scalars(
        select(m.FinancialScenario).where(
            m.FinancialScenario.score_result_id == entry.result.id
        )
    ).all()
    by_code = {row.scenario_code: row for row in finances}
    order = (
        "low",
        "base",
        "high",
        "price_down_25",
        "price_up_25",
        "volume_down_25",
        "volume_up_25",
        "cost_down_50",
        "cost_up_50",
    )
    return s.NicheDetail(
        niche=entry.view,
        criteria=[
            s.Criterion.model_validate(item)
            for item in entry.result.inputs_json["criteria"]
        ],
        claims=[columns(row, s.Claim, evidence=evidence[row.id]) for row in claim_rows],
        finance=[
            columns(by_code[code], s.Finance, code=code)
            for code in order
            if code in by_code
        ],
        finance_gap=None
        if finances
        else "В TASK-003 отсутствует финансовая модель для этой ниши.",
    )


def selected(
    db: Session, dataset_id: UUID, niche_ids: list[UUID]
) -> list[CatalogEntry]:
    get_dataset(db, dataset_id)
    catalog = entries(db, dataset_id)
    try:
        return [catalog[niche_id] for niche_id in niche_ids]
    except KeyError:
        raise missing() from None


def source_view(row: m.SourceVersion, source: m.Source) -> s.SourceVersion:
    return columns(
        row,
        s.SourceVersion,
        source_code=source.source_code,
        publisher=source.publisher,
        title=source.title,
        kind=source.kind,
    )


def sources_query():
    return select(m.SourceVersion, m.Source).join(
        m.Source, m.Source.id == m.SourceVersion.source_id
    )


def slice_page(items: list, last: UUID | None, limit: int, key):
    if last is not None:
        try:
            offset = next(i for i, item in enumerate(items) if key(item) == last) + 1
        except StopIteration:
            raise invalid("Cursor position is not available") from None
        items = items[offset:]
    return items[:limit], key(items[limit - 1]) if len(items) > limit else None


@router.get("/datasets/current", operation_id="getCurrentDataset")
def current_dataset(db: Db, auth: Current) -> s.Dataset:
    return dataset_view(db, get_dataset(db, None))


@router.get("/niches", operation_id="listNiches", response_model_exclude_unset=True)
def list_niches(
    db: Db,
    auth: Current,
    dataset_id: UUID | None = None,
    cursor: Cursor = None,
    limit: Limit = 20,
    country: Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")] = None,
    region: Annotated[str | None, Query(max_length=32)] = None,
    industry: Annotated[str | None, Query(max_length=64)] = None,
    budget_rub: Annotated[int | None, Query(ge=0, le=1_000_000_000_000)] = None,
    include_unknown_budget: bool = False,
) -> s.NichePage:
    if region is not None and country is None:
        raise invalid("country is required with region")
    binding = fingerprint(
        [country, region, industry, budget_rub, include_unknown_budget]
    )
    last, pinned = decode_cursor(cursor, "niches", binding)
    if dataset_id and pinned and dataset_id != pinned:
        raise invalid("Cursor uses a different dataset")
    dataset = get_dataset(db, pinned or dataset_id)
    filtered = [
        item.view
        for item in entries(db, dataset.id).values()
        if (country is None or country == item.view.market.country)
        and (region is None or region == item.view.market.region)
        and (industry is None or industry == item.view.industry)
        and (
            budget_rub is None
            or (
                include_unknown_budget
                if item.view.start_min is None
                else item.view.start_min <= budget_rub
            )
        )
    ]
    page, end = slice_page(filtered, last, limit, lambda item: item.id)
    return s.NichePage(
        items=page,
        next_cursor=encode_cursor("niches", binding, end, dataset.id) if end else None,
        dataset_id=dataset.id,
        model_version=MODEL_VERSION,
        updated_at=dataset.published_at,
    )


@router.get("/niches/{niche_id}", operation_id="getNiche")
def get_niche(
    niche_id: UUID, db: Db, auth: Current, dataset_id: UUID | None = None
) -> s.NicheDetail:
    dataset = get_dataset(db, dataset_id)
    return detail(db, selected(db, dataset.id, [niche_id])[0])


@router.post("/niches/{niche_id}/scores", operation_id="recalculateScore")
def recalculate(niche_id: UUID, body: s.Recalculate, db: Db, auth: Writer) -> s.Score:
    entry = selected(db, body.dataset_id, [niche_id])[0]
    inputs = entry.result.inputs_json
    criteria = [s.Criterion.model_validate(item) for item in inputs["criteria"]]
    if (
        inputs["calculator_sha256"] != file_digest(CALCULATOR)
        or entry.result.input_hash != fingerprint(inputs)
        or any(
            value != exact(entry.result, name)
            for name, value in score(criteria).items()
        )
    ):
        raise APIError(503, "score_unavailable", "Stored score cannot be reproduced")
    return entry.view.score


@router.get("/scoring-models", operation_id="listScoringModels")
def list_models(db: Db, auth: Current) -> list[s.Model]:
    return [
        columns(row, s.Model, weights=row.weights_json)
        for row in db.scalars(select(m.ScoringModel).order_by(m.ScoringModel.version))
    ]


@router.post("/comparisons", operation_id="compareNiches")
def compare(body: s.CompareRequest, db: Db, auth: Writer) -> s.Comparison:
    chosen = selected(db, body.dataset_id, body.niche_ids)
    items = [detail(db, item) for item in chosen]
    warnings = [
        f"Интервалы баллов пересекаются: №{left.view.legacy_code}, №{right.view.legacy_code}."
        for left, right in combinations(chosen, 2)
        if max(exact(left.result, "lower"), exact(right.result, "lower"))
        <= min(exact(left.result, "upper"), exact(right.result, "upper"))
    ]
    if len({item.finance[0].unit for item in items if item.finance}) > 1:
        warnings.append(
            "Оплачиваемые единицы различаются. Сценарии сравнимы только с учётом их допущений."
        )
    return s.Comparison(
        dataset_id=body.dataset_id,
        model_version=body.model_version,
        items=items,
        warnings=warnings,
    )


@router.get("/sources", operation_id="listSources")
def list_sources(
    db: Db,
    auth: Current,
    dataset_id: UUID | None = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> s.SourcePage:
    last, pinned = decode_cursor(cursor, "sources", "")
    if dataset_id and pinned and dataset_id != pinned:
        raise invalid("Cursor uses a different dataset")
    dataset = get_dataset(db, pinned or dataset_id)
    rows = db.execute(
        sources_query()
        .where(m.SourceVersion.dataset_id == dataset.id)
        .order_by(m.Source.source_code)
    ).all()
    page, end = slice_page(rows, last, limit, lambda row: row[0].id)
    return s.SourcePage(
        items=[source_view(*row) for row in page],
        next_cursor=encode_cursor("sources", "", end, dataset.id) if end else None,
    )


@router.get("/sources/{source_version_id}", operation_id="getSourceVersion")
def get_source(source_version_id: UUID, db: Db, auth: Current) -> s.SourceVersion:
    row = db.execute(
        sources_query().where(m.SourceVersion.id == source_version_id)
    ).one_or_none()
    if row is None:
        raise missing()
    return source_view(*row)
