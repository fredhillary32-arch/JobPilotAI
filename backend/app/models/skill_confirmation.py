"""The candidate's own answers about skills and job requirements.

A confirmation records what the candidate says, never independent proof:
- ``has_skill``: they have the skill (it may appear in Core Skills);
- ``used_in_role``: they used it in a recorded role or a project and give a
  truthful example in their own words (the example may become a CV bullet for
  that role);
- ``needs_details``: they have it but will add details later;
- ``not_possessed``: they do not have it (never claimed on a CV);
- ``unsure``: left unverified (never claimed on a CV).

Withdrawn confirmations are kept for history and never used.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SKILL_RESPONSES = ("has_skill", "used_in_role", "needs_details", "not_possessed", "unsure")
CLAIMABLE_RESPONSES = ("has_skill", "used_in_role", "needs_details")
SKILL_CATEGORIES = ("technical", "tool", "communication", "customer_service", "work_style", "language", "other")
SkillResponse = Literal["has_skill", "used_in_role", "needs_details", "not_possessed", "unsure"]
SkillCategory = Literal["technical", "tool", "communication", "customer_service", "work_style", "language", "other"]


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class CandidateSkillConfirmation(Base):
    __tablename__ = "candidate_skill_confirmations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_description_id", "candidate_profile_id"],
            ["candidate_job_descriptions.id", "candidate_job_descriptions.candidate_profile_id"],
            ondelete="RESTRICT",
            name="fk_skill_confirmation_job_profile",
        ),
        CheckConstraint("length(trim(skill_name)) > 0", name="ck_skill_confirmation_name"),
        CheckConstraint(f"response IN ({_in(SKILL_RESPONSES)})", name="ck_skill_confirmation_response"),
        CheckConstraint(f"category IN ({_in(SKILL_CATEGORIES)})", name="ck_skill_confirmation_category"),
        CheckConstraint("status IN ('active', 'withdrawn')", name="ck_skill_confirmation_status"),
        CheckConstraint(
            "proficiency_level IS NULL OR proficiency_level IN ('beginner', 'intermediate', 'advanced', 'expert')",
            name="ck_skill_confirmation_proficiency",
        ),
        # An example in the candidate's own words is what "used in a role or project" means.
        CheckConstraint(
            "response <> 'used_in_role' OR (example IS NOT NULL AND length(trim(example)) > 0)",
            name="ck_skill_confirmation_example",
        ),
        CheckConstraint(
            "(requirement_key IS NULL) = (job_description_id IS NULL)",
            name="ck_skill_confirmation_requirement_job",
        ),
        Index("ix_skill_confirmations_profile", "candidate_profile_id", "status"),
        Index("ix_skill_confirmations_job", "job_description_id", "requirement_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The saved job and requirement this answers; both empty for a skill recorded on its own.
    job_description_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    requirement_key: Mapped[str | None] = mapped_column(String(32))
    requirement_text: Mapped[str | None] = mapped_column(String(1000))
    skill_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    response: Mapped[str] = mapped_column(String(24), nullable=False)
    proficiency_level: Mapped[str | None] = mapped_column(String(20))
    # The recorded role it was used in; the API checks it belongs to the same profile.
    work_experience_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_work_experiences.id", ondelete="SET NULL"),
    )
    project_name: Mapped[str | None] = mapped_column(String(200))
    example: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
