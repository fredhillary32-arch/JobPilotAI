"""add reviewed listing eligibility assessments

Revision ID: a17c3e5b9d24
Revises: 8d4b6f2e9c17
Create Date: 2026-10-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a17c3e5b9d24"
down_revision: str | Sequence[str] | None = "8d4b6f2e9c17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listing_eligibility_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_listing_id", sa.Uuid(), nullable=False),
        sa.Column("assessed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("quotation", sa.Text(), nullable=True),
        sa.Column("evidence_field", sa.String(length=16), nullable=True),
        sa.Column("quote_start", sa.Integer(), nullable=True),
        sa.Column("statement_scope", sa.String(length=24), nullable=True),
        sa.Column("role_applicability", sa.String(length=32), nullable=True),
        sa.Column("examined_description", sa.Text(), nullable=True),
        sa.Column("examined_location", sa.String(length=500), nullable=True),
        sa.Column("listing_content_hash", sa.String(length=64), nullable=False),
        sa.Column("listing_source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("listing_last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('eligible_confirmed', 'not_eligible', 'eligibility_unknown')",
            name="ck_eligibility_outcome",
        ),
        sa.CheckConstraint(
            "evidence_field IS NULL OR evidence_field IN ('description', 'location')",
            name="ck_eligibility_evidence_field",
        ),
        sa.CheckConstraint(
            "statement_scope IS NULL OR statement_scope IN ('role', 'company', 'team', "
            "'market_or_customer', 'unclear')",
            name="ck_eligibility_statement_scope",
        ),
        sa.CheckConstraint(
            "role_applicability IS NULL OR role_applicability IN ('direct', "
            "'established_by_wording', 'unclear', 'not_applicable')",
            name="ck_eligibility_role_applicability",
        ),
        sa.CheckConstraint(
            "outcome = 'eligibility_unknown' OR (quotation IS NOT NULL AND evidence_field IS NOT "
            "NULL AND quote_start IS NOT NULL AND role_applicability IN ('direct', "
            "'established_by_wording'))",
            name="ck_eligibility_definite_needs_evidence",
        ),
        sa.CheckConstraint("length(trim(explanation)) > 0", name="ck_eligibility_explanation"),
        sa.ForeignKeyConstraint(["job_listing_id"], ["job_listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assessed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_eligibility_listing_assessed",
        "listing_eligibility_assessments",
        ["job_listing_id", "assessed_at"],
    )


def downgrade() -> None:
    # Destroys all recorded eligibility assessments; take a backup first.
    op.drop_index("ix_eligibility_listing_assessed", table_name="listing_eligibility_assessments")
    op.drop_table("listing_eligibility_assessments")
