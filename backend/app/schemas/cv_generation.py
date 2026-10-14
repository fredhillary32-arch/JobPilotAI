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
    created_at: datetime


SourceType = Literal[
    "profile_field",
    "skill",
    "work_experience",
    "education",
    "candidate_evidence",
]


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
]


class CVSection(BaseModel):
    heading: CVSectionHeading
    claims: list[CVClaim] = Field(default_factory=list)
    roles: list[CVRole] = Field(default_factory=list)


class CVStructuredContent(BaseModel):
    candidate_name: str
    professional_heading: str
    header_source_references: list[CVSourceReference] = Field(min_length=1)
    sections: list[CVSection]


class CVValidationResults(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

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
    status: Literal["generated", "failed"]
    generated_content: str | None
    structured_content: CVStructuredContent | None
    validation_results: CVValidationResults
    source_references: list[CVSourceReference]
    created_at: datetime
