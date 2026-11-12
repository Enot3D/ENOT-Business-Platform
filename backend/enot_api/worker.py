from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import Field, ValidationError
from sqlalchemy import select

from . import models as m
from . import schemas as s
from .catalog import detail, entries
from .db import now, session_factory


@dataclass(frozen=True)
class InterpretationContext:
    prompt_version: str
    observations: tuple[s.Observation, ...]
    gaps: tuple[str, ...]


class Candidate(s.DTO):
    observation_ids: list[UUID] = Field(min_length=1, max_length=12)
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    usage: dict[str, int] = Field(default_factory=dict)


class InterpretationAdapter(Protocol):
    def select_observations(self, context: InterpretationContext) -> Candidate:
        """Return only references to approved observations. The server writes the statements."""
        ...


def build_context(job: m.Interpretation) -> InterpretationContext:
    with session_factory()() as db:
        by_result = {
            str(entry.result.id): entry
            for entry in entries(db, job.dataset_id).values()
            if entry.result.scoring_model_id == job.scoring_model_id
        }
        details = [
            detail(db, by_result[result_id]) for result_id in job.score_result_ids
        ]
    observations = {}
    gaps = []
    for item in details:
        for claim in item.claims:
            if claim.gap_reason:
                gaps.append(f"№{item.niche.legacy_code}. {claim.gap_reason}")
            for link in claim.evidence:
                obs = link.observation
                if obs.kind == "fact" and obs.source_version_id and obs.text_value:
                    observations.setdefault(obs.id, obs)
    return InterpretationContext(
        job.prompt_version, tuple(observations.values()), tuple(gaps)
    )


def finish(db, job, status, *, items=(), gaps=(), error=None, candidate=None) -> None:
    job.status = status
    job.updated_at = now()
    job.lease_until = None
    job.lease_token = None
    job.error_code = error
    job.output_json = {
        "items": [item.model_dump(mode="json") for item in items],
        "gaps": list(gaps),
    }
    if candidate:
        job.provider, job.model, job.token_usage = (
            candidate.provider,
            candidate.model,
            candidate.usage,
        )
    quota = db.get(
        m.AIQuota,
        (job.user_id, job.created_at.astimezone(UTC).date()),
        with_for_update=True,
    )
    if quota and job.budget_reservation:
        quota.reserved_units -= job.budget_reservation
    job.budget_reservation = 0


def work_once(adapter: InterpretationAdapter | None = None) -> bool:
    with session_factory().begin() as db:
        stamp = now()
        expired = db.scalar(
            select(m.Interpretation)
            .where(
                m.Interpretation.status == "running",
                m.Interpretation.lease_until <= stamp,
            )
            .order_by(m.Interpretation.lease_until)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if expired is not None:
            finish(
                db,
                expired,
                "failed",
                error="lease_expired",
                gaps=("Задача прервана. Аналитика доступна.",),
            )
            return True
        job = db.scalar(
            select(m.Interpretation)
            .where(m.Interpretation.status == "queued")
            .order_by(m.Interpretation.created_at, m.Interpretation.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return False
        lease = uuid4()
        job.status = "running"
        job.updated_at = stamp
        job.lease_until = stamp + timedelta(seconds=30)
        job.lease_token = lease
        job.attempts += 1

    context = build_context(job)
    allowed = {obs.id: obs for obs in context.observations}
    status, error, candidate = "insufficient_data", None, None
    chosen = []
    if allowed:
        status, error = "fallback", "provider_disabled"
        chosen = list(allowed)[:6]
        if adapter is not None:
            try:
                proposed = Candidate.model_validate(
                    adapter.select_observations(context)
                )
                if (
                    len(set(proposed.observation_ids)) != len(proposed.observation_ids)
                    or not set(proposed.observation_ids) <= allowed.keys()
                ):
                    raise ValueError("Unknown or repeated observation")
                candidate = proposed
                status, error, chosen = "succeeded", None, proposed.observation_ids
            except (ValidationError, ValueError, TimeoutError, ConnectionError):
                error = "adapter_unavailable"
    items = [
        s.Statement(
            kind=allowed[key].kind,
            statement=allowed[key].text_value,
            observation_ids=[key],
        )
        for key in chosen
    ]
    with session_factory().begin() as db:
        running = db.scalar(
            select(m.Interpretation)
            .where(
                m.Interpretation.id == job.id,
                m.Interpretation.status == "running",
                m.Interpretation.lease_token == lease,
                m.Interpretation.lease_until > now(),
            )
            .with_for_update()
        )
        if running is not None:
            finish(
                db,
                running,
                status,
                items=items,
                gaps=context.gaps,
                error=error,
                candidate=candidate,
            )
    return True
