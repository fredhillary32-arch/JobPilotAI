import getpass
import warnings
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.cli import main
from app.models.user import User
from app.services.auth import hash_password


def _run_cli(
    factory: sessionmaker[Session],
    email: str,
    password: str,
    confirmation: str,
    capsys,
) -> tuple[int, str]:
    prompts: Iterator[str] = iter([password, confirmation])
    result = main(
        ["bootstrap-owner"],
        input_fn=lambda _: email,
        password_prompt=lambda _: next(prompts),
        session_factory=factory,
    )
    return result, capsys.readouterr().out


def test_bootstrap_cli_creates_owner_without_printing_password_or_hash(
    database,
    capsys,
) -> None:
    _, factory = database
    password = "a secure password with spaces"

    result, output = _run_cli(factory, "owner@example.com", password, password, capsys)

    assert result == 0
    assert output.strip() == "Owner account created."
    assert password not in output
    with factory() as session:
        user = session.query(User).one()
        assert password not in user.password_hash
        assert user.password_hash not in output


def test_bootstrap_cli_refuses_repeated_setup_without_disclosing_secrets(
    database,
    capsys,
) -> None:
    _, factory = database
    password = "a secure password with spaces"
    with factory.begin() as session:
        session.add(
            User(
                email="owner@example.com",
                password_hash=hash_password(password),
            )
        )

    result, output = _run_cli(factory, "owner@example.com", password, password, capsys)

    assert result == 1
    assert output.strip() == "An owner account already exists; bootstrap refused."
    assert password not in output
    with factory() as session:
        assert session.query(User).count() == 1


def test_bootstrap_cli_rejects_invalid_input_without_creating_user(
    database,
    capsys,
) -> None:
    _, factory = database
    result = main(
        ["bootstrap-owner"],
        input_fn=lambda _: "not-an-email",
        password_prompt=lambda _: pytest.fail("Password prompt should not run for invalid email."),
        session_factory=factory,
    )

    assert result == 2
    assert "valid email" in capsys.readouterr().out
    with factory() as session:
        assert session.query(User).count() == 0


def test_bootstrap_cli_rejects_password_mismatch_without_creating_user(
    database,
    capsys,
) -> None:
    _, factory = database
    result, output = _run_cli(
        factory,
        "owner@example.com",
        "a secure password with spaces",
        "a different secure password",
        capsys,
    )

    assert result == 2
    assert "did not match" in output
    assert "a secure password with spaces" not in output
    with factory() as session:
        assert session.query(User).count() == 0


def test_bootstrap_cli_accepts_matching_unicode_password_confirmation(
    database,
    capsys,
) -> None:
    _, factory = database
    password = "correct horse battery staple 🔒"

    result, output = _run_cli(factory, "owner@example.com", password, password, capsys)

    assert result == 0
    assert output.strip() == "Owner account created."
    assert password not in output
    with factory() as session:
        user = session.query(User).one()
        assert user.password_hash.startswith("$argon2id$")
        assert password not in user.password_hash


def test_bootstrap_cli_rejects_mismatched_unicode_password_confirmation(
    database,
    capsys,
) -> None:
    _, factory = database

    result, output = _run_cli(
        factory,
        "owner@example.com",
        "correct horse battery staple 🔒",
        "correct horse battery staple 🔐",
        capsys,
    )

    assert result == 2
    assert "did not match" in output
    assert "correct horse battery staple" not in output
    with factory() as session:
        assert session.query(User).count() == 0


def test_bootstrap_cli_handles_unsupported_database_without_traceback_or_secret(
    database,
    monkeypatch,
    capsys,
) -> None:
    engine, factory = database
    monkeypatch.setattr(engine.dialect, "name", "unsupported")
    password = "a secure password with spaces"
    result, output = _run_cli(factory, "owner@example.com", password, password, capsys)

    assert result == 1
    assert output.strip() == "Owner bootstrap is unsupported for this database engine."
    assert password not in output
    with factory() as session:
        assert session.query(User).count() == 0


def test_bootstrap_cli_fails_closed_if_hidden_password_prompt_is_unavailable(
    database,
    monkeypatch,
    capsys,
) -> None:
    _, factory = database

    def echo_fallback(_: str) -> str:
        warnings.warn("echo fallback", getpass.GetPassWarning)
        return "a secure password with spaces"

    monkeypatch.setattr(getpass, "getpass", echo_fallback)

    result = main(
        ["bootstrap-owner"],
        input_fn=lambda _: "owner@example.com",
        session_factory=factory,
    )

    assert result == 2
    output = capsys.readouterr().out
    assert "Hidden password entry is unavailable" in output
    with factory() as session:
        assert session.query(User).count() == 0
