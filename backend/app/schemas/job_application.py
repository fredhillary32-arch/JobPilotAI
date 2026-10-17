from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints

ApplicationStatus = Literal[
    "saved",
    "eligibility_review",
    "preparing",
    "ready_for_review",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
    "closed",
]
InitialApplicationStatus = Literal["saved", "eligibility_review", "preparing", "ready_for_review", "applied"]
ContactName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ApplicationNotes = Annotated[str, StringConstraints(min_length=1, max_length=10_000)]
EventNote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]


class JobApplicationCreate(BaseModel):
    job_description_id: UUID
    status: InitialApplicationStatus = "saved"
    applied_on: date | None = None
    cv_draft_id: UUID | None = None
    deadline_on: date | None = None
    follow_up_on: date | None = None
    contact_name: ContactName | None = None
    contact_email: EmailStr | None = None
    notes: ApplicationNotes | None = None


class JobApplicationUpdate(BaseModel):
    """Only fields present in the request change; null clears a field."""

    cv_draft_id: UUID | None = None
    deadline_on: date | None = None
    follow_up_on: date | None = None
    contact_name: ContactName | None = None
    contact_email: EmailStr | None = None
    notes: ApplicationNotes | None = None


class JobApplicationStatusChange(BaseModel):
    status: ApplicationStatus
    applied_on: date | None = None
    note: EventNote | None = None


class JobApplicationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    note: str | None
    occurred_at: datetime


class JobApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    job_description_id: UUID
    cv_draft_id: UUID | None
    status: ApplicationStatus
    applied_on: date | None
    deadline_on: date | None
    follow_up_on: date | None
    contact_name: str | None
    contact_email: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    allowed_next_statuses: list[ApplicationStatus]
    events: list[JobApplicationEventRead]
