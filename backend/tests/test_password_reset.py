from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.cli import main
from app.models.user import AuthSession, User
from app.services.auth import hash_password, hash_token, verify_password


def _run_reset(
    factory: sessionmaker[Session],
    email: str,
    email_confirmation: str,
    password: str,
    password_confirmation: str,
    capsys,
) -> tuple[int, str]:
    inputs: Iterator[str] = iter([email, email_confirmation])
    passwords: Iterator[str] = iter([password, password_confirmation])
    result = main(
        ["reset-password"],
        input_fn=lambda _: next(inputs),
        password_prompt=lambda _: next(passwords),
        session_factory=factory,
    )
    return result, capsys.readouterr().out


def test_local_password_reset_changes_hash_and_revokes_all_sessions(
    database,
    capsys,
) -> None:
    _, factory = database
    now = datetime.now(timezone.utc)
    old_password = "previous secure password"
    new_password = "new secure password with spaces"
    raw_tokens = ["session-one", "session-two"]
    with factory.begin() as session:
        user = User(
            email="owner@example.com",
            password_hash=hash_password(old_password),
        )
        session.add(user)
        session.flush()
        for raw_token in raw_tokens:
            session.add(
                AuthSession(
                    user_id=user.id,
                    token_hash=hash_token(raw_token),
                    csrf_token_hash=hash_token("csrf-" + raw_token),
                    created_at=now,
                    idle_expires_at=now + timedelta(hours=12),
                    absolute_expires_at=now + timedelta(days=7),
                )
            )

    result, output = _run_reset(
        factory,
        " OWNER@example.com ",
        "owner@example.com",
        new_password,
        new_password,
        capsys,
    )

    assert result == 0
    assert new_password not in output
    assert old_password not in output
    with factory() as session:
        stored_user = session.scalar(select(User))
        assert stored_user is not None
        assert verify_password(new_password, stored_user.password_hash)
        assert not verify_password(old_password, stored_user.password_hash)
        stored_sessions = session.scalars(select(AuthSession)).all()
        assert len(stored_sessions) == 2
        assert all(auth_session.revoked_at is not None for auth_session in stored_sessions)


def test_local_password_reset_requires_explicit_account_confirmation(
    database,
    capsys,
) -> None:
    _, factory = database
    with factory.begin() as session:
        session.add(
            User(
                email="owner@example.com",
                password_hash=hash_password("previous secure password"),
            )
        )

    result, output = _run_reset(
        factory,
        "owner@example.com",
        "other@example.com",
        "new secure password with spaces",
        "new secure password with spaces",
        capsys,
    )

    assert result == 2
    assert "did not match" in output
    with factory() as session:
        assert session.query(AuthSession).count() == 0
        stored_user = session.scalar(select(User))
        assert stored_user is not None
        assert not verify_password(
            "new secure password with spaces",
            stored_user.password_hash,
        )


def test_local_password_reset_does_not_echo_new_password_on_failure(
    database,
    capsys,
) -> None:
    _, factory = database
    password = "new secure password with spaces"
    result, output = _run_reset(
        factory,
        "owner@example.com",
        "owner@example.com",
        password,
        password,
        capsys,
    )

    assert result == 1
    assert password not in output
    assert "could not be reset" in output
