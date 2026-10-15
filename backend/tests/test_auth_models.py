from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    AuthSession,
    CandidateProfile,
    PreAuthChallenge,
    ProfileOwnershipAdoption,
    User,
)


def test_user_profile_and_auth_session_relationships_store_hashes(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    now = datetime.now(timezone.utc)
    raw_session_token = "synthetic-session-token"
    raw_csrf_token = "synthetic-csrf-token"
    user = User(
        email="owner@example.test",
        password_hash="$argon2id$synthetic-test-hash",
    )
    profile = CandidateProfile(name="Synthetic Candidate")
    user.candidate_profiles.append(profile)
    session = AuthSession(
        token_hash=hashlib.sha256(raw_session_token.encode()).hexdigest(),
        csrf_token_hash=hashlib.sha256(raw_csrf_token.encode()).hexdigest(),
        created_at=now,
        idle_expires_at=now + timedelta(hours=12),
        absolute_expires_at=now + timedelta(days=7),
    )
    user.sessions.append(session)

    with factory.begin() as db_session:
        db_session.add(user)
        db_session.flush()
        assert profile.user_id == user.id
        assert session.user_id == user.id

    with factory() as db_session:
        stored = db_session.get(AuthSession, session.id)
        assert stored is not None
        assert stored.token_hash == hashlib.sha256(raw_session_token.encode()).hexdigest()
        assert stored.csrf_token_hash == hashlib.sha256(raw_csrf_token.encode()).hexdigest()
        assert raw_session_token not in stored.token_hash
        assert raw_csrf_token not in stored.csrf_token_hash
        assert db_session.get(CandidateProfile, profile.id).user_id == user.id


def test_user_email_must_be_normalized_and_unique(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    with factory.begin() as session:
        session.add(User(email="owner@example.test", password_hash="test-hash"))

    with factory.begin() as session:
        session.add(User(email="owner@example.test", password_hash="another-hash"))
        with pytest.raises(IntegrityError):
            session.flush()

    with factory.begin() as session:
        session.add(User(email=" Owner@example.test ", password_hash="test-hash"))
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize(
    "record",
    [
        lambda now: AuthSession(
            token_hash="short",
            csrf_token_hash="a" * 64,
            created_at=now,
            idle_expires_at=now + timedelta(hours=12),
            absolute_expires_at=now + timedelta(days=7),
        ),
        lambda now: AuthSession(
            token_hash="a" * 64,
            csrf_token_hash="b" * 64,
            created_at=now,
            idle_expires_at=now + timedelta(days=8),
            absolute_expires_at=now + timedelta(days=7),
        ),
    ],
)
def test_auth_session_hash_and_expiry_constraints(
    database: tuple[Engine, sessionmaker[Session]],
    record,
) -> None:
    _, factory = database
    now = datetime.now(timezone.utc)
    with factory.begin() as session:
        user = User(email="owner@example.test", password_hash="test-hash")
        user.sessions.append(record(now))
        session.add(user)
        with pytest.raises(IntegrityError):
            session.flush()


def test_pre_auth_challenge_constraints(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    now = datetime.now(timezone.utc)
    with factory.begin() as session:
        session.add(
            PreAuthChallenge(
                token_hash="a" * 64,
                cookie_binding_hash="b" * 64,
                created_at=now,
                expires_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_ownership_adoption_records_actor_and_references_users(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    engine, factory = database
    user = User(email="owner@example.test", password_hash="test-hash")
    user.id = uuid4()
    adoption = ProfileOwnershipAdoption(
        candidate_profile_id=uuid4(),
        new_user_id=user.id,
        actor_user_id=user.id,
        action="adopt",
    )
    with factory.begin() as session:
        session.add(user)
        session.add(adoption)
        session.flush()
        assert adoption.previous_user_id is None

    foreign_keys = inspect(engine).get_foreign_keys("profile_ownership_adoptions")
    referred_tables = [fk["referred_table"] for fk in foreign_keys]
    assert referred_tables == ["users", "users", "users"]
    profile_foreign_keys = inspect(engine).get_foreign_keys("candidate_profiles")
    assert any(fk["referred_table"] == "users" for fk in profile_foreign_keys)
