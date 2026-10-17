from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

EvidenceCategory = Literal[
    "employment_responsibility",
    "technical_skill",
    "project",
    "achievement",
    "qualification",
    "metric",
]
EvidenceConfirmationStatus = Literal["unreviewed", "candidate_confirmed", "rejected"]

Description = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
Excerpt = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
]


class CandidateEvidenceCreate(BaseModel):
    source_document_id: UUID
    category: EvidenceCategory
    description: Description
    source_excerpt: Excerpt | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, gt=0)
    source_section: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None

    @model_validator(mode="after")
    def validate_source_reference(self) -> "CandidateEvidenceCreate":
        if (self.source_start is None) != (self.source_end is None):
            raise ValueError("source_start and source_end must be provided together")
        if self.source_start is None and self.source_excerpt is None:
            raise ValueError("A source excerpt or source offsets are required")
        if self.source_start is not None and self.source_end is not None and self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        return self


class CandidateEvidenceUpdate(BaseModel):
    category: EvidenceCategory | None = None
    description: Description | None = None
    source_excerpt: Excerpt | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, gt=0)
    source_section: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    confirmation_status: EvidenceConfirmationStatus | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "CandidateEvidenceUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field_name in ("category", "description", "confirmation_status"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} must not be null")
        if (self.source_start is None) != (self.source_end is None):
            raise ValueError("source_start and source_end must be provided together")
        if self.source_start is not None and self.source_end is not None and self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        return self


class CandidateEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    source_document_id: UUID
    category: EvidenceCategory
    description: str
    source_excerpt: str | None
    source_start: int | None
    source_end: int | None
    source_section: str | None
    confirmation_status: EvidenceConfirmationStatus
    created_at: datetime
    updated_at: datetime
    # False when the document's current extracted text no longer has this excerpt
    # at these offsets (for example after a failed or changed re-extraction).
    source_current: bool = True


class EvidenceSuggestionsRead(BaseModel):
    created: int
    skipped_existing: int
    limited: bool
    evidence: list[CandidateEvidenceRead]
