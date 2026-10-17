from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.candidate_document import CandidateDocument

ExtractionStatus = Literal["succeeded", "no_text", "failed"]
ExtractionErrorCategory = Literal[
    "missing_file",
    "invalid_document",
    "encrypted_document",
    "resource_limit",
    "unsupported_content",
    "decoding_error",
    "extraction_error",
]


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'no_text', 'failed')",
            name="ck_document_extraction_status",
        ),
        CheckConstraint(
            "error_category IS NULL OR error_category IN "
            "('missing_file', 'invalid_document', 'encrypted_document', "
            "'resource_limit', 'unsupported_content', 'decoding_error', "
            "'extraction_error')",
            name="ck_document_extraction_error_category",
        ),
        CheckConstraint("character_count >= 0", name="ck_document_extraction_char_count"),
        CheckConstraint(
            "(status = 'succeeded' AND extracted_text IS NOT NULL AND error_category IS NULL) "
            "OR (status = 'no_text' AND extracted_text IS NULL AND error_category IS NULL) "
            "OR (status = 'failed' AND extracted_text IS NULL AND error_category IS NOT NULL)",
            name="ck_document_extraction_result_consistency",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    character_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    extractor_version: Mapped[str] = mapped_column(String(100), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(32))
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    source_document: Mapped["CandidateDocument"] = relationship(back_populates="extraction")
