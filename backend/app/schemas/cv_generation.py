from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

JobTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
JobDescriptionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000),
]


class CandidateJobDescriptionCreate(BaseModel):
    job_title: JobTitle
    company: CompanyName | None = None
    description: JobDescriptionText
    source_url: AnyHttpUrl | None = None


class CandidateJobDescriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    job_title: str
    company: str | None
    description: str
    source_url: str | None
    source_job_listing_id: UUID | None = None
    created_at: datetime


SourceType = Literal[
    "skill_confirmation",
    "profile_field",
    "skill",
    "work_experience",
    "education",
    "certification",
    "candidate_evidence",
]
# How a claim's wording relates to its sources: copied ("source"), restated by the
# writer without adding facts ("rewritten"), assembled from several confirmed
# records ("composed"), or changed by the candidate ("candidate_edited").
ClaimOrigin = Literal["source", "rewritten", "composed", "candidate_edited"]


class CVSourceReference(BaseModel):
    source_type: SourceType
    source_id: str
    source_field: str
    claim_text: str
    source_document_id: str | None = None
    source_excerpt: str | None = None
    source_start: int | None = None
    source_end: int | None = None
    evidence_confirmation_status: Literal["candidate_confirmed"] | None = None


class CVClaim(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    source_references: list[CVSourceReference] = Field(min_length=1)
    key: str | None = None
    origin: ClaimOrigin = "source"
    change_reasons: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False
    confirmation_note: str | None = None


class CVRole(BaseModel):
    work_experience_id: UUID
    job_title: str
    employer: str
    dates: str
    bullets: list[CVClaim]
    source_references: list[CVSourceReference] = Field(min_length=1)


CVSectionHeading = Literal[
    "Professional Summary",
    "Tools and Platforms",
    "Core Skills",
    "Professional Experience",
    "Education",
    "Certifications",
]


class CVSection(BaseModel):
    heading: CVSectionHeading
    claims: list[CVClaim] = Field(default_factory=list)
    roles: list[CVRole] = Field(default_factory=list)


class CVReview(BaseModel):
    """Traceability and approval state for drafts written by the reviewed CV writer."""

    writer_version: str
    job_description_id: str
    source_document_id: str | None = None
    parent_draft_id: str | None = None
    approval_status: Literal["pending_review", "approved"] = "pending_review"
    approved_at: datetime | None = None
    attested_unconfirmed_statements: bool = False
    # Set when the candidate approved a draft that is knowingly incomplete.
    acknowledged_incomplete: bool = False
    suggestions: list[str] = Field(default_factory=list)
    ats_score: int | None = None
    ats_potential_score: int | None = None


class CVStructuredContent(BaseModel):
    candidate_name: str
    professional_heading: str
    header_source_references: list[CVSourceReference] = Field(min_length=1)
    sections: list[CVSection]
    contact_details: str = ""
    review: CVReview | None = None


class CvDraftCreate(BaseModel):
    """Optional settings for a new draft; an empty request keeps the standard writer."""

    writer: Literal["standard", "reviewed"] = "standard"
    source_document_id: UUID | None = None


class CvClaimEdit(BaseModel):
    key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]


class CvDraftRevisionCreate(BaseModel):
    edits: list[CvClaimEdit] = Field(min_length=1, max_length=60)


class CvDraftApproval(BaseModel):
    attest_unconfirmed_statements: bool = False
    # Required to approve a "needs_review" draft: the candidate accepts it as incomplete.
    acknowledge_incomplete: bool = False


class CVValidationResults(BaseModel):
    # is_valid: no integrity errors. completeness: whether the records support every part of the layout.
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    completeness: Literal["complete", "incomplete"] = "complete"
    issues: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_validity_matches_errors(self) -> "CVValidationResults":
        if self.is_valid == bool(self.errors):
            raise ValueError("is_valid must be true exactly when errors are empty")
        return self


class TailoredCvDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    job_description_id: UUID
    status: Literal["generated", "needs_review", "failed"]
    generated_content: str | None
    structured_content: CVStructuredContent | None
    validation_results: CVValidationResults
    source_references: list[CVSourceReference]
    created_at: datetime
