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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

EvidenceCategory = Literal[
    "employment_responsibility",
    "technical_skill",
    "project",
    "achievement",
    "qualification",
    "metric",
]
EvidenceConfirmationStatus = Literal["unreviewed", "candidate_confirmed", "rejected"]


class CandidateEvidence(Base):
    __tablename__ = "candidate_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_document_id", "candidate_profile_id"],
            [
                "candidate_documents.id",
                "candidate_documents.candidate_profile_id",
            ],
            ondelete="CASCADE",
            name="fk_candidate_evidence_source_document_profile",
        ),
        CheckConstraint(
            "category IN ('employment_responsibility', 'technical_skill', 'project', "
            "'achievement', 'qualification', 'metric')",
            name="ck_candidate_evidence_category",
        ),
        CheckConstraint(
            "confirmation_status IN ('unreviewed', 'candidate_confirmed', 'rejected')",
            name="ck_candidate_evidence_confirmation_status",
        ),
        CheckConstraint("length(trim(description)) > 0", name="ck_candidate_evidence_description"),
        CheckConstraint(
            "(source_start IS NULL AND source_end IS NULL) "
            "OR (source_start >= 0 AND source_end > source_start)",
            name="ck_candidate_evidence_offsets",
        ),
        CheckConstraint(
            "source_excerpt IS NOT NULL OR source_start IS NOT NULL",
            name="ck_candidate_evidence_source_reference",
        ),
        Index(
            "ix_candidate_evidence_profile_created",
            "candidate_profile_id",
            "created_at",
        ),
        Index("ix_candidate_evidence_source_document", "source_document_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_start: Mapped[int | None] = mapped_column()
    source_end: Mapped[int | None] = mapped_column()
    source_section: Mapped[str | None] = mapped_column(String(200))
    confirmation_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="unreviewed",
        server_default="unreviewed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    candidate_profile: Mapped["CandidateProfile"] = relationship(
        back_populates="evidence_records",
        overlaps="evidence_records,source_document",
    )
    source_document: Mapped["CandidateDocument"] = relationship(
        back_populates="evidence_records",
        overlaps="candidate_profile,evidence_records",
    )
