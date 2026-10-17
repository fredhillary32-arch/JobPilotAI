from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models.user import AuthSession, PreAuthChallenge, User
from app.services.auth import hash_password, hash_token
from app.services.login_limiter import login_failure_limiter
from app.settings import Settings, get_settings

ORIGIN = "http://127.0.0.1:5173"
PRE_AUTH_URL = "/api/v1/auth/pre-auth-csrf"
LOGIN_URL = "/api/v1/auth/login"
SESSION_URL = "/api/v1/auth/session"
LOGOUT_URL = "/api/v1/auth/logout"


@pytest.fixture
def auth_client(
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
    )
    app.dependency_overrides[get_settings] = lambda: settings
    login_failure_limiter.reset()
    try:
        yield unauthenticated_client, factory
    finally:
        login_failure_limiter.reset()
        app.dependency_overrides.pop(get_settings, None)


def _create_user(factory: sessionmaker[Session], *, active: bool = True) -> str:
    password = "correct horse battery staple"
    with factory.begin() as session:
        session.add(
            User(
                email="owner@example.com",
                password_hash=hash_password(password),
                is_active=active,
            )
        )
    return password


def _challenge(client: TestClient) -> str:
    response = client.get(PRE_AUTH_URL, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert _get_cookie(client, "jobpilot_pre_auth")
    return response.json()["csrf_token"]


def _get_cookie(client: TestClient, name: str) -> str | None:
    cookies = [cookie.value for cookie in client.cookies.jar if cookie.name == name]
    return cookies[-1] if cookies else None


def _set_cookie(client: TestClient, name: str, value: str) -> None:
    for cookie in list(client.cookies.jar):
        if cookie.name == name:
            client.cookies.delete(name, domain=cookie.domain, path=cookie.path)
    client.cookies.set(name, value, domain="testserver.local", path="/")


def _login(
    client: TestClient,
    email: str,
    password: str,
    *,
    csrf_token: str | None = None,
    origin: str = ORIGIN,
):
    csrf_token = _challenge(client) if csrf_token is None else csrf_token
    return client.post(
        LOGIN_URL,
        headers={"Origin": origin, "X-CSRF-Token": csrf_token},
        json={"email": email, "password": password},
    )


def test_login_sets_secure_session_and_returns_minimal_identity(auth_client) -> None:
    client, factory = auth_client
    password = _create_user(factory)

    response = _login(client, " OWNER@example.com ", password)

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "owner@example.com"
    assert set(body["user"]) == {"id", "email"}
    assert len(body["csrf_token"]) >= 40
    cookie_header = response.headers["set-cookie"].lower()
    assert "jobpilot_session=" in cookie_header
    assert "httponly" in cookie_header
    assert "samesite=strict" in cookie_header
    assert "path=/" in cookie_header
    assert "secure" not in cookie_header
    assert "domain=" not in cookie_header

    raw_cookie = client.cookies.get("jobpilot_session")
    assert raw_cookie not in response.text
    assert "jobpilot_session" not in response.json()
    with factory() as session:
        auth_session = session.scalar(select(AuthSession))
        assert auth_session is not None
        assert auth_session.token_hash == hash_token(raw_cookie)
        assert raw_cookie not in auth_session.token_hash
        assert auth_session.idle_expires_at - auth_session.created_at == timedelta(hours=12)
        assert auth_session.absolute_expires_at - auth_session.created_at == timedelta(days=7)


def test_https_mode_sets_secure_pre_auth_cookie(auth_client) -> None:
    client, _ = auth_client
    https_origin = "https://127.0.0.1:5173"
    settings = Settings(
        postgres_user="test-user",
        postgres_password="test-password",
        postgres_db="test-db",
        auth_allowed_origin=https_origin,
        auth_local_http=False,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    response = client.get(
        PRE_AUTH_URL,
        headers={"Origin": https_origin},
    )

    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize("account_state", ["unknown", "wrong_password", "inactive"])
def test_login_failures_are_generic_and_do_not_create_session(
    auth_client,
    account_state: str,
) -> None:
    client, factory = auth_client
    if account_state == "wrong_password":
        _create_user(factory)
        email, password = "owner@example.com", "incorrect but long password"
    elif account_state == "inactive":
        _create_user(factory, active=False)
        email, password = "owner@example.com", "correct horse battery staple"
    else:
        email, password = "nobody@example.com", "incorrect but long password"

    response = _login(client, email, password)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password."}
    with factory() as session:
        assert session.query(AuthSession).count() == 0


def test_login_rejects_missing_or_invalid_pre_auth_csrf_and_origin(auth_client) -> None:
    client, factory = auth_client
    password = _create_user(factory)

    missing_token = client.post(
        LOGIN_URL,
        headers={"Origin": ORIGIN},
        json={"email": "owner@example.com", "password": password},
    )
    assert missing_token.status_code == 403

    token = _challenge(client)
    invalid_origin = _login(
        client,
        "owner@example.com",
        password,
        csrf_token=token,
        origin="http://evil.example",
    )
    assert invalid_origin.status_code == 403

    token = _challenge(client)
    _set_cookie(client, "jobpilot_pre_auth", "wrong-cookie-binding")
    bad_binding = _login(
        client,
        "owner@example.com",
        password,
        csrf_token=token,
    )
    assert bad_binding.status_code == 403
    with factory() as session:
        assert session.query(AuthSession).count() == 0


def test_pre_auth_challenge_is_one_time_and_expiring(auth_client) -> None:
    client, factory = auth_client
    password = _create_user(factory)
    token = _challenge(client)
    original_cookie = _get_cookie(client, "jobpilot_pre_auth")
    assert original_cookie is not None

    first = _login(client, "owner@example.com", password, csrf_token=token)
    assert first.status_code == 200

    _set_cookie(client, "jobpilot_pre_auth", original_cookie)
    replay = _login(client, "owner@example.com", password, csrf_token=token)
    assert replay.status_code == 403

    expired_token = _challenge(client)
    expired_cookie = _get_cookie(client, "jobpilot_pre_auth")
    assert expired_cookie is not None
    with factory.begin() as session:
        challenge = session.scalar(
            select(PreAuthChallenge).where(PreAuthChallenge.token_hash == hash_token(expired_token))
        )
        assert challenge is not None
        challenge.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        challenge.created_at = challenge.expires_at - timedelta(minutes=1)
    _set_cookie(client, "jobpilot_pre_auth", expired_cookie)
    expired = _login(client, "owner@example.com", password, csrf_token=expired_token)
    assert expired.status_code == 403


def test_session_restore_rotates_csrf_and_logout_revokes_session(auth_client) -> None:
    client, factory = auth_client
    password = _create_user(factory)
    login_response = _login(client, "owner@example.com", password)
    assert login_response.status_code == 200
    old_csrf = login_response.json()["csrf_token"]

    restored = client.get(SESSION_URL)
    assert restored.status_code == 200
    new_csrf = restored.json()["csrf_token"]
    assert new_csrf != old_csrf

    rejected_logout = client.post(
        LOGOUT_URL,
        headers={"Origin": ORIGIN, "X-CSRF-Token": old_csrf},
    )
    assert rejected_logout.status_code == 403

    logout_response = client.post(
        LOGOUT_URL,
        headers={"Origin": ORIGIN, "X-CSRF-Token": new_csrf},
    )
    assert logout_response.status_code == 204
    with factory() as session:
        auth_session = session.scalar(select(AuthSession))
        assert auth_session is not None
        assert auth_session.revoked_at is not None

    assert client.get(SESSION_URL).status_code == 401


def test_session_activity_slides_idle_expiry_but_not_absolute_expiry(auth_client) -> None:
    client, factory = auth_client
    now = datetime.now(timezone.utc)
    raw_token = "synthetic-sliding-session-token"
    with factory.begin() as session:
        user = User(
            email="owner@example.com",
            password_hash=hash_password("correct horse battery staple"),
        )
        session.add(user)
        session.flush()
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            csrf_token_hash=hash_token("synthetic-csrf-token"),
            created_at=now - timedelta(hours=5),
            last_seen_at=now - timedelta(hours=1),
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=2),
        )
        session.add(auth_session)
        session.flush()
        session_id = auth_session.id

    client.cookies.set("jobpilot_session", raw_token)
    response = client.get(SESSION_URL)

    assert response.status_code == 200
    with factory() as session:
        stored = session.get(AuthSession, session_id)
        assert stored is not None
        refreshed_idle = stored.idle_expires_at.replace(tzinfo=timezone.utc)
        absolute = stored.absolute_expires_at.replace(tzinfo=timezone.utc)
        assert refreshed_idle > now + timedelta(minutes=30)
        assert refreshed_idle <= absolute
        assert absolute < now + timedelta(days=7)


@pytest.mark.parametrize("expiry", ["idle", "absolute", "revoked"])
def test_expired_or_revoked_session_is_rejected(auth_client, expiry: str) -> None:
    client, factory = auth_client
    now = datetime.now(timezone.utc)
    raw_token = "synthetic-session-token"
    user = User(email="owner@example.com", password_hash=hash_password("correct horse battery staple"))
    with factory.begin() as session:
        session.add(user)
        session.flush()
        if expiry == "idle":
            created_at = now - timedelta(hours=13)
            idle_expires_at = now - timedelta(minutes=1)
            absolute_expires_at = now + timedelta(days=6)
        elif expiry == "absolute":
            created_at = now - timedelta(days=8)
            idle_expires_at = now - timedelta(hours=1)
            absolute_expires_at = now - timedelta(minutes=1)
        else:
            created_at = now - timedelta(minutes=1)
            idle_expires_at = now + timedelta(hours=11)
            absolute_expires_at = now + timedelta(days=6)
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            csrf_token_hash=hash_token("synthetic-csrf-token"),
            created_at=created_at,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            revoked_at=now if expiry == "revoked" else None,
        )
        session.add(auth_session)

    client.cookies.set("jobpilot_session", raw_token)
    response = client.get(SESSION_URL)
    assert response.status_code == 401
    with factory() as session:
        stored = session.get(AuthSession, auth_session.id)
        assert stored is not None
        if expiry in {"idle", "absolute"}:
            assert stored.revoked_at is not None


def test_existing_session_is_revoked_when_user_becomes_inactive(auth_client) -> None:
    client, factory = auth_client
    now = datetime.now(timezone.utc)
    raw_token = "synthetic-session-for-inactive-user"
    with factory.begin() as session:
        user = User(
            email="owner@example.com",
            password_hash=hash_password("correct horse battery staple"),
            is_active=False,
        )
        session.add(user)
        session.flush()
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            csrf_token_hash=hash_token("synthetic-csrf-token"),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(hours=12),
            absolute_expires_at=now + timedelta(days=7),
        )
        session.add(auth_session)

    client.cookies.set("jobpilot_session", raw_token)
    response = client.get(SESSION_URL)

    assert response.status_code == 401
    with factory() as session:
        stored = session.get(AuthSession, auth_session.id)
        assert stored is not None
        assert stored.revoked_at is not None


def test_logout_requires_allowed_origin_and_session_csrf(auth_client) -> None:
    client, factory = auth_client
    password = _create_user(factory)
    csrf = _login(client, "owner@example.com", password).json()["csrf_token"]

    wrong_origin = client.post(
        LOGOUT_URL,
        headers={"Origin": "http://evil.example", "X-CSRF-Token": csrf},
    )
    assert wrong_origin.status_code == 403
    missing_csrf = client.post(LOGOUT_URL, headers={"Origin": ORIGIN})
    assert missing_csrf.status_code == 403
    with factory() as session:
        assert session.scalar(select(AuthSession)).revoked_at is None


def test_login_rate_limit_blocks_after_five_failed_attempts(auth_client) -> None:
    client, _ = auth_client
    for _ in range(5):
        response = _login(client, "owner@example.com", "incorrect but long password")
        assert response.status_code == 401

    throttled = _login(client, "owner@example.com", "incorrect but long password")
    assert throttled.status_code == 429
    assert throttled.json() == {"detail": "Too many login attempts. Try again later."}


def test_one_accounts_failures_do_not_lock_out_another_account_on_the_same_client(auth_client) -> None:
    client, factory = auth_client
    with factory.begin() as session:
        session.add(User(email="colleague@example.com", password_hash=hash_password("another long passphrase")))
    for _ in range(5):
        assert _login(client, "owner@example.com", "incorrect but long password").status_code == 401
    assert _login(client, "owner@example.com", "incorrect but long password").status_code == 429

    other = _login(client, "colleague@example.com", "another long passphrase")

    assert other.status_code == 200


def test_email_variants_share_one_failure_count(auth_client) -> None:
    client, _ = auth_client
    for variant in [
        "owner@example.com",
        "Owner@Example.com",
        " owner@example.com ",
        "OWNER@EXAMPLE.COM",
        "owner@example.com",
    ]:
        assert _login(client, variant, "incorrect but long password").status_code == 401

    assert _login(client, "Owner@example.com", "incorrect but long password").status_code == 429


def test_successful_sign_in_clears_that_accounts_failures(auth_client) -> None:
    client, factory = auth_client
    password = _create_user(factory)
    for _ in range(4):
        assert _login(client, "owner@example.com", "incorrect but long password").status_code == 401
    assert _login(client, "owner@example.com", password).status_code == 200

    for _ in range(5):
        assert _login(client, "owner@example.com", "incorrect but long password").status_code == 401
    assert _login(client, "owner@example.com", "incorrect but long password").status_code == 429


def test_guessing_across_many_accounts_from_one_client_is_capped(auth_client) -> None:
    client, _ = auth_client
    for index in range(50):
        assert _login(client, f"guess{index}@example.com", "incorrect but long password").status_code == 401

    capped = _login(client, "fresh-account@example.com", "incorrect but long password")

    assert capped.status_code == 429


def test_login_request_validation_does_not_echo_password(auth_client) -> None:
    client, _ = auth_client
    secret_input = {"email": "owner@example.com", "password": {"private": "sentinel"}}
    response = client.post(
        LOGIN_URL,
        headers={"Origin": ORIGIN, "X-CSRF-Token": "irrelevant"},
        json=secret_input,
    )

    assert response.status_code == 400
    assert "sentinel" not in response.text


def test_malformed_utf8_login_body_returns_generic_error(auth_client) -> None:
    client, _ = auth_client
    response = client.post(
        LOGIN_URL,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": "irrelevant",
            "Content-Type": "application/json",
        },
        content=b'{"email":"owner@example.com","password":"\xff"}',
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid login request."}
