from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db_session
from app.main import app
from app.models import CandidateProfile


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
def api_client(
    database: tuple[Engine, sessionmaker[Session]],
) -> Generator[TestClient, None, None]:
    _, factory = database

    def override_db_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def candidate_profile() -> CandidateProfile:
    return CandidateProfile(name="Test Candidate")
