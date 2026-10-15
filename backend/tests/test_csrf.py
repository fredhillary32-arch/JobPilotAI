from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.user import PreAuthChallenge
from app.services.auth import consume_pre_auth_challenge, hash_token


def test_pre_auth_challenge_binds_cookie_and_is_consumed_once(database) -> None:
    _, factory = database
    now = datetime.now(timezone.utc)
    token = "synthetic-pre-auth-token"
    cookie_binding = "synthetic-pre-auth-cookie"
    with factory.begin() as session:
        session.add(
            PreAuthChallenge(
                token_hash=hash_token(token),
                cookie_binding_hash=hash_token(cookie_binding),
                created_at=now,
                expires_at=now + timedelta(minutes=5),
            )
        )

    with factory() as session:
        assert not consume_pre_auth_challenge(
            session,
            token,
            "different-cookie-value",
            now,
        )
    with factory() as session:
        assert consume_pre_auth_challenge(session, token, cookie_binding, now)
    with factory() as session:
        assert not consume_pre_auth_challenge(session, token, cookie_binding, now)
        challenge = session.scalar(
            select(PreAuthChallenge).where(PreAuthChallenge.token_hash == hash_token(token))
        )
        assert challenge is not None
        assert challenge.consumed_at is not None


def test_expired_pre_auth_challenge_cannot_be_consumed(database) -> None:
    _, factory = database
    now = datetime.now(timezone.utc)
    token = "synthetic-expired-token"
    cookie_binding = "synthetic-expired-cookie"
    with factory.begin() as session:
        session.add(
            PreAuthChallenge(
                token_hash=hash_token(token),
                cookie_binding_hash=hash_token(cookie_binding),
                created_at=now - timedelta(minutes=2),
                expires_at=now - timedelta(minutes=1),
            )
        )

    with factory() as session:
        assert not consume_pre_auth_challenge(session, token, cookie_binding, now)
