import hmac
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db import DatabaseSession
from app.models import CandidateProfile
from app.models.user import AuthSession, User
from app.services.auth import (
    SESSION_IDLE_TIMEOUT,
    hash_token,
    normalize_database_datetime,
    utc_now,
)
from app.settings import Settings, get_settings

SESSION_COOKIE_NAME = "jobpilot_session"


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    auth_session: AuthSession


def clear_session_cookie(
    request: Request,
    response: Response,
    settings: Settings,
) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=settings.auth_cookie_secure or request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )


def require_allowed_origin(request: Request, settings: Settings) -> None:
    if request.headers.get("origin") != settings.auth_allowed_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed.",
        )
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed.",
        )


def get_authenticated_session(
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedSession:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    now = utc_now()
    auth_session: AuthSession | None = None
    user: User | None = None
    valid = False
    try:
        with session.begin():
            auth_session = session.scalar(
                select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token)).with_for_update()
            )
            if auth_session is not None:
                user = session.get(User, auth_session.user_id)
                if auth_session.revoked_at is None and user is not None and user.is_active:
                    idle_expiry = normalize_database_datetime(auth_session.idle_expires_at)
                    absolute_expiry = normalize_database_datetime(auth_session.absolute_expires_at)
                    if idle_expiry > now and absolute_expiry > now:
                        auth_session.last_seen_at = now
                        auth_session.idle_expires_at = min(
                            now + SESSION_IDLE_TIMEOUT,
                            absolute_expiry,
                        )
                        valid = True

                if not valid and auth_session.revoked_at is None:
                    auth_session.revoked_at = now
    except SQLAlchemyError:
        clear_session_cookie(request, response, settings)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from None

    if not valid or auth_session is None or user is None:
        clear_session_cookie(request, response, settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_token,
        max_age=max(
            1,
            int((normalize_database_datetime(auth_session.idle_expires_at) - now).total_seconds()),
        ),
        httponly=True,
        secure=settings.auth_cookie_secure or request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return AuthenticatedSession(user=user, auth_session=auth_session)


def require_session_csrf(
    request: Request,
    authenticated: Annotated[
        AuthenticatedSession,
        Depends(get_authenticated_session),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedSession:
    validate_session_csrf(request, authenticated, settings)
    return authenticated


def validate_session_csrf(
    request: Request,
    authenticated: AuthenticatedSession,
    settings: Settings,
) -> None:
    require_allowed_origin(request, settings)
    csrf_token = request.headers.get("x-csrf-token")
    if not csrf_token or not hmac.compare_digest(
        hash_token(csrf_token),
        authenticated.auth_session.csrf_token_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request verification failed.",
        )


def require_authenticated_resource_access(
    request: Request,
    session: DatabaseSession,
    authenticated: Annotated[
        AuthenticatedSession,
        Depends(get_authenticated_session),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        validate_session_csrf(request, authenticated, settings)

    profile_id_value = request.path_params.get("profile_id")
    if profile_id_value is None:
        return
    try:
        profile_id = profile_id_value if isinstance(profile_id_value, UUID) else UUID(str(profile_id_value))
    except ValueError:
        profile_id = None

    if (
        profile_id is None
        or session.scalar(
            select(CandidateProfile.id).where(
                CandidateProfile.id == profile_id,
                CandidateProfile.user_id == authenticated.user.id,
            )
        )
        is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        )
