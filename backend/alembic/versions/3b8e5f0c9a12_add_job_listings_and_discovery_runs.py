"""add job listings and discovery runs

Revision ID: 3b8e5f0c9a12
Revises: d4f7a19c2b86
Create Date: 2026-10-16

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "3b8e5f0c9a12"
down_revision: str | Sequence[str] | None = "d4f7a19c2b86"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_key", sa.String(length=200), nullable=False),
        sa.Column("source_listing_id", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("application_url", sa.String(length=2048), nullable=False),
        sa.Column("employer_name", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("location_text", sa.String(length=500), nullable=True),
        sa.Column("stated_workplace_type", sa.String(length=20), nullable=True),
        sa.Column("stated_countries", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("application_deadline", sa.Date(), nullable=True),
        sa.Column("salary_min", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("salary_max", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column("salary_period", sa.String(length=20), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("source_status", sa.String(length=24), server_default="active", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_job_listing_title"),
        sa.CheckConstraint("length(trim(employer_name)) > 0", name="ck_job_listing_employer"),
        sa.CheckConstraint(
            "length(trim(source_listing_id)) > 0", name="ck_job_listing_source_listing_id"
        ),
        sa.CheckConstraint(
            "source_status IN ('active', 'missing_from_source')",
            name="ck_job_listing_source_status",
        ),
        sa.CheckConstraint(
            "stated_workplace_type IS NULL OR stated_workplace_type IN "
            "('remote', 'hybrid', 'onsite')",
            name="ck_job_listing_workplace_type",
        ),
        sa.CheckConstraint(
            "salary_min IS NULL OR salary_max IS NULL OR salary_max >= salary_min",
            name="ck_job_listing_salary_order",
        ),
        sa.CheckConstraint(
            "(salary_min IS NULL AND salary_max IS NULL) OR salary_currency IS NOT NULL",
            name="ck_job_listing_salary_currency",
        ),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_job_listing_content_hash"),
        sa.CheckConstraint("length(dedupe_key) = 64", name="ck_job_listing_dedupe_key"),
        sa.CheckConstraint("last_seen_at >= first_seen_at", name="ck_job_listing_seen_order"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_kind",
            "source_key",
            "source_listing_id",
            name="uq_job_listings_source_identity",
        ),
    )
    op.create_index(
        "ix_job_listings_status_posted", "job_listings", ["source_status", "posted_at"]
    )
    op.create_index("ix_job_listings_first_seen", "job_listings", ["first_seen_at"])
    op.create_index("ix_job_listings_dedupe_key", "job_listings", ["dedupe_key"])

    op.create_table(
        "job_discovery_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_category", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unchanged_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("missing_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_job_discovery_run_status"
        ),
        sa.CheckConstraint(
            "error_category IS NULL OR error_category IN ('unavailable', 'not_found', "
            "'rate_limited', 'invalid_response', 'too_large', 'timeout', 'conflict', "
            "'internal_error')",
            name="ck_job_discovery_run_error_category",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_category IS NOT NULL)",
            name="ck_job_discovery_run_failure_consistency",
        ),
        sa.CheckConstraint(
            "fetched_count >= 0 AND created_count >= 0 AND updated_count >= 0 "
            "AND unchanged_count >= 0 AND missing_count >= 0 AND skipped_count >= 0",
            name="ck_job_discovery_run_counts",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_discovery_runs_source_started",
        "job_discovery_runs",
        ["source_kind", "source_key", "started_at"],
    )


def downgrade() -> None:
    # Destroys all discovered listings and run history; take a backup first.
    op.drop_index("ix_job_discovery_runs_source_started", table_name="job_discovery_runs")
    op.drop_table("job_discovery_runs")
    op.drop_index("ix_job_listings_dedupe_key", table_name="job_listings")
    op.drop_index("ix_job_listings_first_seen", table_name="job_listings")
    op.drop_index("ix_job_listings_status_posted", table_name="job_listings")
    op.drop_table("job_listings")
