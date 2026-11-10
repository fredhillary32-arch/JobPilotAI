import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.models import CandidateProfile
from app.models.user import (
    AuthSession,
    PasswordResetToken,
    PreAuthChallenge,
    ProfileOwnershipAdoption,
    User,
)

PASSWORD_MIN_LENGTH: Final = 15
PASSWORD_MAX_LENGTH: Final = 128
SESSION_IDLE_TIMEOUT: Final = timedelta(hours=12)
SESSION_ABSOLUTE_LIFETIME: Final = timedelta(days=7)
PRE_AUTH_CHALLENGE_LIFETIME: Final = timedelta(minutes=5)
PASSWORD_RESET_TOKEN_LIFETIME: Final = timedelta(minutes=30)
_EMAIL_ADAPTER: Final = TypeAdapter(EmailStr)
_PASSWORD_HASHER: Final = PasswordHasher(type=Type.ID)
_DUMMY_PASSWORD_HASH: Final = _PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


class OwnerAlreadyExistsError(RuntimeError):
    pass


class UnsupportedAuthDatabaseError(RuntimeError):
    pass


class AccountNotFoundError(RuntimeError):
    pass


class ProfilesNotFoundError(RuntimeError):
    pass


class ProfilesAlreadyAssignedError(RuntimeError):
    pass


class IncorrectCurrentPasswordError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_database_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_login_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("Enter a valid email address.")

    candidate = email.strip().lower()
    if not candidate or len(candidate) > 254:
        raise ValueError("Enter a valid email address.")

    try:
        normalized = str(_EMAIL_ADAPTER.validate_python(candidate)).lower()
    except ValidationError:
        raise ValueError("Enter a valid email address.") from None

    if len(normalized) > 254:
        raise ValueError("Enter a valid email address.")
    return normalized


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not (PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH):
        raise ValueError(f"Password must be between {PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters.")


def hash_password(password: str) -> str:
    validate_password(password)
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not isinstance(password, str) or not isinstance(password_hash, str):
        return False

    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, UnicodeError):
        return False


def verify_login_password(password: str, user: User | None) -> bool:
    password_hash = _DUMMY_PASSWORD_HASH if user is None else user.password_hash
    verified = verify_password(password, password_hash)
    return user is not None and user.is_active and verified


def consume_pre_auth_challenge(
    session: Session,
    token: str | None,
    cookie_binding: str | None,
    now: datetime | None = None,
) -> bool:
    if not token or not cookie_binding:
        return False

    now = utc_now() if now is None else now
    with session.begin():
        challenge = session.scalar(
            select(PreAuthChallenge).where(PreAuthChallenge.token_hash == hash_token(token)).with_for_update()
        )
        if challenge is None or challenge.consumed_at is not None:
            return False
        if normalize_database_datetime(challenge.expires_at) <= now:
            return False
        if not secrets.compare_digest(
            challenge.cookie_binding_hash,
            hash_token(cookie_binding),
        ):
            return False

        result = session.execute(
            update(PreAuthChallenge)
            .where(
                PreAuthChallenge.id == challenge.id,
                PreAuthChallenge.consumed_at.is_(None),
                PreAuthChallenge.expires_at > now,
            )
            .values(consumed_at=now)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1


def create_auth_session(
    session: Session,
    user: User,
    now: datetime | None = None,
) -> tuple[AuthSession, str, str]:
    now = utc_now() if now is None else now
    raw_session_token = secrets.token_urlsafe(32)
    raw_csrf_token = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(raw_session_token),
        csrf_token_hash=hash_token(raw_csrf_token),
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + SESSION_IDLE_TIMEOUT,
        absolute_expires_at=now + SESSION_ABSOLUTE_LIFETIME,
    )
    session.add(auth_session)
    return auth_session, raw_session_token, raw_csrf_token


def reset_password(session: Session, email: str, password: str) -> None:
    normalized_email = normalize_login_email(email)
    password_hash = hash_password(password)

    with session.begin():
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "postgresql":
            session.execute(text("LOCK TABLE users IN EXCLUSIVE MODE"))
        elif dialect_name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            raise UnsupportedAuthDatabaseError(f"Password reset does not support the {dialect_name} database engine.")

        user = session.scalar(select(User).where(User.email == normalized_email).with_for_update())
        if user is None:
            raise AccountNotFoundError("The requested account does not exist.")

        user.password_hash = password_hash
        session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=utc_now())
        )
        session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(consumed_at=utc_now())
        )


def create_password_reset_token(
    session: Session,
    email: str,
    now: datetime | None = None,
) -> tuple[str, str] | None:
    try:
        normalized_email = normalize_login_email(email)
    except ValueError:
        return None

    now = utc_now() if now is None else now
    result: tuple[str, str] | None = None
    with session.begin():
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        elif dialect_name != "postgresql":
            raise UnsupportedAuthDatabaseError(
                f"Password reset does not support the {dialect_name} database engine."
            )

        session.execute(
            delete(PasswordResetToken).where(
                (PasswordResetToken.expires_at <= now) | PasswordResetToken.consumed_at.is_not(None)
            )
        )
        user_query = select(User).where(User.email == normalized_email, User.is_active.is_(True))
        if dialect_name == "postgresql":
            user_query = user_query.with_for_update()
        user = session.scalar(user_query)
        if user is not None:
            session.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
            raw_token = secrets.token_urlsafe(32)
            session.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hash_token(raw_token),
                    created_at=now,
                    expires_at=now + PASSWORD_RESET_TOKEN_LIFETIME,
                )
            )
            result = user.email, raw_token
    return result


def complete_password_reset(
    session: Session,
    raw_token: str,
    new_password: str,
    now: datetime | None = None,
) -> bool:
    validate_password(new_password)
    now = utc_now() if now is None else now
    token_digest = hash_token(raw_token)

    with session.begin():
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        elif dialect_name != "postgresql":
            raise UnsupportedAuthDatabaseError(
                f"Password reset does not support the {dialect_name} database engine."
            )

        reset_user_id = session.scalar(
            select(PasswordResetToken.user_id).where(PasswordResetToken.token_hash == token_digest)
        )
        if reset_user_id is None:
            return False

        user_query = select(User).where(User.id == reset_user_id).with_for_update()
        user = session.scalar(user_query)
        reset_token = session.scalar(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_digest)
            .with_for_update()
        )
        if (
            user is None
            or not user.is_active
            or reset_token is None
            or reset_token.user_id != user.id
            or reset_token.consumed_at is not None
            or normalize_database_datetime(reset_token.expires_at) <= now
        ):
            return False

        user.password_hash = hash_password(new_password)
        session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
    return True


def change_password(
    session: Session,
    user_id: UUID,
    current_password: str,
    new_password: str,
) -> None:
    """Update one authenticated user's password and revoke all their sessions."""
    validate_password(new_password)
    if current_password == new_password:
        raise ValueError("Choose a new password that differs from your current password.")
    new_hash = hash_password(new_password)

    with session.begin():
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        elif dialect_name != "postgresql":
            raise UnsupportedAuthDatabaseError("Password change does not support this database engine.")

        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or not user.is_active:
            raise AccountNotFoundError("The authenticated account is unavailable.")
        if not verify_password(current_password, user.password_hash):
            raise IncorrectCurrentPasswordError("The current password is incorrect.")

        user.password_hash = new_hash
        session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=utc_now())
        )
        session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(consumed_at=utc_now())
        )


def bootstrap_owner(session: Session, email: str, password: str) -> User:
    normalized_email = normalize_login_email(email)
    password_hash = hash_password(password)

    with session.begin():
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "postgresql":
            session.execute(text("LOCK TABLE users IN EXCLUSIVE MODE"))
        elif dialect_name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            raise UnsupportedAuthDatabaseError(f"Owner bootstrap does not support the {dialect_name} database engine.")

        existing_user_id = session.scalar(select(User.id).limit(1))
        if existing_user_id is not None:
            raise OwnerAlreadyExistsError("An owner account already exists; refusing to create another.")

        user = User(email=normalized_email, password_hash=password_hash)
        session.add(user)
        session.flush()

    return user


def adopt_candidate_profiles(
    session: Session,
    email: str,
    profile_ids: list[UUID],
) -> int:
    normalized_email = normalize_login_email(email)
    if not profile_ids or len(set(profile_ids)) != len(profile_ids):
        raise ValueError("Provide unique candidate profile IDs.")

    with session.begin():
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        elif dialect_name != "postgresql":
            raise UnsupportedAuthDatabaseError(
                f"Profile adoption is unsupported for the {dialect_name} database engine."
            )

        user_query = select(User).where(
            User.email == normalized_email,
            User.is_active.is_(True),
        )
        if dialect_name == "postgresql":
            user_query = user_query.with_for_update()
        user = session.scalar(user_query)
        if user is None:
            raise AccountNotFoundError("The requested account does not exist.")

        profiles_query = (
            select(CandidateProfile).where(CandidateProfile.id.in_(profile_ids)).order_by(CandidateProfile.id)
        )
        if dialect_name == "postgresql":
            profiles_query = profiles_query.with_for_update()
        profiles = list(session.scalars(profiles_query))
        if len(profiles) != len(profile_ids):
            raise ProfilesNotFoundError("One or more candidate profiles were not found.")
        if any(profile.user_id is not None for profile in profiles):
            raise ProfilesAlreadyAssignedError("One or more candidate profiles are already assigned.")

        for profile in profiles:
            profile.user_id = user.id
            session.add(
                ProfileOwnershipAdoption(
                    candidate_profile_id=profile.id,
                    previous_user_id=None,
                    new_user_id=user.id,
                    actor_user_id=user.id,
                    action="adopt",
                )
            )

    return len(profiles)
