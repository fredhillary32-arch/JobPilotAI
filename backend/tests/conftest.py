from collections.abc import Generator
from datetime import timedelta
import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db_session
from app.main import app
from app.models import CandidateProfile
from app.models.user import AuthSession, User
from app.services.auth import hash_token, utc_now
from app.services.documents import LocalDocumentStorage, get_document_storage
from app.settings import Settings, get_settings


@pytest.fixture
def database() -> Generator[tuple[Engine, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield engine, factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def unauthenticated_client(
    database: tuple[Engine, sessionmaker[Session]],
    tmp_path,
) -> Generator[TestClient, None, None]:
    _, factory = database

    def override_db_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_document_storage] = lambda: LocalDocumentStorage(
        tmp_path / "private-documents"
    )
    test_settings = Settings(
        postgres_user="test-user",
        postgres_password="test-password",
        postgres_db="test-db",
        auth_local_http=True,
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_document_storage, None)
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def api_client(
    unauthenticated_client: TestClient,
    database: tuple[Engine, sessionmaker[Session]],
) -> TestClient:
    _, factory = database
    now = utc_now()
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    with factory.begin() as session:
        user = User(
            email="test-owner@example.com",
            password_hash="$argon2id$test-fixture",
        )
        session.add(user)
        session.flush()
        session.add(
            AuthSession(
                user_id=user.id,
                token_hash=hash_token(session_token),
                csrf_token_hash=hash_token(csrf_token),
                created_at=now,
                last_seen_at=now,
                idle_expires_at=now + timedelta(hours=12),
                absolute_expires_at=now + timedelta(days=7),
            )
        )
    unauthenticated_client.cookies.set(
        "jobpilot_session",
        session_token,
        domain="testserver.local",
        path="/",
    )
    unauthenticated_client.headers.update(
        {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": csrf_token,
        }
    )
    return unauthenticated_client


@pytest.fixture
def candidate_profile() -> CandidateProfile:
    return CandidateProfile(name="Test Candidate")
