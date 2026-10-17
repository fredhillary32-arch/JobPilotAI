"""link job descriptions to discovered listings

Revision ID: 5c2d9e7a1f40
Revises: 3b8e5f0c9a12
Create Date: 2026-10-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "5c2d9e7a1f40"
down_revision: str | Sequence[str] | None = "3b8e5f0c9a12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Additive: existing job descriptions keep a null link.
    op.add_column(
        "candidate_job_descriptions",
        sa.Column("source_job_listing_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_job_description_source_listing",
        "candidate_job_descriptions",
        "job_listings",
        ["source_job_listing_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_job_description_profile_listing",
        "candidate_job_descriptions",
        ["candidate_profile_id", "source_job_listing_id"],
    )


def downgrade() -> None:
    # Drops only the link; imported job descriptions and their text remain.
    op.drop_constraint(
        "uq_job_description_profile_listing",
        "candidate_job_descriptions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_job_description_source_listing",
        "candidate_job_descriptions",
        type_="foreignkey",
    )
    op.drop_column("candidate_job_descriptions", "source_job_listing_id")
