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
DescriptionText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
SkillText = Annotated[NonEmptyText, Field(max_length=100)]
ProficiencyLevel = Literal["beginner", "intermediate", "advanced", "expert"]
WorkArrangement = Literal["remote", "hybrid", "onsite"]


class CandidateWorkExperienceCreate(BaseModel):
    employer: Annotated[NonEmptyText, Field(max_length=200)]
    job_title: Annotated[NonEmptyText, Field(max_length=200)]
    location: ShortText | None = None
    work_arrangement: WorkArrangement | None = None
    start_date: date
    end_date: date | None = None
    current_role: bool = False
    description: DescriptionText | None = None
    achievements: list[AchievementText] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_dates(self) -> "CandidateWorkExperienceCreate":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.current_role and self.end_date is not None:
            raise ValueError("current roles cannot have an end_date")
        return self


class CandidateWorkExperienceUpdate(BaseModel):
    employer: Annotated[NonEmptyText, Field(max_length=200)] | None = None
    job_title: Annotated[NonEmptyText, Field(max_length=200)] | None = None
    location: ShortText | None = None
    work_arrangement: WorkArrangement | None = None
    start_date: date | None = None
    end_date: date | None = None
    current_role: bool | None = None
    description: DescriptionText | None = None
    achievements: list[AchievementText] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_patch(self) -> "CandidateWorkExperienceUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field_name in ("employer", "job_title", "start_date", "current_role", "achievements"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be on or after start_date")
        if self.current_role and self.end_date is not None:
            raise ValueError("current roles cannot have an end_date")
        return self


class CandidateEducationCreate(BaseModel):
    institution: Annotated[NonEmptyText, Field(max_length=200)]
    qualification: Annotated[NonEmptyText, Field(max_length=200)]
    field_of_study: ShortText | None = None
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "CandidateEducationCreate":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class CandidateEducationUpdate(BaseModel):
    institution: Annotated[NonEmptyText, Field(max_length=200)] | None = None
    qualification: Annotated[NonEmptyText, Field(max_length=200)] | None = None
    field_of_study: ShortText | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "CandidateEducationUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field_name in ("institution", "qualification", "start_date"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be on or after start_date")
        return self


class CandidateSkillCreate(BaseModel):
    name: SkillText
    proficiency_level: ProficiencyLevel | None = None


class CandidateSkillUpdate(BaseModel):
    name: SkillText | None = None
    proficiency_level: ProficiencyLevel | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "CandidateSkillUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class CandidateCertificationCreate(BaseModel):
    name: Annotated[NonEmptyText, Field(max_length=200)]
    issuer: Annotated[NonEmptyText, Field(max_length=200)]
    issue_date: date
    expires_on: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "CandidateCertificationCreate":
        if self.expires_on is not None and self.expires_on < self.issue_date:
            raise ValueError("expires_on must be on or after issue_date")
        return self


class CandidateCertificationUpdate(BaseModel):
    name: Annotated[NonEmptyText, Field(max_length=200)] | None = None
    issuer: Annotated[NonEmptyText, Field(max_length=200)] | None = None
    issue_date: date | None = None
    expires_on: date | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "CandidateCertificationUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field_name in ("name", "issuer", "issue_date"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        if (
            self.issue_date is not None
            and self.expires_on is not None
            and self.expires_on < self.issue_date
        ):
            raise ValueError("expires_on must be on or after issue_date")
        return self


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
    candidate_profile_id: UUID
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
    candidate_profile_id: UUID
    institution: str
    qualification: str
    field_of_study: str | None
    start_date: date
    end_date: date | None


class CandidateSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    name: str
    proficiency_level: str | None


class CandidateCertificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    name: str
    issuer: str
    issue_date: date
    expires_on: date | None
