from collections.abc import Generator

from app.db import get_db_session


class FakeSession:
    closed = False

    def close(self) -> None:
        self.closed = True


def test_database_session_dependency_closes_session(monkeypatch) -> None:
    session = FakeSession()
    monkeypatch.setattr("app.db.get_session_factory", lambda: lambda: session)

    dependency: Generator = get_db_session()
    assert next(dependency) is session

    dependency.close()

    assert session.closed
