import secrets
from collections.abc import Generator
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1 import auth as auth_api
from app.main import app
from app.models.user import AuthSession, PasswordResetToken, User
from app.services.auth import hash_password, hash_token, utc_now, verify_password
from app.services.password_reset_limiter import password_reset_limiter
from app.settings import Settings, get_settings

ORIGIN = "http://127.0.0.1:5173"
PRE_AUTH_URL = "/api/v1/auth/pre-auth-csrf"
REQUEST_RESET_URL = "/api/v1/auth/password-reset/request"
CONFIRM_RESET_URL = "/api/v1/auth/password-reset/confirm"


@pytest.fixture
def recovery_client(
    unauthenticated_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    _, factory = database
    settings = Settings(
        postgres_user="test-user",
        postgres_password="test-password",
        postgres_db="test-db",
        auth_allowed_origin=ORIGIN,
        auth_local_http=True,
        password_reset_smtp_host="smtp.example.test",
        password_reset_smtp_username="mailer",
        password_reset_smtp_password="smtp-test-password",
        password_reset_sender_email="noreply@example.com",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    password_reset_limiter.reset()
    try:
        yield unauthenticated_client, factory
    finally:
        password_reset_limiter.reset()
        app.dependency_overrides.pop(get_settings, None)


def _request_reset(client: TestClient, email: str, *, origin: str = ORIGIN, token: str | None = None):
    challenge = client.get(PRE_AUTH_URL, headers={"Origin": ORIGIN}).json()["csrf_token"] if token is None else token
    return client.post(
        REQUEST_RESET_URL,
        headers={"Origin": origin, "X-CSRF-Token": challenge},
        json={"email": email},
    )


def _confirmation_token(reset_url: str) -> str:
    return parse_qs(urlsplit(reset_url).fragment)["reset"][0]


def test_reset_request_is_neutral_and_email_link_resets_password_and_sessions(
    recovery_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = recovery_client
    old_password = "correct horse battery staple"
    now = utc_now()
    delivered: list[tuple[str, str]] = []
    with factory.begin() as session:
        user = User(email="owner@example.com", password_hash=hash_password(old_password))
        session.add(user)
        session.flush()
        session.add(
            AuthSession(
                user_id=user.id,
                token_hash=hash_token("existing-session"),
                csrf_token_hash=hash_token("existing-csrf"),
                created_at=now,
                idle_expires_at=now + timedelta(hours=12),
                absolute_expires_at=now + timedelta(days=7),
            )
        )

    monkeypatch.setattr(
        auth_api,
        "send_password_reset_email",
        lambda settings, email, url: delivered.append((email, url)),
    )

    known = _request_reset(client, "OWNER@example.com")
    unknown = _request_reset(client, "nobody@example.com")

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert delivered[0][0] == "owner@example.com"
    with factory() as session:
        assert session.scalar(select(User).where(User.email == "nobody@example.com")) is None
    reset_token = _confirmation_token(delivered[0][1])
    assert reset_token not in delivered[0][1].split("#")[0]
    with factory() as session:
        token = session.scalar(select(PasswordResetToken))
        assert token is not None and token.token_hash == hash_token(reset_token)
        assert reset_token not in token.token_hash

    new_password = "a replacement password with enough length"
    challenge = client.get(PRE_AUTH_URL, headers={"Origin": ORIGIN}).json()["csrf_token"]
    response = client.post(
        CONFIRM_RESET_URL,
        headers={"Origin": ORIGIN, "X-CSRF-Token": challenge},
        json={
            "token": reset_token,
            "new_password": new_password,
            "confirm_new_password": new_password,
        },
    )

    assert response.status_code == 204
    with factory() as session:
        user = session.scalar(select(User).where(User.email == "owner@example.com"))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(new_password, user.password_hash)
        assert not verify_password(old_password, user.password_hash)
        auth_session = session.scalar(select(AuthSession))
        assert auth_session is not None and auth_session.revoked_at is not None
        token = session.scalar(select(PasswordResetToken))
        assert token is not None and token.consumed_at is not None

    reused_challenge = client.get(PRE_AUTH_URL, headers={"Origin": ORIGIN}).json()["csrf_token"]
    reused = client.post(
        CONFIRM_RESET_URL,
        headers={"Origin": ORIGIN, "X-CSRF-Token": reused_challenge},
        json={
            "token": reset_token,
            "new_password": "another replacement password",
            "confirm_new_password": "another replacement password",
        },
    )
    assert reused.status_code == 400


def test_password_reset_requires_origin_and_one_use_pre_auth_csrf(recovery_client) -> None:
    client, _ = recovery_client
    wrong_origin = _request_reset(client, "owner@example.com", origin="https://attacker.example")
    assert wrong_origin.status_code == 403

    missing_csrf = client.post(
        REQUEST_RESET_URL,
        headers={"Origin": ORIGIN},
        json={"email": "owner@example.com"},
    )
    assert missing_csrf.status_code == 403


def test_reset_api_rejects_missing_email_proof_and_identity_substitution(
    recovery_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = recovery_client
    with factory.begin() as session:
        session.add_all(
            [
                User(email="owner@example.com", password_hash=hash_password("owner original password")),
                User(email="other@example.com", password_hash=hash_password("other original password")),
            ]
        )
    delivered: list[tuple[str, str]] = []
    monkeypatch.setattr(
        auth_api,
        "send_password_reset_email",
        lambda settings, email, url: delivered.append((email, url)),
    )
    assert _request_reset(client, "other@example.com").status_code == 202
    assert delivered[0][0] == "other@example.com"
    token = _confirmation_token(delivered[0][1])
    with factory() as session:
        owner = session.scalar(select(User).where(User.email == "owner@example.com"))
        other = session.scalar(select(User).where(User.email == "other@example.com"))
        assert owner is not None and other is not None
        owner_id = str(owner.id)

    password = "a replacement password with enough length"
    for payload in (
        {
            "token": secrets.token_urlsafe(32),
            "new_password": password,
            "confirm_new_password": password,
        },
        {
            "token": token,
            "email": "owner@example.com",
            "user_id": owner_id,
            "new_password": password,
            "confirm_new_password": password,
        },
    ):
        challenge = client.get(PRE_AUTH_URL, headers={"Origin": ORIGIN}).json()["csrf_token"]
        response = client.post(
            CONFIRM_RESET_URL,
            headers={"Origin": ORIGIN, "X-CSRF-Token": challenge},
            json=payload,
        )
        assert response.status_code == 400

    with factory() as session:
        owner = session.scalar(select(User).where(User.email == "owner@example.com"))
        other = session.scalar(select(User).where(User.email == "other@example.com"))
        assert owner is not None and verify_password("owner original password", owner.password_hash)
        assert other is not None and verify_password("other original password", other.password_hash)


def test_password_reset_requests_are_rate_limited_by_client(recovery_client) -> None:
    client, _ = recovery_client

    responses = [_request_reset(client, "nobody@example.com").status_code for _ in range(6)]

    assert responses == [202, 202, 202, 202, 202, 429]


@pytest.mark.parametrize(
    ("new_password", "confirm_new_password"),
    [
        ("short", "short"),
        ("a sufficiently long password", "different sufficiently long password"),
    ],
)
def test_password_reset_rejects_bad_passwords_without_changing_user(
    recovery_client,
    monkeypatch: pytest.MonkeyPatch,
    new_password: str,
    confirm_new_password: str,
) -> None:
    client, factory = recovery_client
    original = "correct horse battery staple"
    with factory.begin() as session:
        session.add(User(email="owner@example.com", password_hash=hash_password(original)))
    delivered: list[str] = []
    monkeypatch.setattr(
        auth_api,
        "send_password_reset_email",
        lambda settings, email, url: delivered.append(url),
    )
    assert _request_reset(client, "owner@example.com").status_code == 202
    token = _confirmation_token(delivered[0])

    challenge = client.get(PRE_AUTH_URL, headers={"Origin": ORIGIN}).json()["csrf_token"]
    response = client.post(
        CONFIRM_RESET_URL,
        headers={"Origin": ORIGIN, "X-CSRF-Token": challenge},
        json={
            "token": token,
            "new_password": new_password,
            "confirm_new_password": confirm_new_password,
        },
    )

    assert response.status_code == 422
    with factory() as session:
        user = session.scalar(select(User).where(User.email == "owner@example.com"))
        assert user is not None and verify_password(original, user.password_hash)
        reset_token = session.scalar(select(PasswordResetToken))
        assert reset_token is not None and reset_token.consumed_at is None


def test_password_reset_request_is_unavailable_without_email_configuration(
    unauthenticated_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    _, factory = database
    password_reset_limiter.reset()
    with factory.begin() as session:
        session.add(User(email="owner@example.com", password_hash=hash_password("correct horse battery staple")))

    response = _request_reset(unauthenticated_client, "owner@example.com")

    assert response.status_code == 503
    with factory() as session:
        assert session.scalar(select(PasswordResetToken)) is None


def test_expired_password_reset_link_cannot_change_password(
    recovery_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = recovery_client
    old_password = "correct horse battery staple"
    with factory.begin() as session:
        session.add(User(email="owner@example.com", password_hash=hash_password(old_password)))
    delivered: list[str] = []
    monkeypatch.setattr(
        auth_api,
        "send_password_reset_email",
        lambda settings, email, url: delivered.append(url),
    )
    assert _request_reset(client, "owner@example.com").status_code == 202
    reset_token = _confirmation_token(delivered[0])
    with factory.begin() as session:
        token = session.scalar(select(PasswordResetToken))
        assert token is not None
        now = utc_now()
        token.created_at = now - timedelta(hours=1)
        token.expires_at = now - timedelta(minutes=30)

    challenge = client.get(PRE_AUTH_URL, headers={"Origin": ORIGIN}).json()["csrf_token"]
    response = client.post(
        CONFIRM_RESET_URL,
        headers={"Origin": ORIGIN, "X-CSRF-Token": challenge},
        json={
            "token": reset_token,
            "new_password": "a replacement password with enough length",
            "confirm_new_password": "a replacement password with enough length",
        },
    )

    assert response.status_code == 400
    with factory() as session:
        user = session.scalar(select(User).where(User.email == "owner@example.com"))
        assert user is not None and verify_password(old_password, user.password_hash)
