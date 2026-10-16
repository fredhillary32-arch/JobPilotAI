from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EligibilityAssessmentRead(BaseModel):
    # Eligibility is a JobPilot conclusion, not a source fact; no checks exist yet.
    status: Literal["unknown"] = "unknown"
    reason: str = "Eligibility for Kenya-based applicants has not been assessed."


class JobListingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_kind: str
    source_key: str
    source_listing_id: str
    source_url: str
    application_url: str
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


class JobListingDetailRead(JobListingRead):
    description_text: str | None


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
