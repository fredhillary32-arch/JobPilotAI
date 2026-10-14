from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import app.main as main_module
from app.main import app

client = TestClient(app)


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
