from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.candidate_evidence import CandidateEvidence
    from app.models.candidate_profile import CandidateProfile
    from app.models.document_extraction import DocumentExtraction

DocumentKind = Literal[
    "source_cv",
    "supporting_document",
    "tailored_cv",
    "application_document",
    "final_cv",
]
DocumentProvenance = Literal[
    "candidate_uploaded",
    "candidate_confirmed",
    "ai_generated",
    "system_generated",
]


class CandidateDocument(Base):
    __tablename__ = "candidate_documents"
    __table_args__ = (
        CheckConstraint(
            "document_kind IN ('source_cv', 'supporting_document', 'tailored_cv', 'application_document', 'final_cv')",
            name="ck_candidate_document_kind",
        ),
        CheckConstraint(
            "provenance IN ('candidate_uploaded', 'candidate_confirmed', 'ai_generated', 'system_generated')",
            name="ck_candidate_document_provenance",
        ),
        CheckConstraint("size_bytes > 0", name="ck_candidate_document_size"),
        UniqueConstraint(
            "id",
            "candidate_profile_id",
            name="uq_candidate_document_profile",
        ),
        Index(
            "ix_candidate_documents_profile_created",
            "candidate_profile_id",
            "created_at",
        ),
        Index("ix_candidate_documents_source", "source_document_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_document_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_documents.id", ondelete="RESTRICT"),
    )
    document_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    target_job_title: Mapped[str | None] = mapped_column(String(240))
    target_company: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    candidate_profile: Mapped["CandidateProfile"] = relationship(back_populates="documents")
    source_document: Mapped["CandidateDocument | None"] = relationship(
        remote_side="CandidateDocument.id",
        back_populates="derived_documents",
    )
    derived_documents: Mapped[list["CandidateDocument"]] = relationship(
        back_populates="source_document",
    )
    extraction: Mapped["DocumentExtraction | None"] = relationship(
        back_populates="source_document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    evidence_records: Mapped[list["CandidateEvidence"]] = relationship(
        back_populates="source_document",
        overlaps="candidate_profile,evidence_records",
        passive_deletes=True,
    )
