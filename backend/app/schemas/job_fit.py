from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.job_listing import EligibilityStatus


class FitSource(BaseModel):
    source_type: Literal[
        "skill",
        "certification",
        "work_experience",
        "education",
        "evidence",
        "eligibility_details",
        "work_authorization",
    ]
    source_id: str
    label: str


class FitItem(BaseModel):
    kind: Literal[
        "skill", "work_authorization", "location", "relocation", "schedule", "contradiction", "work_arrangement"
    ]
    requirement: str
    status: Literal["met", "missing", "uncertain", "disqualifier", "mismatch"]
    explanation: str
    quotation: str | None
    sources: list[FitSource]


class GeographicEligibility(BaseModel):
    status: EligibilityStatus
    currency: Literal["not_assessed", "current", "stale", "automatic"]
    listing_id: UUID | None
    reason: str
    quotation: str | None
    assessment_id: UUID | None
    assessed_at: datetime | None


class FitCoverage(BaseModel):
    met: int
    total: int
    summary: str


class JobFitRead(BaseModel):
    job_description_id: UUID
    verdict: Literal["excluded_by_employer", "potential_disqualifiers", "eligibility_unknown", "no_blockers_found"]
    headline: str
    geographic_eligibility: GeographicEligibility
    candidate_details_confirmed: bool
    candidate_country_of_residence: str | None
    coverage: FitCoverage
    matched: list[FitItem]
    missing: list[FitItem]
    uncertain: list[FitItem]
    disqualifiers: list[FitItem]
    location_requirements_met: list[FitItem]
    preferences: list[FitItem]
