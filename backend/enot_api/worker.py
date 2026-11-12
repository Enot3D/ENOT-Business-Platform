from datetime import UTC, timedelta
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.orm import Session

from . import models as m
from .analyst import (
    PROMPT_VERSION,
    Selection,
    build_context,
    render,
    validate_selection,
)
from .db import now, session_factory, transaction_lock
from .llm import (
    INPUT_LIMIT,
    OUTPUT_LIMIT,
    External,
    ProviderError,
    external_from_env,
    fits_input_limit,
    messages,
)


def finish(db, job, status, *, items=(), gaps=(), error=None, audit=None) -> None:
    job.status = status
    job.updated_at = now()
    job.lease_until = None
    job.lease_token = None
    job.error_code = error
    job.output_json = {
        "items": [item.model_dump(mode="json") for item in items],
        "gaps": list(gaps),
    }
    if audit is not None:
        job.output_json["audit"] = audit
    quota = db.get(
        m.AIQuota,
        (job.user_id, job.created_at.astimezone(UTC).date()),
        with_for_update=True,
    )
    if quota and job.budget_reservation:
        quota.reserved_units -= job.budget_reservation
    job.budget_reservation = 0


def owned(db: Session, job_id: UUID, lease: UUID) -> m.Interpretation | None:
    return db.scalar(
        select(m.Interpretation)
        .where(
            m.Interpretation.id == job_id,
            m.Interpretation.status == "running",
            m.Interpretation.lease_token == lease,
            m.Interpretation.lease_until > now(),
        )
        .with_for_update()
    )


def reserve_call(job_id: UUID, lease: UUID, external: External) -> str | None:
    """Persist the worst-case charge before making the single outbound attempt."""
    with session_factory().begin() as db:
        day = now().date().isoformat()
        transaction_lock(db, f"ai-provider-budget:{day}")
        job = owned(db, job_id, lease)
        if job is None or job.lease_until <= now() + timedelta(seconds=22):
            return "provider_deadline"
        usage = m.Interpretation.token_usage
        committed = db.scalar(
            select(
                func.coalesce(
                    func.sum(cast(usage["cost_micro_usd"].astext, BigInteger)), 0
                )
            ).where(usage["budget_day"].astext == day)
        )
        if committed + external.budget.maximum > external.budget.daily:
            return "provider_budget_exhausted"
        job.token_usage = {
            "budget_day": day,
            "cost_micro_usd": external.budget.maximum,
            "state": "reserved",
            "provider": external.provider.name,
            "model": external.provider.model,
        }
    return None


def work_once(external: External | None = None) -> bool:
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

    try:
        context = build_context(job)
    except KeyError:
        with session_factory().begin() as db:
            running = owned(db, job.id, lease)
            if running is not None:
                finish(
                    db,
                    running,
                    "failed",
                    error="context_unavailable",
                    gaps=("Снимок аналитики недоступен для интерпретации.",),
                )
        return True

    status, error = "insufficient_data", None
    selected = []
    usage = None
    if context.evidence:
        status, error = "fallback", "provider_disabled"
        if job.prompt_version == PROMPT_VERSION:
            try:
                external = external if external is not None else external_from_env()
            except (ValueError, KeyError):
                error = "provider_misconfigured"
            else:
                if external is not None:
                    request = messages(context.evidence)
                    error = (
                        reserve_call(job.id, lease, external)
                        if fits_input_limit(request)
                        else "provider_input_limit"
                    )
                    if error is None:
                        try:
                            reply = external.provider.complete(request)
                            usage = reply.usage
                            if (
                                usage.prompt_tokens > INPUT_LIMIT
                                or usage.completion_tokens > OUTPUT_LIMIT
                            ):
                                error = "provider_token_limit"
                            else:
                                proposed = Selection.model_validate_json(
                                    reply.content or ""
                                )
                                selected = validate_selection(
                                    proposed, context.evidence
                                )
                                status = "succeeded"
                        except (
                            ProviderError,
                            TimeoutError,
                            ConnectionError,
                            ValueError,
                        ):
                            error = "adapter_unavailable"

    with session_factory().begin() as db:
        running = owned(db, job.id, lease)
        if running is not None:
            if usage is not None and external is not None:
                running.token_usage = {
                    **running.token_usage,
                    **usage.model_dump(),
                    "cost_micro_usd": external.budget.cost(
                        usage.prompt_tokens, usage.completion_tokens
                    ),
                    "state": "estimated_from_usage",
                }
            if status == "succeeded":
                running.provider = external.provider.name
                running.model = external.provider.model
            finish(
                db,
                running,
                status,
                items=render(context, selected) if context.evidence else (),
                gaps=context.gaps,
                error=error,
                audit={
                    "renderer_version": PROMPT_VERSION,
                    "context_sha256": context.digest(),
                    "evidence_ids": [str(row.link.id) for row in selected],
                },
            )
    return True
