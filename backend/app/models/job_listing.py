from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

LISTING_SOURCE_STATUSES = ("active", "missing_from_source")
DISCOVERY_RUN_STATUSES = ("running", "succeeded", "failed")
DISCOVERY_ERROR_CATEGORIES = (
    "unavailable",
    "not_found",
    "rate_limited",
    "invalid_response",
    "too_large",
    "timeout",
    "conflict",
    "internal_error",
)


class JobListing(Base):
    """Facts reported by a job source. JobPilot's own conclusions live elsewhere.

    Nullable fields mean the source did not state the value; they are never
    inferred. Listings are not deleted when a source drops them; they are marked
    ``missing_from_source`` after a fully successful discovery run.
    """

    __tablename__ = "job_listings"
    __table_args__ = (
        UniqueConstraint(
            "source_kind",
            "source_key",
            "source_listing_id",
            name="uq_job_listings_source_identity",
        ),
        CheckConstraint("length(trim(title)) > 0", name="ck_job_listing_title"),
        CheckConstraint("length(trim(employer_name)) > 0", name="ck_job_listing_employer"),
        CheckConstraint(
            "length(trim(source_listing_id)) > 0",
            name="ck_job_listing_source_listing_id",
        ),
        CheckConstraint(
            "source_status IN ('active', 'missing_from_source')",
            name="ck_job_listing_source_status",
        ),
        CheckConstraint(
            "stated_workplace_type IS NULL OR stated_workplace_type IN "
            "('remote', 'hybrid', 'onsite')",
            name="ck_job_listing_workplace_type",
        ),
        CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min",
            name="ck_job_listing_salary_order",
        ),
        CheckConstraint(
            "(salary_min IS NULL AND salary_max IS NULL) OR salary_currency IS NOT NULL",
            name="ck_job_listing_salary_currency",
        ),
        CheckConstraint("length(content_hash) = 64", name="ck_job_listing_content_hash"),
        CheckConstraint("length(dedupe_key) = 64", name="ck_job_listing_dedupe_key"),
        CheckConstraint("last_seen_at >= first_seen_at", name="ck_job_listing_seen_order"),
        Index("ix_job_listings_status_posted", "source_status", "posted_at"),
        Index("ix_job_listings_first_seen", "first_seen_at"),
        Index("ix_job_listings_dedupe_key", "dedupe_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # Source identity and provenance.
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source_listing_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    application_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Facts exactly as stated by the source (untrusted text).
    employer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description_text: Mapped[str | None] = mapped_column(Text)
    location_text: Mapped[str | None] = mapped_column(String(500))
    stated_workplace_type: Mapped[str | None] = mapped_column(String(20))
    stated_countries: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    application_deadline: Mapped[date | None] = mapped_column(Date)
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(20))
    # JobPilot bookkeeping about the source record (not eligibility conclusions).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="active", server_default="active"
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class JobDiscoveryRun(Base):
    """One attempt to read one source; failures are recorded, never hidden."""

    __tablename__ = "job_discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_job_discovery_run_status",
        ),
        CheckConstraint(
            "error_category IS NULL OR error_category IN ('unavailable', 'not_found', "
            "'rate_limited', 'invalid_response', 'too_large', 'timeout', 'conflict', "
            "'internal_error')",
            name="ck_job_discovery_run_error_category",
        ),
        CheckConstraint(
            "(status = 'failed') = (error_category IS NOT NULL)",
            name="ck_job_discovery_run_failure_consistency",
        ),
        CheckConstraint(
            "fetched_count >= 0 AND created_count >= 0 AND updated_count >= 0 "
            "AND unchanged_count >= 0 AND missing_count >= 0 AND skipped_count >= 0",
            name="ck_job_discovery_run_counts",
        ),
        Index("ix_job_discovery_runs_source_started", "source_kind", "source_key", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    updated_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    missing_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
