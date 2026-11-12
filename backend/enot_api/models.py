from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .db import now


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True), dict: JSONB, list: JSONB}


class Row(Base):
    __abstract__ = True
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class User(Row):
    __tablename__ = "users"
    login: Mapped[str] = mapped_column(String(128), unique=True)
    password_hash: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class SessionRecord(Row):
    __tablename__ = "sessions"
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class RateLimit(Base):
    __tablename__ = "request_rate_limits"
    key: Mapped[str] = mapped_column(primary_key=True)
    window: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    count: Mapped[int]


class Market(Row):
    __tablename__ = "markets"
    __table_args__ = (
        UniqueConstraint(
            "country_code", "region_code", postgresql_nulls_not_distinct=True
        ),
    )
    country_code: Mapped[str] = mapped_column(String(2))
    region_code: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str]


class Niche(Row):
    __tablename__ = "business_niches"
    legacy_code: Mapped[str] = mapped_column(String(2), unique=True)
    slug: Mapped[str] = mapped_column(unique=True)


class Dataset(Row):
    __tablename__ = "dataset_versions"
    version: Mapped[str] = mapped_column(unique=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    source_commit: Mapped[str]
    published_at: Mapped[datetime]
    manifest_json: Mapped[dict]
    importer_version: Mapped[str]


class NicheRevision(Row):
    __tablename__ = "niche_revisions"
    __table_args__ = (UniqueConstraint("dataset_id", "niche_id"),)
    niche_id: Mapped[UUID] = mapped_column(ForeignKey("business_niches.id"))
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("dataset_versions.id"))
    market_id: Mapped[UUID] = mapped_column(ForeignKey("markets.id"))
    title: Mapped[str]
    industry_code: Mapped[str]
    segment: Mapped[str]
    summary: Mapped[str]
    updated_at: Mapped[datetime]


class Source(Row):
    __tablename__ = "data_sources"
    source_code: Mapped[str] = mapped_column(String(3), unique=True)
    publisher: Mapped[str]
    title: Mapped[str]
    kind: Mapped[str]


class SourceVersion(Row):
    __tablename__ = "source_versions"
    __table_args__ = (UniqueConstraint("source_id", "version"),)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"))
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_versions.id"), index=True
    )
    version: Mapped[str]
    url: Mapped[str]
    published_on: Mapped[date | None]
    retrieved_on: Mapped[date]
    retrieved_at: Mapped[datetime | None]
    availability: Mapped[str]
    access_mode: Mapped[str]
    license_note: Mapped[str]
    caveats: Mapped[str]
    artifact_locator: Mapped[str | None]
    sha256: Mapped[str | None]
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_versions.id"))


class Observation(Row):
    __tablename__ = "observations"
    __table_args__ = (
        CheckConstraint("kind <> 'fact' OR source_version_id IS NOT NULL"),
        CheckConstraint("value IS NOT NULL OR text_value IS NOT NULL"),
    )
    source_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_versions.id")
    )
    market_id: Mapped[UUID] = mapped_column(ForeignKey("markets.id"))
    kind: Mapped[str]
    metric: Mapped[str]
    value: Mapped[Decimal | None] = mapped_column(Numeric)
    text_value: Mapped[str | None]
    unit: Mapped[str | None]
    currency: Mapped[str | None]
    basis: Mapped[str | None]
    period_start: Mapped[date | None]
    period_end: Mapped[date | None]
    period_label: Mapped[str]
    period_precision: Mapped[str]
    population: Mapped[str]
    locator: Mapped[str]
    method_version: Mapped[str]
    limitations: Mapped[str]
    input_ids: Mapped[list]


class Claim(Row):
    __tablename__ = "claims"
    niche_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("niche_revisions.id"), index=True
    )
    section: Mapped[str]
    kind: Mapped[str]
    statement: Mapped[str]
    gap_reason: Mapped[str | None]


class Evidence(Row):
    __tablename__ = "evidence"
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id"), index=True)
    observation_id: Mapped[UUID] = mapped_column(
        ForeignKey("observations.id"), index=True
    )
    relation: Mapped[str]
    locator: Mapped[str]
    reviewer: Mapped[str]
    reviewed_at: Mapped[datetime]
    note: Mapped[str]


class ScoringModel(Row):
    __tablename__ = "scoring_models"
    version: Mapped[str] = mapped_column(unique=True)
    calculator_commit: Mapped[str]
    calculator_sha256: Mapped[str]
    rubric_json: Mapped[dict]
    criteria_order: Mapped[list]
    weights_json: Mapped[list]
    runtime_version: Mapped[str]
    published_at: Mapped[datetime]


class ScoreResult(Row):
    __tablename__ = "score_results"
    __table_args__ = (
        UniqueConstraint("niche_revision_id", "scoring_model_id", "input_hash"),
    )
    niche_revision_id: Mapped[UUID] = mapped_column(ForeignKey("niche_revisions.id"))
    scoring_model_id: Mapped[UUID] = mapped_column(ForeignKey("scoring_models.id"))
    input_hash: Mapped[str] = mapped_column(String(64))
    inputs_json: Mapped[dict]
    lower_num: Mapped[int | None]
    lower_den: Mapped[int | None]
    upper_num: Mapped[int | None]
    upper_den: Mapped[int | None]
    confidence_num: Mapped[int | None]
    confidence_den: Mapped[int | None]
    coverage_num: Mapped[int | None]
    coverage_den: Mapped[int | None]
    legacy_score: Mapped[Decimal | None] = mapped_column(Numeric)
    calculated_at: Mapped[datetime]


class FinancialScenario(Row):
    __tablename__ = "financial_scenarios"
    __table_args__ = (UniqueConstraint("score_result_id", "scenario_code"),)
    score_result_id: Mapped[UUID] = mapped_column(ForeignKey("score_results.id"))
    scenario_code: Mapped[str]
    input_hash: Mapped[str] = mapped_column(String(64))
    finance_version: Mapped[str]
    currency: Mapped[str] = mapped_column(String(3))
    unit: Mapped[str]
    price: Mapped[int] = mapped_column(BigInteger)
    variable: Mapped[int] = mapped_column(BigInteger)
    fixed: Mapped[int] = mapped_column(BigInteger)
    volume: Mapped[int] = mapped_column(BigInteger)
    start_min: Mapped[int] = mapped_column(BigInteger)
    start_max: Mapped[int] = mapped_column(BigInteger)
    revenue: Mapped[int] = mapped_column(BigInteger)
    variable_total: Mapped[int] = mapped_column(BigInteger)
    contribution: Mapped[int] = mapped_column(BigInteger)
    unit_margin: Mapped[int] = mapped_column(BigInteger)
    break_even: Mapped[int | None] = mapped_column(BigInteger)
    basis_kind: Mapped[str]
    calculated_at: Mapped[datetime]


class Project(Row):
    __tablename__ = "research_projects"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        Index("ix_project_owner_time", "user_id", "updated_at", "id"),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(120))
    filters_json: Mapped[dict]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Interpretation(Row):
    __tablename__ = "ai_interpretations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
        ),
        UniqueConstraint("id", "project_id", "dataset_id", "scoring_model_id"),
        Index("ix_interpretation_queue", "status", "created_at"),
        Index(
            "uq_interpretation_active",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
        ),
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[UUID]
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("dataset_versions.id"))
    scoring_model_id: Mapped[UUID] = mapped_column(ForeignKey("scoring_models.id"))
    score_result_ids: Mapped[list]
    input_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str]
    status: Mapped[str]
    prompt_version: Mapped[str]
    provider: Mapped[str | None]
    model: Mapped[str | None]
    output_json: Mapped[dict | None]
    error_code: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None]
    lease_token: Mapped[UUID | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    token_usage: Mapped[dict | None]
    budget_reservation: Mapped[int | None]


class Report(Row):
    __tablename__ = "research_reports"
    __table_args__ = (
        UniqueConstraint("project_id", "version"),
        ForeignKeyConstraint(
            ["interpretation_id", "project_id", "dataset_id", "scoring_model_id"],
            [
                "ai_interpretations.id",
                "ai_interpretations.project_id",
                "ai_interpretations.dataset_id",
                "ai_interpretations.scoring_model_id",
            ],
        ),
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("research_projects.id"))
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("dataset_versions.id"))
    scoring_model_id: Mapped[UUID] = mapped_column(ForeignKey("scoring_models.id"))
    version: Mapped[int]
    filters_snapshot: Mapped[dict]
    snapshot_json: Mapped[dict]
    sha256: Mapped[str] = mapped_column(String(64))
    interpretation_id: Mapped[UUID | None]
    created_at: Mapped[datetime]


class ReportScore(Base):
    __tablename__ = "report_scores"
    __table_args__ = (UniqueConstraint("report_id", "position"),)
    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_reports.id"), primary_key=True
    )
    score_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("score_results.id"), primary_key=True
    )
    position: Mapped[int]


class AIQuota(Base):
    __tablename__ = "ai_quota_daily"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    quota_day: Mapped[date] = mapped_column(primary_key=True)
    requests: Mapped[int]
    reserved_units: Mapped[int]
    spent_units: Mapped[int]


class Idempotency(Row):
    __tablename__ = "request_idempotency"
    __table_args__ = (UniqueConstraint("user_id", "operation", "scope_id", "key"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    operation: Mapped[str]
    scope_id: Mapped[UUID]
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID]
    status_code: Mapped[int]
    created_at: Mapped[datetime]
