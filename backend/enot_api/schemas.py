"""Typed DTOs for the approved TASK-004 OpenAPI contract."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Error(DTO):
    code: str
    message: str
    request_id: str


class Login(DTO):
    login: Annotated[str, Field(min_length=1, max_length=254)]
    password: Annotated[str, Field(min_length=1, max_length=256)]

    @field_validator("login")
    @classmethod
    def valid_login(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Invalid login")
        return value


class Session(DTO):
    user_id: UUID
    csrf_token: str
    expires_at: datetime


class ProfileName(DTO):
    name: Annotated[str, Field(min_length=1, max_length=80)]

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(not char.isprintable() for char in value):
            raise ValueError("Invalid name")
        return value


class NewPassword(DTO):
    password: Annotated[str, Field(min_length=12, max_length=256)]

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        if not any(char.isalpha() for char in value) or not any(
            char.isdecimal() for char in value
        ):
            raise ValueError("Password must contain a letter and a digit")
        return value


class Registration(ProfileName, NewPassword):
    email: Annotated[EmailStr, Field(max_length=254)]


class PasswordChange(NewPassword):
    current_password: Annotated[str, Field(min_length=1, max_length=256)]


class Profile(DTO):
    name: str
    email: str | None


class CatalogFilters(DTO):
    country: Annotated[str, Field(pattern="^[A-Z]{2}$")] | None = None
    region: Annotated[str, Field(max_length=32)] | None = None
    industry: Annotated[str, Field(max_length=64)] | None = None
    budget_rub: Annotated[int, Field(ge=0, le=1000000000000, strict=True)] | None = None
    include_unknown_budget: Annotated[bool, Field(strict=True)] = False

    @field_validator("country", "region", "industry", "budget_rub")
    @classmethod
    def present_value(cls, value):
        if value is None or (isinstance(value, str) and "\x00" in value):
            raise ValueError("Filter must contain a valid value")
        return value

    @model_validator(mode="after")
    def check_geography(self):
        if self.region is not None and self.country is None:
            raise ValueError("country is required with region")
        return self


class Model(DTO):
    version: str
    calculator_commit: str
    calculator_sha256: str
    criteria_order: list[str]
    weights: list[Annotated[int, Field(ge=0)]]
    published_at: datetime


class Score(DTO):
    id: UUID
    model_version: str
    lower: Annotated[float, Field(ge=0, le=100)]
    upper: Annotated[float, Field(ge=0, le=100)]
    coverage: Annotated[float, Field(ge=0, le=100)]
    confidence: Annotated[float, Field(ge=0, le=100)]
    rank_from: Annotated[int, Field(ge=1)]
    rank_to: Annotated[int, Field(ge=1)]
    calculated_at: datetime


class Market(DTO):
    country: str
    region: str | None
    name: str


class Dataset(DTO):
    id: UUID
    version: str
    published_at: datetime
    markets: list[Market]
    industries: list[str]


class Niche(DTO):
    id: UUID
    legacy_code: str
    dataset_id: UUID
    title: str
    market: Market
    industry: str
    segment: str
    updated_at: datetime
    score: Score
    start_min: Annotated[int, Field(ge=0)] | None
    start_max: Annotated[int, Field(ge=0)] | None


class SourceVersion(DTO):
    id: UUID
    source_code: str
    publisher: str
    title: str
    kind: str
    version: str
    url: HttpUrl
    published_on: date | None
    retrieved_on: date
    retrieved_at: datetime | None
    availability: Literal["readable", "unavailable", "shell"]
    access_mode: str
    license_note: str
    caveats: str


class Observation(DTO):
    id: UUID
    source_version_id: UUID | None
    market: Market
    kind: Literal["fact", "calculation", "estimate", "hypothesis"]
    metric: str
    value: float | None
    text_value: str | None
    unit: str | None
    currency: str | None
    basis: str | None
    period_start: date | None
    period_end: date | None
    period_label: str
    period_precision: Literal["day", "month", "quarter", "year", "range", "unknown"]
    population: str
    locator: str
    method_version: str
    limitations: str
    input_ids: list[UUID]


class Evidence(DTO):
    id: UUID
    observation: Observation
    relation: Literal["supports", "qualifies", "contradicts"]
    locator: str
    note: str


class Claim(DTO):
    id: UUID
    section: Literal["demand", "competition", "risk", "economics", "criterion", "gap"]
    kind: Literal["fact", "calculation", "estimate", "hypothesis"]
    statement: str
    gap_reason: str | None
    evidence: list[Evidence]


class Criterion(DTO):
    code: Literal["D", "U", "C", "P", "I", "S", "R"]
    rating: Annotated[int, Field(ge=1, le=5)] | None
    quality: Annotated[int, Field(ge=0, le=3)]
    claim_ids: list[UUID]
    gap_reason: str | None


FinanceInput = Annotated[int, Field(ge=0, le=10_000_000, strict=True)]


class FinanceInputs(DTO):
    price: FinanceInput
    variable: FinanceInput
    fixed: FinanceInput
    volume: FinanceInput


class FinanceCalculation(DTO):
    revenue: int
    variable_total: int
    fixed: int
    contribution: int
    unit_margin: int
    break_even: int | None


class Finance(DTO):
    code: Literal[
        "low",
        "base",
        "high",
        "price_down_25",
        "price_up_25",
        "volume_down_25",
        "volume_up_25",
        "cost_down_50",
        "cost_up_50",
    ]
    finance_version: str
    currency: Literal["RUB"]
    unit: str
    price: Annotated[int, Field(ge=0)]
    variable: Annotated[int, Field(ge=0)]
    fixed: Annotated[int, Field(ge=0)]
    volume: Annotated[int, Field(ge=0)]
    start_min: Annotated[int, Field(ge=0)]
    start_max: Annotated[int, Field(ge=0)]
    revenue: Annotated[int, Field(ge=0)]
    variable_total: Annotated[int, Field(ge=0)]
    contribution: int
    unit_margin: int
    break_even: Annotated[int, Field(ge=0)] | None
    basis_kind: Literal["estimate", "hypothesis"]
    calculated_at: datetime


class NicheDetail(DTO):
    niche: Niche
    criteria: Annotated[list[Criterion], Field(min_length=7, max_length=7)]
    claims: list[Claim]
    finance: list[Finance]
    finance_gap: str | None


class Recalculate(DTO):
    dataset_id: UUID
    model_version: Literal["2.0-pilot"]


class Selection(DTO):
    dataset_id: UUID
    model_version: Literal["2.0-pilot"]
    niche_ids: Annotated[list[UUID], Field(min_length=1, max_length=5)]

    @field_validator("niche_ids")
    @classmethod
    def unique_niche_ids(cls, ids: list[UUID]) -> list[UUID]:
        if len(set(ids)) != len(ids):
            raise ValueError("IDs must be unique")
        return ids


class CompareRequest(DTO):
    dataset_id: UUID
    model_version: Literal["2.0-pilot"]
    niche_ids: Annotated[list[UUID], Field(min_length=2, max_length=5)]

    @field_validator("niche_ids")
    @classmethod
    def unique_niche_ids(cls, ids: list[UUID]) -> list[UUID]:
        if len(set(ids)) != len(ids):
            raise ValueError("IDs must be unique")
        return ids


class Comparison(DTO):
    dataset_id: UUID
    model_version: str
    items: Annotated[list[NicheDetail], Field(min_length=2, max_length=5)]
    warnings: list[str]


class ProjectCreate(DTO):
    title: Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[^\x00]+$")]
    filters: CatalogFilters


class Project(DTO):
    id: UUID
    title: str
    filters: CatalogFilters
    created_at: datetime
    updated_at: datetime


class ReportCreate(DTO):
    dataset_id: UUID
    model_version: Literal["2.0-pilot"]
    niche_ids: Annotated[list[UUID], Field(min_length=1, max_length=5)]
    filters: CatalogFilters
    interpretation_id: UUID | None

    @field_validator("niche_ids")
    @classmethod
    def unique_niche_ids(cls, ids: list[UUID]) -> list[UUID]:
        if len(set(ids)) != len(ids):
            raise ValueError("IDs must be unique")
        return ids


class ReportSummary(DTO):
    id: UUID
    project_id: UUID
    dataset_id: UUID
    model_version: str
    version: Annotated[int, Field(ge=0)]
    created_at: datetime


class Statement(DTO):
    kind: Literal["fact", "calculation", "estimate", "hypothesis"]
    statement: str
    observation_ids: list[UUID]

    @field_validator("observation_ids")
    @classmethod
    def unique_observation_ids(cls, ids: list[UUID]) -> list[UUID]:
        if len(set(ids)) != len(ids):
            raise ValueError("IDs must be unique")
        return ids


class Interpretation(DTO):
    id: UUID
    project_id: UUID
    status: Literal[
        "queued", "running", "succeeded", "insufficient_data", "fallback", "failed"
    ]
    status_url: str
    items: list[Statement]
    gaps: list[str]
    provider: str | None
    model: str | None
    prompt_version: str
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class Report(DTO):
    id: UUID
    project_id: UUID
    dataset_id: UUID
    model_version: str
    version: Annotated[int, Field(ge=0)]
    created_at: datetime
    filters: CatalogFilters
    items: Annotated[list[NicheDetail], Field(min_length=1, max_length=5)]
    sources: list[SourceVersion]
    interpretation: Interpretation | None
    sha256: str


class NichePage(DTO):
    items: list[Niche]
    next_cursor: str | None
    dataset_id: UUID
    model_version: str
    updated_at: datetime


class SourcePage(DTO):
    items: list[SourceVersion]
    next_cursor: str | None


class ProjectPage(DTO):
    items: list[Project]
    next_cursor: str | None


class ReportPage(DTO):
    items: list[ReportSummary]
    next_cursor: str | None
