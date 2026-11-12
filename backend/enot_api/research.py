from datetime import datetime
from typing import TypeVar
from uuid import UUID, uuid4

from fastapi import APIRouter, Response
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from . import models as m
from . import schemas as s
from .catalog import (
    Cursor,
    Limit,
    columns,
    detail,
    selected,
    source_view,
    sources_query,
)
from .db import now, transaction_lock
from .scoring import fingerprint
from .security import (
    APIError,
    Current,
    Db,
    KeyHeader,
    PREFIX,
    Writer,
    decode_cursor,
    encode_cursor,
    missing,
)

router = APIRouter()
EMPTY_SCOPE = UUID(int=0)
PROMPT_VERSION = "task-005-local-v1"
TERMINAL = {"succeeded", "insufficient_data", "fallback", "failed"}
Resource = TypeVar("Resource", m.Project, m.Report, m.Interpretation)


def project_row(
    db: Session, user_id: UUID, project_id: UUID, lock: bool = False
) -> m.Project:
    query = select(m.Project).where(
        m.Project.id == project_id, m.Project.user_id == user_id
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise missing()
    return row


def project_view(row: m.Project) -> s.Project:
    return columns(
        row, s.Project, filters=s.CatalogFilters.model_validate(row.filters_json)
    )


def write_resource(
    db: Session,
    user_id: UUID,
    operation: str,
    scope: UUID,
    key: str,
    request: s.DTO,
    model: type[Resource],
    status: int,
    create,
) -> Resource:
    request_hash = fingerprint(request.model_dump(mode="json", exclude_none=True))
    transaction_lock(db, f"request:{user_id}:{operation}:{scope}:{key}")
    existing = db.scalar(
        select(m.Idempotency).where(
            m.Idempotency.user_id == user_id,
            m.Idempotency.operation == operation,
            m.Idempotency.scope_id == scope,
            m.Idempotency.key == key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise APIError(
                409, "idempotency_conflict", "Key already used with a different request"
            )
        return db.get(model, existing.resource_id)
    item = create()
    db.flush()
    db.add(
        m.Idempotency(
            user_id=user_id,
            operation=operation,
            scope_id=scope,
            key=key,
            request_hash=request_hash,
            resource_id=item.id,
            status_code=status,
            created_at=now(),
        )
    )
    db.commit()
    return item


def project_url(project_id: UUID) -> str:
    return f"{PREFIX}/research-projects/{project_id}"


def interpretation_view(row: m.Interpretation) -> s.Interpretation:
    output = row.output_json or {}
    return columns(
        row,
        s.Interpretation,
        status_url=f"{project_url(row.project_id)}/interpretations/{row.id}",
        items=output.get("items", []),
        gaps=output.get("gaps", []),
    )


@router.post(
    "/research-projects",
    operation_id="createProject",
    status_code=201,
    response_model_exclude_unset=True,
)
def create_project(
    body: s.ProjectCreate, response: Response, db: Db, auth: Writer, key: KeyHeader
) -> s.Project:
    def create() -> m.Project:
        stamp = now()
        item = m.Project(
            user_id=auth.user_id,
            title=body.title,
            filters_json=body.filters.model_dump(exclude_none=True),
            created_at=stamp,
            updated_at=stamp,
        )
        db.add(item)
        return item

    row = write_resource(
        db,
        auth.user_id,
        "createProject",
        EMPTY_SCOPE,
        key,
        body,
        m.Project,
        201,
        create,
    )
    response.headers["Location"] = project_url(row.id)
    return project_view(row)


@router.get(
    "/research-projects", operation_id="listProjects", response_model_exclude_unset=True
)
def list_projects(
    db: Db, auth: Current, cursor: Cursor = None, limit: Limit = 20
) -> s.ProjectPage:
    binding = str(auth.user_id)
    last, _ = decode_cursor(cursor, "projects", binding)
    statement = select(m.Project).where(m.Project.user_id == auth.user_id)
    if last:
        anchor = project_row(db, auth.user_id, last)
        statement = statement.where(
            tuple_(m.Project.updated_at, m.Project.id) < (anchor.updated_at, anchor.id)
        )
    rows = db.scalars(
        statement.order_by(m.Project.updated_at.desc(), m.Project.id.desc()).limit(
            limit + 1
        )
    ).all()
    end = (
        encode_cursor("projects", binding, rows[limit - 1].id)
        if len(rows) > limit
        else None
    )
    return s.ProjectPage(
        items=[project_view(row) for row in rows[:limit]], next_cursor=end
    )


@router.get(
    "/research-projects/{project_id}",
    operation_id="getProject",
    response_model_exclude_unset=True,
)
def get_project(project_id: UUID, db: Db, auth: Current) -> s.Project:
    return project_view(project_row(db, auth.user_id, project_id))


def report_row(db: Session, project_id: UUID, report_id: UUID) -> m.Report:
    row = db.scalar(
        select(m.Report).where(
            m.Report.id == report_id, m.Report.project_id == project_id
        )
    )
    if row is None:
        raise missing()
    return row


def interpretation_row(
    db: Session, project: m.Project, interpretation_id: UUID
) -> m.Interpretation:
    row = db.scalar(
        select(m.Interpretation).where(
            m.Interpretation.id == interpretation_id,
            m.Interpretation.project_id == project.id,
            m.Interpretation.user_id == project.user_id,
        )
    )
    if row is None:
        raise missing()
    return row


def report_view(row: m.Report) -> s.Report:
    if fingerprint(row.snapshot_json) != row.sha256:
        raise APIError(503, "report_unavailable", "Saved snapshot cannot be verified")
    return s.Report.model_validate({**row.snapshot_json, "sha256": row.sha256})


@router.post(
    "/research-projects/{project_id}/reports",
    operation_id="saveReport",
    status_code=201,
    response_model_exclude_unset=True,
)
def save_report(
    project_id: UUID,
    body: s.ReportCreate,
    response: Response,
    db: Db,
    auth: Writer,
    key: KeyHeader,
) -> s.Report:
    project = project_row(db, auth.user_id, project_id, lock=True)

    def create() -> m.Report:
        chosen = selected(db, body.dataset_id, body.niche_ids)
        model_id = chosen[0].result.scoring_model_id
        result_ids = [str(item.result.id) for item in chosen]
        interpretation = None
        if body.interpretation_id is not None:
            ai_row = interpretation_row(db, project, body.interpretation_id)
            if (
                ai_row.status not in TERMINAL
                or ai_row.dataset_id != body.dataset_id
                or ai_row.scoring_model_id != model_id
                or set(ai_row.score_result_ids) != set(result_ids)
            ):
                raise APIError(
                    409,
                    "incompatible_interpretation",
                    "Interpretation does not match the report",
                )
            interpretation = interpretation_view(ai_row)
        items = [detail(db, item) for item in chosen]
        source_ids = {
            link.observation.source_version_id
            for item in items
            for claim in item.claims
            for link in claim.evidence
            if link.observation.source_version_id is not None
        }
        sources = [
            source_view(*row)
            for row in db.execute(
                sources_query()
                .where(
                    m.SourceVersion.id.in_(source_ids),
                    m.SourceVersion.dataset_id == body.dataset_id,
                )
                .order_by(m.Source.source_code)
            )
        ]
        if len(sources) != len(source_ids):
            raise APIError(
                503, "report_unavailable", "Sources do not match the selected release"
            )
        version = (
            db.scalar(
                select(func.coalesce(func.max(m.Report.version), 0)).where(
                    m.Report.project_id == project_id
                )
            )
            + 1
        )
        stamp = now()
        snapshot = s.Report(
            id=uuid4(),
            project_id=project_id,
            dataset_id=body.dataset_id,
            model_version=body.model_version,
            version=version,
            created_at=stamp,
            filters=body.filters,
            items=items,
            sources=sources,
            interpretation=interpretation,
            sha256="",
        ).model_dump(mode="json", exclude={"sha256"}, exclude_unset=True)
        report = m.Report(
            id=UUID(snapshot["id"]),
            project_id=project_id,
            dataset_id=body.dataset_id,
            scoring_model_id=model_id,
            version=version,
            created_at=stamp,
            filters_snapshot=body.filters.model_dump(exclude_none=True),
            snapshot_json=snapshot,
            sha256=fingerprint(snapshot),
            interpretation_id=body.interpretation_id,
        )
        project.updated_at = stamp
        db.add(report)
        db.flush()
        db.add_all(
            [
                m.ReportScore(
                    report_id=report.id,
                    score_result_id=item.result.id,
                    position=position,
                )
                for position, item in enumerate(chosen)
            ]
        )
        return report

    row = write_resource(
        db, auth.user_id, "saveReport", project_id, key, body, m.Report, 201, create
    )
    response.headers["Location"] = f"{project_url(project_id)}/reports/{row.id}"
    return report_view(row)


@router.get("/research-projects/{project_id}/reports", operation_id="listReports")
def list_reports(
    project_id: UUID, db: Db, auth: Current, cursor: Cursor = None, limit: Limit = 20
) -> s.ReportPage:
    project_row(db, auth.user_id, project_id)
    binding = f"{auth.user_id}:{project_id}"
    last, _ = decode_cursor(cursor, "reports", binding)
    statement = (
        select(m.Report, m.ScoringModel.version)
        .join(m.ScoringModel, m.ScoringModel.id == m.Report.scoring_model_id)
        .where(m.Report.project_id == project_id)
    )
    if last:
        statement = statement.where(
            m.Report.version < report_row(db, project_id, last).version
        )
    rows = db.execute(
        statement.order_by(m.Report.version.desc()).limit(limit + 1)
    ).all()
    end = (
        encode_cursor("reports", binding, rows[limit - 1][0].id)
        if len(rows) > limit
        else None
    )
    return s.ReportPage(
        items=[
            columns(row, s.ReportSummary, model_version=version)
            for row, version in rows[:limit]
        ],
        next_cursor=end,
    )


@router.get(
    "/research-projects/{project_id}/reports/{report_id}",
    operation_id="getReport",
    response_model_exclude_unset=True,
)
def get_report(project_id: UUID, report_id: UUID, db: Db, auth: Current) -> s.Report:
    project_row(db, auth.user_id, project_id)
    return report_view(report_row(db, project_id, report_id))


def reserve_quota(db: Session, user_id: UUID, stamp: datetime) -> None:
    active = db.scalar(
        select(m.Interpretation.id)
        .where(
            m.Interpretation.user_id == user_id,
            m.Interpretation.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    if active is not None:
        raise APIError(
            429, "interpretation_active", "An interpretation is already active"
        )
    quota = db.get(m.AIQuota, (user_id, stamp.date()), with_for_update=True)
    if quota is None:
        quota = m.AIQuota(
            user_id=user_id,
            quota_day=stamp.date(),
            requests=0,
            reserved_units=0,
            spent_units=0,
        )
        db.add(quota)
    if quota.requests >= 10:
        raise APIError(
            429, "interpretation_quota", "Daily interpretation quota exhausted"
        )
    quota.requests += 1
    quota.reserved_units += 1


@router.post(
    "/research-projects/{project_id}/interpretations",
    operation_id="requestInterpretation",
    status_code=202,
)
def request_interpretation(
    project_id: UUID,
    body: s.Selection,
    response: Response,
    db: Db,
    auth: Writer,
    key: KeyHeader,
) -> s.Interpretation:
    project_row(db, auth.user_id, project_id)

    def create() -> m.Interpretation:
        transaction_lock(db, f"ai-quota:{auth.user_id}")
        chosen = selected(db, body.dataset_id, body.niche_ids)
        stamp = now()
        ids = [str(item.result.id) for item in chosen]
        input_hash = fingerprint(
            [str(body.dataset_id), body.model_version, PROMPT_VERSION, ids]
        )
        previous = db.scalar(
            select(m.Interpretation)
            .where(
                m.Interpretation.user_id == auth.user_id,
                m.Interpretation.project_id == project_id,
                m.Interpretation.input_hash == input_hash,
                m.Interpretation.status == "succeeded",
            )
            .order_by(m.Interpretation.created_at.desc())
            .limit(1)
        )
        if previous:
            return previous
        reserve_quota(db, auth.user_id, stamp)
        row = m.Interpretation(
            user_id=auth.user_id,
            project_id=project_id,
            dataset_id=body.dataset_id,
            scoring_model_id=chosen[0].result.scoring_model_id,
            score_result_ids=ids,
            input_hash=input_hash,
            idempotency_key=key,
            status="queued",
            prompt_version=PROMPT_VERSION,
            created_at=stamp,
            updated_at=stamp,
            budget_reservation=1,
        )
        db.add(row)
        return row

    row = write_resource(
        db,
        auth.user_id,
        "requestInterpretation",
        project_id,
        key,
        body,
        m.Interpretation,
        202,
        create,
    )
    output = interpretation_view(row)
    response.headers["Location"] = output.status_url
    return output


@router.get(
    "/research-projects/{project_id}/interpretations/{interpretation_id}",
    operation_id="getInterpretation",
)
def get_interpretation(
    project_id: UUID, interpretation_id: UUID, db: Db, auth: Current
) -> s.Interpretation:
    return interpretation_view(
        interpretation_row(
            db, project_row(db, auth.user_id, project_id), interpretation_id
        )
    )
