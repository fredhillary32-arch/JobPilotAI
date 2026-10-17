from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

APPLICATION_STATUSES = (
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
)
# Statuses that only make sense after the candidate recorded submitting it.
SUBMITTED_STATUSES = ("applied", "interviewing", "offer")
# Statuses an application may be created in; later stages need a recorded
# submission and are reached through status changes.
INITIAL_STATUSES = ("saved", "eligibility_review", "preparing", "ready_for_review", "applied")
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "saved": frozenset({"eligibility_review", "preparing", "withdrawn", "closed"}),
    "eligibility_review": frozenset({"saved", "preparing", "withdrawn", "closed"}),
    "preparing": frozenset({"eligibility_review", "ready_for_review", "withdrawn", "closed"}),
    "ready_for_review": frozenset({"preparing", "applied", "withdrawn", "closed"}),
    "applied": frozenset({"interviewing", "offer", "rejected", "withdrawn", "closed"}),
    "interviewing": frozenset({"offer", "rejected", "withdrawn", "closed"}),
    "offer": frozenset({"withdrawn", "closed"}),
    "rejected": frozenset({"closed"}),
    "withdrawn": frozenset({"closed"}),
    "closed": frozenset(),
}

_STATUS_LIST = ", ".join(f"'{value}'" for value in APPLICATION_STATUSES)
_SUBMITTED_LIST = ", ".join(f"'{value}'" for value in SUBMITTED_STATUSES)


class JobApplication(Base):
    """One candidate's application for one of their saved job descriptions."""

    __tablename__ = "job_applications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_description_id", "candidate_profile_id"],
            [
                "candidate_job_descriptions.id",
                "candidate_job_descriptions.candidate_profile_id",
            ],
            ondelete="RESTRICT",
            name="fk_job_application_job_profile",
        ),
        ForeignKeyConstraint(
            ["cv_draft_id", "candidate_profile_id"],
            ["tailored_cv_drafts.id", "tailored_cv_drafts.candidate_profile_id"],
            ondelete="RESTRICT",
            name="fk_job_application_cv_draft_profile",
        ),
        UniqueConstraint(
            "candidate_profile_id",
            "job_description_id",
            name="uq_job_application_profile_job",
        ),
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="ck_job_application_status"),
        CheckConstraint(
            f"status NOT IN ({_SUBMITTED_LIST}) OR applied_on IS NOT NULL",
            name="ck_job_application_applied_on",
        ),
        Index("ix_job_applications_profile_status", "candidate_profile_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_description_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    cv_draft_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="saved")
    applied_on: Mapped[date | None] = mapped_column(Date)
    deadline_on: Mapped[date | None] = mapped_column(Date)
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list["JobApplicationEvent"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="JobApplicationEvent.occurred_at",
        passive_deletes=True,
    )

    @property
    def allowed_next_statuses(self) -> list[str]:
        allowed = ALLOWED_TRANSITIONS[self.status]
        return [value for value in APPLICATION_STATUSES if value in allowed]


class JobApplicationEvent(Base):
    """Append-only status history; the first event has no previous status."""

    __tablename__ = "job_application_events"
    __table_args__ = (
        CheckConstraint(f"to_status IN ({_STATUS_LIST})", name="ck_job_application_event_to"),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_STATUS_LIST})",
            name="ck_job_application_event_from",
        ),
        Index("ix_job_application_events_application", "application_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    application: Mapped[JobApplication] = relationship(back_populates="events")
