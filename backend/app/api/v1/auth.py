import json
import secrets
from typing import Annotated, TypeVar
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.v1.dependencies import (
    SESSION_COOKIE_NAME,
    AuthenticatedSession,
    clear_session_cookie,
    get_authenticated_session,
    require_allowed_origin,
    require_session_csrf,
)
from app.db import DatabaseSession
from app.models.user import AuthSession, PreAuthChallenge, User
from app.schemas.auth import (
    AuthenticatedUserResponse,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    PreAuthChallengeResponse,
    SessionResponse,
)
from app.services.auth import (
    PRE_AUTH_CHALLENGE_LIFETIME,
    AccountNotFoundError,
    IncorrectCurrentPasswordError,
    UnsupportedAuthDatabaseError,
    complete_password_reset,
    consume_pre_auth_challenge,
    create_auth_session,
    create_password_reset_token,
    hash_token,
    normalize_database_datetime,
    normalize_login_email,
    utc_now,
    validate_password,
    verify_login_password,
)
from app.services.auth import (
    change_password as change_password_for_user,
)
from app.services.login_limiter import login_failure_limiter
from app.services.password_reset_email import send_password_reset_email
from app.services.password_reset_limiter import password_reset_limiter
from app.settings import Settings, get_settings, normalize_origin

router = APIRouter(prefix="/auth", tags=["auth"])
PRE_AUTH_COOKIE_NAME = "jobpilot_pre_auth"
CSRF_HEADER_NAME = "x-csrf-token"
MAX_LOGIN_BODY_BYTES = 8192
MAX_PASSWORD_CHANGE_BODY_BYTES = 8192
MAX_PASSWORD_RESET_BODY_BYTES = 8192
GENERIC_LOGIN_ERROR = "Invalid email or password."
AuthRequestT = TypeVar("AuthRequestT", bound=BaseModel)


def _set_cookie(
    request: Request,
    response: Response,
    name: str,
    value: str,
    *,
    max_age: int,
    settings: Settings,
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure or request.url.scheme == "https",
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def _clear_pre_auth_cookie(
    request: Request,
    response: Response,
    settings: Settings,
) -> None:
    response.delete_cookie(
        PRE_AUTH_COOKIE_NAME,
        path="/",
        secure=settings.auth_cookie_secure or request.url.scheme == "https",
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )


def _client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


async def _parse_login_request(request: Request) -> LoginRequest:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_LOGIN_BODY_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Login request is too large.",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid login request.",
            ) from None

    body = await request.body()
    if len(body) > MAX_LOGIN_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Login request is too large.",
        )
    try:
        payload = json.loads(body)
        return LoginRequest.model_validate(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid login request.",
        ) from None


async def _parse_password_change_request(request: Request) -> PasswordChangeRequest:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_PASSWORD_CHANGE_BODY_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Password change request is too large.",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid password change request.",
            ) from None

    body = await request.body()
    if len(body) > MAX_PASSWORD_CHANGE_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Password change request is too large.",
        )
    try:
        payload = json.loads(body)
        return PasswordChangeRequest.model_validate(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid password change request.",
        ) from None


async def _parse_password_reset_request(request: Request) -> PasswordResetRequest:
    return await _parse_auth_request(request, PasswordResetRequest, "password reset")


async def _parse_password_reset_confirm_request(request: Request) -> PasswordResetConfirmRequest:
    return await _parse_auth_request(request, PasswordResetConfirmRequest, "password reset")


async def _parse_auth_request(
    request: Request,
    model: type[AuthRequestT],
    label: str,
) -> AuthRequestT:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_PASSWORD_RESET_BODY_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"{label.capitalize()} request is too large.",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {label} request.",
            ) from None

    body = await request.body()
    if len(body) > MAX_PASSWORD_RESET_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{label.capitalize()} request is too large.",
        )
    try:
        return model.model_validate(json.loads(body))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {label} request.",
        ) from None


def _consume_pre_auth_challenge(
    request: Request,
    response: Response,
    session: Session,
    settings: Settings,
) -> None:
    require_allowed_origin(request, settings)
    _clear_pre_auth_cookie(request, response, settings)
    try:
        challenge_valid = consume_pre_auth_challenge(
            session,
            request.headers.get(CSRF_HEADER_NAME),
            request.cookies.get(PRE_AUTH_COOKIE_NAME),
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from None
    if not challenge_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request verification failed.",
        )


def _record_password_reset_attempt(client_ip: str) -> None:
    with password_reset_limiter.lock:
        if password_reset_limiter.is_limited(client_ip):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many password recovery requests. Try again later.",
            )
        password_reset_limiter.record_request(client_ip)


def _session_response(user: User, csrf_token: str) -> SessionResponse:
    return SessionResponse(
        user=AuthenticatedUserResponse(id=user.id, email=user.email),
        csrf_token=csrf_token,
    )


def _authenticate_and_create_session(
    session: Session,
    login_request: LoginRequest,
    client_ip: str,
) -> tuple[User, str, str, int]:
    try:
        normalized_email = normalize_login_email(login_request.email)
    except ValueError:
        normalized_email = None
    # Malformed emails share one bucket per client so they cannot bypass the limit.
    account_key = normalized_email or ""

    with login_failure_limiter.lock:
        if login_failure_limiter.is_limited(client_ip, account_key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Try again later.",
            )

        try:
            with session.begin():
                dialect_name = session.get_bind().dialect.name
                if dialect_name == "sqlite":
                    session.execute(text("BEGIN IMMEDIATE"))
                elif dialect_name != "postgresql":
                    raise UnsupportedAuthDatabaseError("Authentication does not support this database engine.")

                user: User | None = None
                if normalized_email is not None:
                    user = session.scalar(select(User).where(User.email == normalized_email).with_for_update())
                if not verify_login_password(login_request.password, user):
                    login_failure_limiter.record_failure(client_ip, account_key)
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=GENERIC_LOGIN_ERROR,
                    )

                now = utc_now()
                auth_session, raw_session_token, csrf_token = create_auth_session(
                    session,
                    user,
                    now,
                )
                session.flush()
                expiry = min(
                    normalize_database_datetime(auth_session.idle_expires_at),
                    normalize_database_datetime(auth_session.absolute_expires_at),
                )
                max_age = max(1, int((expiry - now).total_seconds()))
        except HTTPException:
            raise
        except SQLAlchemyError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service unavailable.",
            ) from None
        except UnsupportedAuthDatabaseError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service unavailable.",
            ) from None
        # Reached only after the session was committed successfully.
        login_failure_limiter.clear_account(client_ip, account_key)

    return user, raw_session_token, csrf_token, max_age


@router.get("/pre-auth-csrf", response_model=PreAuthChallengeResponse)
def create_pre_auth_csrf(
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PreAuthChallengeResponse:
    origin = request.headers.get("origin")
    normalized_origin = normalize_origin(origin) if origin else None
    normalized_allowed_origin = normalize_origin(settings.auth_allowed_origin)
    if origin is not None and normalized_origin != normalized_allowed_origin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed.",
        )
    if (
        request.headers.get("sec-fetch-site", "").lower() == "cross-site"
        and (origin is None or normalized_origin != normalized_allowed_origin)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed.",
        )

    now = utc_now()
    csrf_token = secrets.token_urlsafe(32)
    cookie_binding = secrets.token_urlsafe(32)
    try:
        with session.begin():
            session.execute(delete(PreAuthChallenge).where(PreAuthChallenge.expires_at <= now))
            session.add(
                PreAuthChallenge(
                    token_hash=hash_token(csrf_token),
                    cookie_binding_hash=hash_token(cookie_binding),
                    created_at=now,
                    expires_at=now + PRE_AUTH_CHALLENGE_LIFETIME,
                )
            )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from None

    _set_cookie(
        request,
        response,
        PRE_AUTH_COOKIE_NAME,
        cookie_binding,
        max_age=int(PRE_AUTH_CHALLENGE_LIFETIME.total_seconds()),
        settings=settings,
    )
    return PreAuthChallengeResponse(csrf_token=csrf_token)


@router.post("/login", response_model=SessionResponse)
async def login(
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    require_allowed_origin(request, settings)
    login_request = await _parse_login_request(request)
    _consume_pre_auth_challenge(request, response, session, settings)

    user, raw_session_token, csrf_token, max_age = await run_in_threadpool(
        _authenticate_and_create_session,
        session,
        login_request,
        _client_ip(request),
    )

    _set_cookie(
        request,
        response,
        SESSION_COOKIE_NAME,
        raw_session_token,
        max_age=max_age,
        settings=settings,
    )
    return _session_response(user, csrf_token)


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PasswordResetRequestResponse,
)
async def request_password_reset(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PasswordResetRequestResponse:
    _consume_pre_auth_challenge(request, response, session, settings)
    payload = await _parse_password_reset_request(request)

    _record_password_reset_attempt(_client_ip(request))

    if not settings.password_reset_email_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password recovery is not configured.",
        )

    try:
        reset = await run_in_threadpool(create_password_reset_token, session, payload.email)
    except (UnsupportedAuthDatabaseError, SQLAlchemyError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from None

    if reset is not None:
        account_email, raw_token = reset
        reset_url = f"{settings.auth_allowed_origin.rstrip('/')}/#reset={quote(raw_token, safe='')}"
        background_tasks.add_task(send_password_reset_email, settings, account_email, reset_url)

    return PasswordResetRequestResponse(
        message="If an account exists for this address, a password reset email will be sent."
    )


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    _consume_pre_auth_challenge(request, response, session, settings)
    _record_password_reset_attempt(_client_ip(request))
    payload = await _parse_password_reset_confirm_request(request)
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="New passwords do not match.",
        )
    try:
        reset_succeeded = await run_in_threadpool(
            complete_password_reset,
            session,
            payload.token,
            payload.new_password,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None
    except (UnsupportedAuthDatabaseError, SQLAlchemyError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from None

    if not reset_succeeded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or expired.",
        )

    clear_session_cookie(request, response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/session", response_model=SessionResponse)
def restore_session(
    authenticated: Annotated[
        AuthenticatedSession,
        Depends(get_authenticated_session),
    ],
    session: DatabaseSession,
) -> SessionResponse:
    csrf_token = secrets.token_urlsafe(32)
    authenticated.auth_session.csrf_token_hash = hash_token(csrf_token)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from None
    return _session_response(authenticated.user, csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    authenticated: Annotated[
        AuthenticatedSession,
        Depends(require_session_csrf),
    ],
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    try:
        with session.begin():
            session.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == authenticated.auth_session.id,
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=utc_now())
            )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable.",
        ) from None

    _clear_pre_auth_cookie(request, response, settings)
    clear_session_cookie(request, response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: Request,
    response: Response,
    authenticated: Annotated[
        AuthenticatedSession,
        Depends(require_session_csrf),
    ],
    session: DatabaseSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    payload = await _parse_password_change_request(request)
    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="New passwords do not match.",
        )
    try:
        validate_password(payload.new_password)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from None

    client_ip = _client_ip(request)
    account_key = authenticated.user.email
    with login_failure_limiter.lock:
        if login_failure_limiter.is_limited(client_ip, account_key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many password change attempts. Try again later.",
            )
        try:
            await run_in_threadpool(
                change_password_for_user,
                session,
                authenticated.user.id,
                payload.current_password,
                payload.new_password,
            )
        except IncorrectCurrentPasswordError:
            login_failure_limiter.record_failure(client_ip, account_key)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect.",
            ) from None
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from None
        except (AccountNotFoundError, UnsupportedAuthDatabaseError, SQLAlchemyError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service unavailable.",
            ) from None
        login_failure_limiter.clear_account(client_ip, account_key)

    clear_session_cookie(request, response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
