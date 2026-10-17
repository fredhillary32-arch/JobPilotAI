"""add job applications and their status history

Revision ID: 8d4b6f2e9c17
Revises: 5c2d9e7a1f40
Create Date: 2026-10-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "8d4b6f2e9c17"
down_revision: str | Sequence[str] | None = "5c2d9e7a1f40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "'saved', 'eligibility_review', 'preparing', 'ready_for_review', 'applied', "
    "'interviewing', 'offer', 'rejected', 'withdrawn', 'closed'"
)


def upgrade() -> None:
    op.create_table(
        "job_applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("job_description_id", sa.Uuid(), nullable=False),
        sa.Column("cv_draft_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("applied_on", sa.Date(), nullable=True),
        sa.Column("deadline_on", sa.Date(), nullable=True),
        sa.Column("follow_up_on", sa.Date(), nullable=True),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"status IN ({STATUSES})", name="ck_job_application_status"),
        sa.CheckConstraint(
            "status NOT IN ('applied', 'interviewing', 'offer') OR applied_on IS NOT NULL",
            name="ck_job_application_applied_on",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["job_description_id", "candidate_profile_id"],
            ["candidate_job_descriptions.id", "candidate_job_descriptions.candidate_profile_id"],
            ondelete="RESTRICT",
            name="fk_job_application_job_profile",
        ),
        sa.ForeignKeyConstraint(
            ["cv_draft_id", "candidate_profile_id"],
            ["tailored_cv_drafts.id", "tailored_cv_drafts.candidate_profile_id"],
            ondelete="RESTRICT",
            name="fk_job_application_cv_draft_profile",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_profile_id", "job_description_id", name="uq_job_application_profile_job"
        ),
    )
    op.create_index(
        "ix_job_applications_profile_status",
        "job_applications",
        ["candidate_profile_id", "status"],
    )
    op.create_table(
        "job_application_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"to_status IN ({STATUSES})", name="ck_job_application_event_to"),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({STATUSES})",
            name="ck_job_application_event_from",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["job_applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_application_events_application",
        "job_application_events",
        ["application_id", "occurred_at"],
    )


def downgrade() -> None:
    # Destroys all tracked applications and their history; take a backup first.
    op.drop_index("ix_job_application_events_application", table_name="job_application_events")
    op.drop_table("job_application_events")
    op.drop_index("ix_job_applications_profile_status", table_name="job_applications")
    op.drop_table("job_applications")
