"""Evidence selection and deterministic rendering for the pilot analyst."""

import csv
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from itertools import combinations
from uuid import UUID

from pydantic import Field
from sqlalchemy import select

from . import models as m
from . import schemas as s
from .catalog import detail, entries, exact
from .db import session_factory
from .scoring import ROOT, fingerprint

PROMPT_VERSION = "task-007-evidence-v1"
SECTION_LABELS = {
    "demand": "Сигнал спроса",
    "competition": "Конкуренция",
    "risk": "Контекст рисков",
    "economics": "Контекст экономики",
    "criterion": "Контекст оценки",
    "gap": "Контекст пробела",
}
RELATION_LABELS = {
    "supports": "поддерживает",
    "qualifies": "уточняет",
    "contradicts": "противоречит",
}
CRITERION_LABELS = {
    "D": "сигнал спроса",
    "U": "неудовлетворённость клиентов",
    "C": "конкурентная позиция",
    "P": "готовность платить",
    "I": "доступность старта",
    "S": "повторяемость",
    "R": "управляемость рисков",
}


@lru_cache(maxsize=1)
def reviewed_excerpts() -> dict[str, tuple[str, str, str]]:
    path = ROOT / "backend/data/source-observations.tsv"
    with path.open(encoding="utf-8", newline="") as source:
        return {
            row["metric"]: (row["statement"], row["period"], row["source"])
            for row in csv.DictReader(source, delimiter="\t")
        }


class Reference(s.DTO):
    evidence_id: UUID
    observation_id: UUID


class Selection(s.DTO):
    references: list[Reference] = Field(min_length=1, max_length=12)


@dataclass(frozen=True)
class Evidence:
    niche: int
    section: str
    link: s.Evidence
    same_market: bool

    def provider_view(self) -> dict:
        return {
            "niche": self.niche,
            "section": self.section,
            "relation": self.link.relation,
            "same_market": self.same_market,
            "precision": self.link.observation.period_precision,
            "evidence_id": str(self.link.id),
            "observation_id": str(self.link.observation.id),
        }


@dataclass(frozen=True)
class Context:
    niches: tuple[s.NicheDetail, ...]
    intervals: tuple[tuple[Fraction, Fraction], ...]
    evidence: tuple[Evidence, ...]
    gaps: tuple[str, ...]

    def digest(self) -> str:
        return fingerprint(
            {
                "niches": [item.model_dump(mode="json") for item in self.niches],
                "intervals": [
                    [str(lower), str(upper)] for lower, upper in self.intervals
                ],
                "eligible_evidence": [row.provider_view() for row in self.evidence],
            }
        )


def build_context(job: m.Interpretation) -> Context:
    with session_factory()() as db:
        by_result = {
            str(entry.result.id): entry
            for entry in entries(db, job.dataset_id).values()
            if entry.result.scoring_model_id == job.scoring_model_id
        }
        chosen = [by_result[result_id] for result_id in job.score_result_ids]
        details = tuple(detail(db, entry) for entry in chosen)
        intervals = tuple(
            (exact(entry.result, "lower"), exact(entry.result, "upper"))
            for entry in chosen
        )
        readable = dict(
            db.execute(
                select(m.SourceVersion.id, m.Source.source_code)
                .join(m.Source, m.Source.id == m.SourceVersion.source_id)
                .where(
                    m.SourceVersion.dataset_id == job.dataset_id,
                    m.SourceVersion.availability == "readable",
                )
            ).all()
        )

    reviewed = reviewed_excerpts()
    evidence = []
    gaps = []
    for position, item in enumerate(details, 1):
        prefix = f"№{item.niche.legacy_code}."
        for claim in item.claims:
            if claim.gap_reason:
                gaps.append(f"{prefix} {claim.gap_reason}")
            for link in claim.evidence:
                obs = link.observation
                if obs.kind == "fact" and reviewed.get(obs.metric) == (
                    obs.text_value,
                    obs.period_label,
                    readable.get(obs.source_version_id),
                ):
                    evidence.append(
                        Evidence(
                            position,
                            claim.section,
                            link,
                            obs.market == item.niche.market,
                        )
                    )
        if not any(row.niche == position for row in evidence):
            gaps.append(
                f"{prefix} Нет подтверждённых наблюдений из доступных источников."
            )
    return Context(details, intervals, tuple(evidence), tuple(gaps))


def validate_selection(
    selection: Selection, evidence: tuple[Evidence, ...]
) -> list[Evidence]:
    allowed = {row.link.id: row for row in evidence}
    selected = []
    seen = set()
    for ref in selection.references:
        row = allowed.get(ref.evidence_id)
        if (
            row is None
            or ref.evidence_id in seen
            or ref.observation_id != row.link.observation.id
        ):
            raise ValueError("Unknown, repeated or mismatched evidence reference")
        selected.append(row)
        seen.add(ref.evidence_id)
    return selected


def render(context: Context, selected: list[Evidence]) -> list[s.Statement]:
    items = []
    for position, niche in enumerate(context.niches, 1):
        label = f"№{niche.niche.legacy_code}"
        evidence = [row for row in context.evidence if row.niche == position]
        preferred = [row for row in selected if row.niche == position]
        score = niche.niche.score
        items.append(
            s.Statement(
                kind="calculation",
                statement=(
                    f"{label}. Opportunity Score {score.model_version}: {score.lower:.2f}–"
                    f"{score.upper:.2f}/100. Покрытие {score.coverage:.2f}/100, "
                    f"Confidence {score.confidence:.2f}/100."
                ),
                observation_ids=[],
            )
        )
        # Preserve contrary evidence independently of model ranking.
        prioritized = preferred + sorted(evidence, key=lambda row: not row.same_market)
        for section, section_label in SECTION_LABELS.items():
            matches = [row for row in prioritized if row.section == section]
            for contradictory in (False, True):
                row = next(
                    (
                        row
                        for row in matches
                        if (row.link.relation == "contradicts") == contradictory
                    ),
                    None,
                )
                if row is None:
                    continue
                obs = row.link.observation
                geography = (
                    "" if row.same_market else " Источник относится к другой географии."
                )
                items.append(
                    s.Statement(
                        kind="fact",
                        statement=(
                            f"{label}. {section_label} ({RELATION_LABELS[row.link.relation]}): "
                            f"{obs.text_value} Период источника: {obs.period_label}.{geography} "
                            "Применимость к нише проверяется отдельно."
                        ),
                        observation_ids=[obs.id],
                    )
                )
        for heading, ratings in (
            ("Преимущества по оценке", (4, 5)),
            ("Недостатки по оценке", (1, 2)),
        ):
            criteria = [
                criterion for criterion in niche.criteria if criterion.rating in ratings
            ]
            if criteria:
                claim_ids = {
                    key for criterion in criteria for key in criterion.claim_ids
                }
                labels = ", ".join(
                    f"{CRITERION_LABELS[item.code]} {item.rating}/5"
                    for item in criteria
                )
                items.append(
                    s.Statement(
                        kind="estimate",
                        statement=f"{label}. {heading} TASK-003: {labels}.",
                        observation_ids=list(
                            dict.fromkeys(
                                link.observation.id
                                for claim in niche.claims
                                if claim.id in claim_ids
                                for link in claim.evidence
                                if link.relation == "supports"
                                and link.observation.kind == "estimate"
                            )
                        ),
                    )
                )
        for claim in niche.claims:
            for link in claim.evidence:
                obs = link.observation
                if (
                    obs.kind == "hypothesis"
                    and obs.metric == "screening_risk"
                    and obs.text_value
                ):
                    items.append(
                        s.Statement(
                            kind="hypothesis",
                            statement=f"{label}. Риск для проверки: {obs.text_value}",
                            observation_ids=[obs.id],
                        )
                    )
        base = next(
            (scenario for scenario in niche.finance if scenario.code == "base"), None
        )
        if base is not None:
            threshold = (
                f"{base.break_even} ед./мес."
                if base.break_even is not None
                else "недостижим в сценарии."
            )
            items.append(
                s.Statement(
                    kind="calculation",
                    statement=(
                        f"{label}. Базовый сценарий TASK-003 ({base.unit}): "
                        f"вклад {base.contribution} ₽/мес. при объёме {base.volume} ед./мес. "
                        f"Порог безубыточности: {threshold} Значения рассчитаны на допущениях."
                    ),
                    observation_ids=list(
                        dict.fromkeys(
                            link.observation.id
                            for claim in niche.claims
                            if claim.section == "economics"
                            for link in claim.evidence
                            if link.observation.kind == "hypothesis"
                            and link.observation.metric == "finance_inputs"
                        )
                    ),
                )
            )
        items.append(
            s.Statement(
                kind="hypothesis",
                statement=(
                    f"{label}. Проверка спроса для сегмента «{niche.niche.segment}»: выяснить, "
                    "когда клиенты столкнулись с проблемой и чем её решали. Предложить платный пилот "
                    "с конкретной ценой. Раздельно фиксировать интерес, отказы, оплаты "
                    "и затраты на выполнение."
                ),
                observation_ids=[],
            )
        )
    for left, right in combinations(range(len(context.niches)), 2):
        a, b = context.niches[left].niche, context.niches[right].niche
        low_a, high_a = context.intervals[left]
        low_b, high_b = context.intervals[right]
        if max(low_a, low_b) <= min(high_a, high_b):
            verdict = (
                "интервалы Opportunity Score пересекаются, порядок по ним не определён."
            )
        else:
            higher = a if low_a > high_b else b
            verdict = f"весь диапазон Opportunity Score выше у №{higher.legacy_code}."
        items.append(
            s.Statement(
                kind="calculation",
                statement=f"Сравнение №{a.legacy_code} и №{b.legacy_code}: {verdict}",
                observation_ids=[],
            )
        )
    return items
