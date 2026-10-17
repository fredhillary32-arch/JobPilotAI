from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RELOCATION_WILLINGNESS = ("willing", "not_willing")
WORK_AUTHORIZATION_STATUSES = ("authorized", "not_authorized")
WORK_ARRANGEMENTS = ("remote", "hybrid", "onsite")


class CandidateEligibilityDetails(Base):
    """Work-eligibility facts the candidate explicitly confirmed.

    Separate from the free-text profile location, which is never treated as
    confirmed. A null value means the candidate has not said; it is unknown.
    """

    __tablename__ = "candidate_eligibility_details"
    __table_args__ = (
        CheckConstraint(
            "relocation_willingness IS NULL OR relocation_willingness IN ('willing', 'not_willing')",
            name="ck_candidate_eligibility_relocation",
        ),
        CheckConstraint(
            "country_of_residence IS NULL OR length(country_of_residence) = 2",
            name="ck_candidate_eligibility_country",
        ),
    )

    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    country_of_residence: Mapped[str | None] = mapped_column(String(2))
    relocation_willingness: Mapped[str | None] = mapped_column(String(16))
    relocation_countries: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    accepted_work_arrangements: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CandidateWorkAuthorization(Base):
    """One candidate-confirmed statement about the right to work in a country."""

    __tablename__ = "candidate_work_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "candidate_profile_id", "country_code", name="uq_candidate_work_authorization_country"
        ),
        CheckConstraint(
            "status IN ('authorized', 'not_authorized')",
            name="ck_candidate_work_authorization_status",
        ),
        CheckConstraint("length(country_code) = 2", name="ck_candidate_work_authorization_country"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
