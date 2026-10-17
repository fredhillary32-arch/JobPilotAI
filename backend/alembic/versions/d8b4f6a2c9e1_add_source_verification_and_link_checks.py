"""add listing links, source category, relisting, skip reasons, link checks, geographic scope

Revision ID: d8b4f6a2c9e1
Revises: c3e9a2d7f1b5
Create Date: 2026-10-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d8b4f6a2c9e1"
down_revision: str | Sequence[str] | None = "c3e9a2d7f1b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPES = (
    "'kenya_named', 'africa', 'emea', 'worldwide', 'other_countries', 'restricted', "
    "'conflicting', 'unclear', 'awaiting_employer'"
)


def upgrade() -> None:
    # All additive: existing rows keep nulls/defaults and are filled by later runs.
    op.add_column("job_listings", sa.Column("listing_url", sa.String(length=2048), nullable=True))
    op.add_column("job_listings", sa.Column("source_category", sa.String(length=32), nullable=True))
    op.add_column("job_listings", sa.Column("relisted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "job_discovery_runs",
        sa.Column("skip_reasons", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "listing_eligibility_assessments",
        sa.Column("geographic_scope", sa.String(length=24), nullable=True),
    )
    op.create_check_constraint(
        "ck_eligibility_geographic_scope",
        "listing_eligibility_assessments",
        f"geographic_scope IS NULL OR geographic_scope IN ({SCOPES})",
    )
    op.create_table(
        "job_listing_link_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_listing_id", sa.Uuid(), nullable=False),
        sa.Column("url_kind", sa.String(length=16), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("final_url", sa.String(length=2048), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("url_kind IN ('listing', 'application')", name="ck_link_check_kind"),
        sa.CheckConstraint(
            "outcome IN ('reachable', 'expired', 'auth_required', 'redirected_off_domain', "
            "'unverified_domain', 'insecure', 'rate_limited', 'broken', 'unreachable')",
            name="ck_link_check_outcome",
        ),
        sa.ForeignKeyConstraint(["job_listing_id"], ["job_listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_link_checks_listing_kind_checked",
        "job_listing_link_checks",
        ["job_listing_id", "url_kind", "checked_at"],
    )


def downgrade() -> None:
    # Destroys link-check history, geographic scopes and skip reasons; take a backup first.
    op.drop_index("ix_link_checks_listing_kind_checked", table_name="job_listing_link_checks")
    op.drop_table("job_listing_link_checks")
    op.drop_constraint("ck_eligibility_geographic_scope", "listing_eligibility_assessments", type_="check")
    op.drop_column("listing_eligibility_assessments", "geographic_scope")
    op.drop_column("job_discovery_runs", "skip_reasons")
    op.drop_column("job_listings", "relisted_at")
    op.drop_column("job_listings", "source_category")
    op.drop_column("job_listings", "listing_url")
