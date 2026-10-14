from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

CvDraftStatus = Literal["generated", "failed"]


class CandidateJobDescription(Base):
    __tablename__ = "candidate_job_descriptions"
    __table_args__ = (
        CheckConstraint("length(trim(job_title)) > 0", name="ck_job_description_title"),
        CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_job_description_description",
        ),
        UniqueConstraint("id", "candidate_profile_id", name="uq_job_description_profile"),
        Index(
            "ix_job_descriptions_profile_created",
            "candidate_profile_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_title: Mapped[str] = mapped_column(String(240), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    candidate_profile: Mapped["CandidateProfile"] = relationship(
        back_populates="job_descriptions"
    )
    cv_drafts: Mapped[list["TailoredCvDraft"]] = relationship(
        back_populates="job_description",
        overlaps="candidate_profile",
        passive_deletes=True,
    )


class TailoredCvDraft(Base):
    __tablename__ = "tailored_cv_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_description_id", "candidate_profile_id"],
            [
                "candidate_job_descriptions.id",
                "candidate_job_descriptions.candidate_profile_id",
            ],
            ondelete="RESTRICT",
            name="fk_cv_draft_job_profile",
        ),
        CheckConstraint(
            "status IN ('generated', 'failed')",
            name="ck_cv_draft_status",
        ),
        CheckConstraint(
            "(status = 'generated' AND generated_content IS NOT NULL "
            "AND structured_content IS NOT NULL) OR "
            "(status = 'failed' AND generated_content IS NULL "
            "AND structured_content IS NULL)",
            name="ck_cv_draft_content_status",
        ),
        Index(
            "ix_cv_drafts_profile_created",
            "candidate_profile_id",
            "created_at",
        ),
        Index("ix_cv_drafts_job", "job_description_id"),
        UniqueConstraint("id", "candidate_profile_id", name="uq_cv_draft_profile"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_description_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    generated_content: Mapped[str | None] = mapped_column(Text)
    structured_content: Mapped[dict | None] = mapped_column(
        JSON(none_as_null=True)
    )
    validation_results: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_references: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    job_description: Mapped[CandidateJobDescription] = relationship(
        back_populates="cv_drafts",
        overlaps="candidate_profile",
    )
    exports: Mapped[list["TailoredCvExport"]] = relationship(
        back_populates="cv_draft",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TailoredCvExport.created_at.desc()",
    )


class TailoredCvExport(Base):
    __tablename__ = "tailored_cv_exports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cv_draft_id", "candidate_profile_id"],
            ["tailored_cv_drafts.id", "tailored_cv_drafts.candidate_profile_id"],
            ondelete="CASCADE",
            name="fk_cv_export_draft_profile",
        ),
        ForeignKeyConstraint(
            ["document_id", "candidate_profile_id"],
            ["candidate_documents.id", "candidate_documents.candidate_profile_id"],
            ondelete="CASCADE",
            name="fk_cv_export_document_profile",
        ),
        CheckConstraint(
            "export_format IN ('pdf', 'docx')",
            name="ck_cv_export_format",
        ),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="ck_cv_export_page_count"),
        Index("ix_cv_exports_draft_created", "cv_draft_id", "created_at"),
        Index("ix_cv_exports_profile", "candidate_profile_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    cv_draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    export_format: Mapped[str] = mapped_column(String(8), nullable=False)
    page_count: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    cv_draft: Mapped[TailoredCvDraft] = relationship(back_populates="exports")
    document: Mapped["CandidateDocument"] = relationship(
        overlaps="cv_draft,exports"
    )
