from datetime import datetime, timedelta, timezone
import hashlib
import secrets
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
    PreAuthChallenge,
    ProfileOwnershipAdoption,
    User,
)

PASSWORD_MIN_LENGTH: Final = 15
PASSWORD_MAX_LENGTH: Final = 128
SESSION_IDLE_TIMEOUT: Final = timedelta(hours=12)
SESSION_ABSOLUTE_LIFETIME: Final = timedelta(days=7)
PRE_AUTH_CHALLENGE_LIFETIME: Final = timedelta(minutes=5)
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
    if not isinstance(password, str) or not (
        PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH
    ):
        raise ValueError(
            f"Password must be between {PASSWORD_MIN_LENGTH} and "
            f"{PASSWORD_MAX_LENGTH} characters."
        )


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
            select(PreAuthChallenge)
            .where(PreAuthChallenge.token_hash == hash_token(token))
            .with_for_update()
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
            raise UnsupportedAuthDatabaseError(
                f"Password reset does not support the {dialect_name} database engine."
            )

        user = session.scalar(
            select(User)
            .where(User.email == normalized_email)
            .with_for_update()
        )
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
            raise UnsupportedAuthDatabaseError(
                f"Owner bootstrap does not support the {dialect_name} database engine."
            )

        existing_user_id = session.scalar(select(User.id).limit(1))
        if existing_user_id is not None:
            raise OwnerAlreadyExistsError(
                "An owner account already exists; refusing to create another."
            )

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
            select(CandidateProfile)
            .where(CandidateProfile.id.in_(profile_ids))
            .order_by(CandidateProfile.id)
        )
        if dialect_name == "postgresql":
            profiles_query = profiles_query.with_for_update()
        profiles = list(session.scalars(profiles_query))
        if len(profiles) != len(profile_ids):
            raise ProfilesNotFoundError("One or more candidate profiles were not found.")
        if any(profile.user_id is not None for profile in profiles):
            raise ProfilesAlreadyAssignedError(
                "One or more candidate profiles are already assigned."
            )

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
