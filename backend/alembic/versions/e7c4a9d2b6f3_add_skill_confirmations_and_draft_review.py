"""add candidate skill confirmations and the needs_review draft status

Additive: one new table, and the draft status constraints widened to allow
"needs_review". No existing row is changed.

Revision ID: e7c4a9d2b6f3
Revises: d8b4f6a2c9e1
Create Date: 2026-10-17
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7c4a9d2b6f3"
down_revision: str | Sequence[str] | None = "d8b4f6a2c9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_cv_draft_status", "tailored_cv_drafts", type_="check")
    op.drop_constraint("ck_cv_draft_content_status", "tailored_cv_drafts", type_="check")
    op.create_check_constraint(
        "ck_cv_draft_status", "tailored_cv_drafts", "status IN ('generated', 'needs_review', 'failed')",
    )
    op.create_check_constraint(
        "ck_cv_draft_content_status",
        "tailored_cv_drafts",
        "(status IN ('generated', 'needs_review') AND generated_content IS NOT NULL "
        "AND structured_content IS NOT NULL) OR "
        "(status = 'failed' AND generated_content IS NULL AND structured_content IS NULL)",
    )

    op.create_table(
        "candidate_skill_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("job_description_id", sa.Uuid(), nullable=True),
        sa.Column("requirement_key", sa.String(length=32), nullable=True),
        sa.Column("requirement_text", sa.String(length=1000), nullable=True),
        sa.Column("skill_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("response", sa.String(length=24), nullable=False),
        sa.Column("proficiency_level", sa.String(length=20), nullable=True),
        sa.Column("work_experience_id", sa.Uuid(), nullable=True),
        sa.Column("project_name", sa.String(length=200), nullable=True),
        sa.Column("example", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("length(trim(skill_name)) > 0", name="ck_skill_confirmation_name"),
        sa.CheckConstraint(
            "response IN ('has_skill', 'used_in_role', 'needs_details', 'not_possessed', 'unsure')",
            name="ck_skill_confirmation_response",
        ),
        sa.CheckConstraint(
            "category IN ('technical', 'tool', 'communication', 'customer_service', 'work_style', 'language', 'other')",
            name="ck_skill_confirmation_category",
        ),
        sa.CheckConstraint("status IN ('active', 'withdrawn')", name="ck_skill_confirmation_status"),
        sa.CheckConstraint(
            "proficiency_level IS NULL OR proficiency_level IN ('beginner', 'intermediate', 'advanced', 'expert')",
            name="ck_skill_confirmation_proficiency",
        ),
        sa.CheckConstraint(
            "response <> 'used_in_role' OR (example IS NOT NULL AND length(trim(example)) > 0)",
            name="ck_skill_confirmation_example",
        ),
        sa.CheckConstraint(
            "(requirement_key IS NULL) = (job_description_id IS NULL)",
            name="ck_skill_confirmation_requirement_job",
        ),
        sa.ForeignKeyConstraint(["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["job_description_id", "candidate_profile_id"],
            ["candidate_job_descriptions.id", "candidate_job_descriptions.candidate_profile_id"],
            ondelete="RESTRICT",
            name="fk_skill_confirmation_job_profile",
        ),
        sa.ForeignKeyConstraint(["work_experience_id"], ["candidate_work_experiences.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_confirmations_profile", "candidate_skill_confirmations", ["candidate_profile_id", "status"])
    op.create_index("ix_skill_confirmations_job", "candidate_skill_confirmations", ["job_description_id", "requirement_key"])


def downgrade() -> None:
    # Only safe while no draft uses "needs_review"; the forward path is the supported one.
    op.drop_index("ix_skill_confirmations_job", table_name="candidate_skill_confirmations")
    op.drop_index("ix_skill_confirmations_profile", table_name="candidate_skill_confirmations")
    op.drop_table("candidate_skill_confirmations")
    op.drop_constraint("ck_cv_draft_content_status", "tailored_cv_drafts", type_="check")
    op.drop_constraint("ck_cv_draft_status", "tailored_cv_drafts", type_="check")
    op.create_check_constraint("ck_cv_draft_status", "tailored_cv_drafts", "status IN ('generated', 'failed')")
    op.create_check_constraint(
        "ck_cv_draft_content_status",
        "tailored_cv_drafts",
        "(status = 'generated' AND generated_content IS NOT NULL AND structured_content IS NOT NULL) OR "
        "(status = 'failed' AND generated_content IS NULL AND structured_content IS NULL)",
    )
