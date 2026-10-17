from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.candidate_profile import CandidateProfile


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "length(trim(email)) > 0 AND email = lower(trim(email))",
            name="ck_user_email_normalized",
        ),
        CheckConstraint("length(trim(password_hash)) > 0", name="ck_user_password_hash"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    candidate_profiles: Mapped[list["CandidateProfile"]] = relationship(
        back_populates="user",
        passive_deletes="all",
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "length(token_hash) = 64",
            name="ck_auth_session_token_hash_length",
        ),
        CheckConstraint(
            "length(csrf_token_hash) = 64",
            name="ck_auth_session_csrf_hash_length",
        ),
        CheckConstraint(
            "idle_expires_at > created_at",
            name="ck_auth_session_idle_expiry",
        ),
        CheckConstraint(
            "absolute_expires_at >= idle_expires_at",
            name="ck_auth_session_absolute_expiry",
        ),
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        Index("ix_auth_sessions_user_revoked", "user_id", "revoked_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class PreAuthChallenge(Base):
    __tablename__ = "pre_auth_challenges"
    __table_args__ = (
        CheckConstraint(
            "length(token_hash) = 64",
            name="ck_pre_auth_challenge_token_hash_length",
        ),
        CheckConstraint(
            "length(cookie_binding_hash) = 64",
            name="ck_pre_auth_challenge_cookie_hash_length",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_pre_auth_challenge_expiry",
        ),
        UniqueConstraint("token_hash", name="uq_pre_auth_challenges_token_hash"),
        Index("ix_pre_auth_challenges_expires", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cookie_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProfileOwnershipAdoption(Base):
    __tablename__ = "profile_ownership_adoptions"
    __table_args__ = (
        CheckConstraint(
            "previous_user_id IS NULL OR previous_user_id <> new_user_id",
            name="ck_profile_adoption_changes_owner",
        ),
        CheckConstraint(
            "action IN ('adopt', 'reassign')",
            name="ck_profile_adoption_action",
        ),
        Index(
            "ix_profile_adoptions_profile_occurred",
            "candidate_profile_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # Keep this historical UUID even if its candidate profile is later removed.
    candidate_profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    previous_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    new_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
