from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

EligibilityStatus = Literal["eligible_confirmed", "not_eligible", "eligibility_unknown"]
EvidenceField = Literal["description", "location"]
StatementScope = Literal["role", "company", "team", "market_or_customer", "unclear"]
RoleApplicability = Literal["direct", "established_by_wording", "unclear", "not_applicable"]
GeographicScope = Literal[
    "kenya_named", "africa", "emea", "worldwide", "other_countries", "restricted",
    "conflicting", "unclear", "awaiting_employer",
]
SCOPES_BY_OUTCOME = {
    "eligible_confirmed": ("kenya_named", "africa", "emea", "worldwide"),
    "not_eligible": ("other_countries", "restricted"),
    "eligibility_unknown": ("conflicting", "unclear", "awaiting_employer"),
}


class EligibilityAssessmentRead(BaseModel):
    """Effective Kenya eligibility: a JobPilot conclusion, never a source fact."""

    status: EligibilityStatus = "eligibility_unknown"
    reason: str = "Eligibility for Kenya-based applicants has not been assessed."
    currency: Literal["not_assessed", "current", "stale"] = "not_assessed"
    previous_status: EligibilityStatus | None = None
    assessment_id: UUID | None = None
    assessed_at: datetime | None = None
    explanation: str | None = None
    quotation: str | None = None
    evidence_field: EvidenceField | None = None
    statement_scope: StatementScope | None = None
    role_applicability: RoleApplicability | None = None
    geographic_scope: GeographicScope | None = None


class EligibilityAssessmentCreate(BaseModel):
    outcome: EligibilityStatus
    explanation: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
    # Not stripped: a quotation must match the source text exactly.
    quotation: Annotated[str, StringConstraints(min_length=1, max_length=5_000)] | None = None
    evidence_field: EvidenceField | None = None
    statement_scope: StatementScope | None = None
    role_applicability: RoleApplicability | None = None
    # What the wording establishes (Kenya named, Africa, worldwide, restricted, conflicting, ...).
    geographic_scope: GeographicScope | None = None

    @model_validator(mode="after")
    def require_evidence_for_definite_outcomes(self) -> "EligibilityAssessmentCreate":
        if self.geographic_scope is not None and self.geographic_scope not in SCOPES_BY_OUTCOME[self.outcome]:
            raise ValueError(f"A {self.geographic_scope} scope does not fit the result {self.outcome}.")
        if self.quotation is not None and self.evidence_field is None:
            raise ValueError("Say whether the quotation comes from the description or the location.")
        if self.outcome == "eligibility_unknown":
            return self
        if self.quotation is None or not self.quotation.strip():
            raise ValueError("A definite outcome needs the exact quotation that states it.")
        if self.statement_scope is None:
            raise ValueError("Record what the quoted statement is about.")
        if self.role_applicability not in ("direct", "established_by_wording"):
            raise ValueError(
                "A definite outcome needs a statement about this role, or a company-wide "
                "hiring policy whose wording covers this role."
            )
        return self


class ListingEligibilityAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_listing_id: UUID
    outcome: EligibilityStatus
    explanation: str
    quotation: str | None
    evidence_field: EvidenceField | None
    quote_start: int | None
    statement_scope: StatementScope | None
    role_applicability: RoleApplicability | None
    geographic_scope: GeographicScope | None
    listing_content_hash: str
    listing_source_updated_at: datetime | None
    listing_last_verified_at: datetime
    assessed_at: datetime


class ListingSourceRead(BaseModel):
    """Where a listing came from, as recorded in the verified source registry."""

    registered: bool
    registry_id: str | None = None
    name: str | None = None
    category: str | None = None
    official_domain: str | None = None
    verification_outcome: str | None = None
    verification_checked_at: datetime | None = None


class LinkCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    url: str
    final_url: str | None
    outcome: str
    http_status: int | None
    detail: str | None
    checked_at: datetime


class ListingLinksRead(BaseModel):
    listing: LinkCheckRead | None = None
    application: LinkCheckRead | None = None


class JobListingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_kind: str
    source_key: str
    source_listing_id: str
    source_url: str
    listing_url: str | None = None
    application_url: str
    source_category: str | None = None
    relisted_at: datetime | None = None
    employer_name: str
    title: str
    location_text: str | None
    stated_workplace_type: str | None
    stated_countries: list[str]
    posted_at: datetime | None
    source_updated_at: datetime | None
    application_deadline: date | None
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    salary_period: str | None
    source_status: str
    first_seen_at: datetime
    last_seen_at: datetime
    last_verified_at: datetime
    dedupe_key: str
    eligibility: EligibilityAssessmentRead = EligibilityAssessmentRead()
    source: ListingSourceRead = ListingSourceRead(registered=False)
    links: ListingLinksRead = ListingLinksRead()
    vacancy_status: Literal["listed_by_source", "no_longer_listed", "link_expired"] = "listed_by_source"
    duplicate_group_size: int = 1
    # Strict, evidence-based decision (app.services.kenya_eligibility); independent
    # of the candidate's own facts on this shared listing view.
    kenya_eligibility: dict | None = None
    # Support/IT role family named by the title (app.services.role_relevance), or None.
    # Independent of eligibility.
    role_match: dict | None = None
    # Where posted_at came from: the employer's own job board, a job-board aggregator's
    # publication date, or None when the source gives no date (never the discovery time).
    posted_at_source: Literal["employer_board", "job_board"] | None = None


class AlternateListingRead(BaseModel):
    id: UUID
    source_kind: str
    source_key: str
    source_category: str | None
    application_url: str
    source_status: str


class JobListingDetailRead(JobListingRead):
    description_text: str | None
    alternates: list[AlternateListingRead] = []


class JobListingPage(BaseModel):
    items: list[JobListingRead]
    total: int
    limit: int
    offset: int


class JobDiscoveryRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_kind: str
    source_key: str
    status: str
    error_category: str | None
    started_at: datetime
    finished_at: datetime | None
    fetched_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    missing_count: int
    skipped_count: int
    skip_reasons: dict[str, int] = {}
    # "interrupted" when a run is still marked running long after it started.
    display_status: str | None = None
    source_id: str | None = None
    source_name: str | None = None
