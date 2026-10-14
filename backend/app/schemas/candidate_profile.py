from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NameText = Annotated[NonEmptyText, Field(max_length=200)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
AchievementText = Annotated[NonEmptyText, Field(max_length=2000)]


class CandidateProfileCreate(BaseModel):
    name: NameText
    contact_email: EmailStr | None = None
    contact_phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None
    professional_headline: Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)] | None = None
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None
    location: ShortText | None = None
    remote_work_preference: Literal["remote", "hybrid", "onsite", "flexible"] | None = None
    target_job_categories: list[NameText] = Field(default_factory=list, max_length=30)


class CandidateProfileUpdate(BaseModel):
    name: NameText | None = None
    contact_email: EmailStr | None = None
    contact_phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)] | None = None
    professional_headline: Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)] | None = None
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None
    location: ShortText | None = None
    remote_work_preference: Literal["remote", "hybrid", "onsite", "flexible"] | None = None
    target_job_categories: list[NameText] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_patch(self) -> "CandidateProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field_name in ("name", "target_job_categories"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class CandidateProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    contact_email: EmailStr | None
    contact_phone: str | None
    professional_headline: str | None
    summary: str | None
    location: str | None
    remote_work_preference: str | None
    target_job_categories: list[str]
    created_at: datetime
    updated_at: datetime


class CandidateWorkExperienceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    employer: str
    job_title: str
    location: str | None
    work_arrangement: str | None
    start_date: date
    end_date: date | None
    current_role: bool
    description: str | None
    achievements: list[str]


class CandidateEducationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    institution: str
    qualification: str
    field_of_study: str | None
    start_date: date
    end_date: date | None


class CandidateSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    proficiency_level: str | None


class CandidateCertificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    issuer: str
    issue_date: date
    expires_on: date | None
