"""add candidate-confirmed eligibility details and work authorizations

Revision ID: c3e9a2d7f1b5
Revises: a17c3e5b9d24
Create Date: 2026-10-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c3e9a2d7f1b5"
down_revision: str | Sequence[str] | None = "a17c3e5b9d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_eligibility_details",
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("country_of_residence", sa.String(length=2), nullable=True),
        sa.Column("relocation_willingness", sa.String(length=16), nullable=True),
        sa.Column("relocation_countries", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("accepted_work_arrangements", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "relocation_willingness IS NULL OR relocation_willingness IN ('willing', 'not_willing')",
            name="ck_candidate_eligibility_relocation",
        ),
        sa.CheckConstraint(
            "country_of_residence IS NULL OR length(country_of_residence) = 2",
            name="ck_candidate_eligibility_country",
        ),
        sa.ForeignKeyConstraint(["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("candidate_profile_id"),
    )
    op.create_table(
        "candidate_work_authorizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('authorized', 'not_authorized')",
            name="ck_candidate_work_authorization_status",
        ),
        sa.CheckConstraint("length(country_code) = 2", name="ck_candidate_work_authorization_country"),
        sa.ForeignKeyConstraint(["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_profile_id", "country_code", name="uq_candidate_work_authorization_country"
        ),
    )


def downgrade() -> None:
    # Destroys the candidate's confirmed eligibility details; take a backup first.
    op.drop_table("candidate_work_authorizations")
    op.drop_table("candidate_eligibility_details")
