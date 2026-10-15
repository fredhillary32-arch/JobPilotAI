import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.user import User
from app.services.auth import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    OwnerAlreadyExistsError,
    UnsupportedAuthDatabaseError,
    bootstrap_owner,
    hash_password,
    verify_password,
)


def test_bootstrap_owner_normalizes_email_and_stores_only_argon2id_hash(
    database,
) -> None:
    _, factory = database
    password = "a secure password with spaces"
    with factory() as session:
        user = bootstrap_owner(session, "  Owner@Example.Com  ", password)
        user_id = user.id

    with factory() as session:
        stored_user = session.get(User, user_id)
        assert stored_user is not None
        assert stored_user.email == "owner@example.com"
        assert stored_user.password_hash.startswith("$argon2id$")
        assert stored_user.password_hash != password
        assert verify_password(password, stored_user.password_hash)
        assert not verify_password("a different secure password", stored_user.password_hash)
        assert password not in stored_user.password_hash


def test_bootstrap_owner_refuses_repeated_setup_and_normalized_duplicate_email(
    database,
) -> None:
    _, factory = database
    with factory() as session:
        bootstrap_owner(session, "Owner@Example.Com", "a secure password with spaces")

    with factory() as session:
        with pytest.raises(OwnerAlreadyExistsError):
            bootstrap_owner(
                session,
                " owner@example.com ",
                "another secure password with spaces",
            )

    with factory() as session:
        assert session.query(User).count() == 1


@pytest.mark.parametrize(
    "email",
    ["", "not-an-email", "owner@", "x" * 250 + "@example.test"],
)
def test_invalid_bootstrap_email_is_rejected(email: str, database) -> None:
    _, factory = database
    with factory() as session:
        with pytest.raises(ValueError, match="valid email"):
            bootstrap_owner(session, email, "a secure password with spaces")


@pytest.mark.parametrize(
    "password",
    [
        "s" * (PASSWORD_MIN_LENGTH - 1),
        "s" * (PASSWORD_MAX_LENGTH + 1),
    ],
)
def test_invalid_bootstrap_password_is_rejected(password: str, database) -> None:
    _, factory = database
    with factory() as session:
        with pytest.raises(ValueError, match="between 15 and 128"):
            bootstrap_owner(session, "owner@example.com", password)


@pytest.mark.parametrize(
    "length",
    [PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH],
)
def test_password_length_boundaries_are_accepted(length: int) -> None:
    password = "x" * length
    encoded = hash_password(password)
    assert verify_password(password, encoded)


def test_invalid_or_mismatched_password_hash_verifies_false() -> None:
    assert not verify_password("any password", "not-an-argon2-hash")
    assert not verify_password("any password", "$argon2id$malformed-\u2603")
    assert not verify_password("wrong password", hash_password("a secure password"))


@pytest.mark.parametrize(
    ("password", "password_hash"),
    [
        (None, "$argon2id$not-used"),
        ("valid-looking password", None),
        (123, "$argon2id$not-used"),
        ("valid-looking password", 123),
    ],
)
def test_password_verification_rejects_non_string_values(
    password,
    password_hash,
) -> None:
    assert not verify_password(password, password_hash)


def test_bootstrap_fails_closed_on_unsupported_database_engine(
    database,
    monkeypatch,
) -> None:
    engine, factory = database
    monkeypatch.setattr(engine.dialect, "name", "unsupported")

    with factory() as session:
        with pytest.raises(UnsupportedAuthDatabaseError):
            bootstrap_owner(session, "owner@example.com", "a secure password")

    with factory() as session:
        assert session.query(User).count() == 0


def test_bootstrap_serializes_concurrent_sqlite_attempts(tmp_path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'bootstrap.db'}",
        connect_args={"timeout": 10},
    )
    User.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = Barrier(2)

    def attempt(email: str) -> bool:
        barrier.wait()
        with factory() as session:
            try:
                bootstrap_owner(session, email, "a secure password")
            except OwnerAlreadyExistsError:
                return False
            return True

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    attempt,
                    ["owner-one@example.com", "owner-two@example.com"],
                )
            )

        assert sorted(results) == [False, True]
        with factory() as session:
            assert session.query(User).count() == 1
    finally:
        engine.dispose()
