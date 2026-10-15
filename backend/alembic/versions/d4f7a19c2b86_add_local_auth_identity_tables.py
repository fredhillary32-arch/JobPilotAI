"""add local authentication identity tables

Revision ID: d4f7a19c2b86
Revises: 7ce347caa873
Create Date: 2026-10-15

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d4f7a19c2b86"
down_revision: str | Sequence[str] | None = "7ce347caa873"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(email)) > 0 AND email = lower(trim(email))",
            name="ck_user_email_normalized",
        ),
        sa.CheckConstraint(
            "length(trim(password_hash)) > 0",
            name="ck_user_password_hash",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_auth_session_token_hash_length",
        ),
        sa.CheckConstraint(
            "length(csrf_token_hash) = 64",
            name="ck_auth_session_csrf_hash_length",
        ),
        sa.CheckConstraint(
            "idle_expires_at > created_at",
            name="ck_auth_session_idle_expiry",
        ),
        sa.CheckConstraint(
            "absolute_expires_at >= idle_expires_at",
            name="ck_auth_session_absolute_expiry",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index(
        "ix_auth_sessions_user_revoked",
        "auth_sessions",
        ["user_id", "revoked_at"],
        unique=False,
    )
    op.create_table(
        "pre_auth_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("cookie_binding_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_pre_auth_challenge_token_hash_length",
        ),
        sa.CheckConstraint(
            "length(cookie_binding_hash) = 64",
            name="ck_pre_auth_challenge_cookie_hash_length",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_pre_auth_challenge_expiry",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_pre_auth_challenges_token_hash"),
    )
    op.create_index(
        "ix_pre_auth_challenges_expires",
        "pre_auth_challenges",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "profile_ownership_adoptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("previous_user_id", sa.Uuid(), nullable=True),
        sa.Column("new_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "previous_user_id IS NULL OR previous_user_id <> new_user_id",
            name="ck_profile_adoption_changes_owner",
        ),
        sa.CheckConstraint(
            "action IN ('adopt', 'reassign')",
            name="ck_profile_adoption_action",
        ),
        sa.ForeignKeyConstraint(
            ["previous_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["new_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profile_adoptions_profile_occurred",
        "profile_ownership_adoptions",
        ["candidate_profile_id", "occurred_at"],
        unique=False,
    )

    with op.batch_alter_table("candidate_profiles") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_candidate_profiles_user_id",
            "users",
            ["user_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_candidate_profiles_user_id",
        "candidate_profiles",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_profiles_user_id", table_name="candidate_profiles")
    with op.batch_alter_table("candidate_profiles") as batch_op:
        batch_op.drop_constraint("fk_candidate_profiles_user_id", type_="foreignkey")
        batch_op.drop_column("user_id")
    op.drop_index(
        "ix_profile_adoptions_profile_occurred",
        table_name="profile_ownership_adoptions",
    )
    op.drop_table("profile_ownership_adoptions")
    op.drop_index(
        "ix_pre_auth_challenges_expires",
        table_name="pre_auth_challenges",
    )
    op.drop_table("pre_auth_challenges")
    op.drop_index("ix_auth_sessions_user_revoked", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
