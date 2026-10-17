import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.pool import StaticPool

import app.db as db_module
import app.main as main_module
from app.db import DatabaseSchemaNotCurrentError, get_expected_schema_heads
from app.main import app

client = TestClient(app)


def _sqlite_engine_with_revisions(*revisions: str):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        for revision in revisions:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": revision},
            )
    return engine


def test_expected_schema_head_is_the_single_repository_head() -> None:
    assert get_expected_schema_heads() == frozenset({"e7c4a9d2b6f3"})


def test_database_check_accepts_current_schema_revision(monkeypatch) -> None:
    engine = _sqlite_engine_with_revisions("e7c4a9d2b6f3")
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)

    db_module.check_database_connection()


@pytest.mark.parametrize("revisions", [("7ce347caa873",), ()])
def test_database_check_rejects_outdated_or_unversioned_schema(
    monkeypatch,
    revisions: tuple[str, ...],
) -> None:
    engine = _sqlite_engine_with_revisions(*revisions)
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)

    with pytest.raises(DatabaseSchemaNotCurrentError):
        db_module.check_database_connection()


def test_database_check_reports_missing_migration_table_as_database_error(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)

    with pytest.raises(SQLAlchemyError):
        db_module.check_database_connection()


def test_readiness_check_returns_503_without_revisions_when_schema_is_outdated(
    monkeypatch,
) -> None:
    engine = _sqlite_engine_with_revisions("7ce347caa873")
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database schema is not current"}
    assert "7ce347caa873" not in response.text
    assert "d4f7a19c2b86" not in response.text


def test_readiness_check_succeeds_when_database_is_available(
    monkeypatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        main_module,
        "check_database_connection",
        lambda: calls.append(True),
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == [True]


def test_readiness_check_returns_503_when_database_is_unavailable(
    monkeypatch,
) -> None:
    def fail_connection_check() -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection failed"))

    monkeypatch.setattr(main_module, "check_database_connection", fail_connection_check)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "connection failed" not in response.text
    assert "SELECT" not in response.text
