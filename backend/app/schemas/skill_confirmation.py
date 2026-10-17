from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.models.skill_confirmation import SkillCategory, SkillResponse

SkillName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Example = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Proficiency = Literal["beginner", "intermediate", "advanced", "expert"]


class _Fields(BaseModel):
    @model_validator(mode="after")
    def example_for_use(self):
        if getattr(self, "response", None) == "used_in_role" and not getattr(self, "example", None):
            raise ValueError(
                "Describe, in your own words, how you used it: an example is required for 'used in a role or project'."
            )
        if getattr(self, "response", None) in {"not_possessed", "unsure"} and (
            getattr(self, "example", None) or getattr(self, "work_experience_id", None)
        ):
            raise ValueError("An example or role only applies when you have the skill.")
        return self


class SkillConfirmationCreate(_Fields):
    # Either both (answering a requirement of a saved job) or neither (a skill on its own).
    job_description_id: UUID | None = None
    requirement_key: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")] | None = None
    skill_name: SkillName
    category: SkillCategory = "other"
    response: SkillResponse
    proficiency_level: Proficiency | None = None
    work_experience_id: UUID | None = None
    project_name: ShortText | None = None
    example: Example | None = None

    @model_validator(mode="after")
    def requirement_pair(self):
        if (self.job_description_id is None) != (self.requirement_key is None):
            raise ValueError("A requirement answer needs both the saved job and the requirement.")
        if self.job_description_id is None and self.response in {"not_possessed", "unsure"}:
            raise ValueError("'Not possessed' and 'unsure' answer a job requirement; choose the requirement first.")
        return self


class SkillConfirmationUpdate(_Fields):
    skill_name: SkillName
    category: SkillCategory
    response: SkillResponse
    proficiency_level: Proficiency | None = None
    work_experience_id: UUID | None = None
    project_name: ShortText | None = None
    example: Example | None = None


class SkillConfirmationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    job_description_id: UUID | None
    requirement_key: str | None
    requirement_text: str | None
    skill_name: str
    category: str
    response: str
    proficiency_level: str | None
    work_experience_id: UUID | None
    project_name: str | None
    example: str | None
    status: str
    confirmed_at: datetime
    created_at: datetime
    updated_at: datetime
    # Always the candidate's own statement; JobPilot has no independent verification.
    provenance: Literal["candidate_confirmed"] = "candidate_confirmed"
    independently_verified: Literal[False] = False
