from pydantic import SecretStr

from app.settings import Settings


def test_database_url_uses_safe_url_construction_and_configured_host_port() -> None:
    password = "p@ss:/%word"
    settings = Settings(
        postgres_user="jobpilot",
        postgres_password=SecretStr(password),
        postgres_db="jobpilot",
        postgres_host="127.0.0.1",
        postgres_port=5433,
    )

    url = settings.database_url

    assert url.drivername == "postgresql+psycopg"
    assert url.username == "jobpilot"
    assert url.password == password
    assert url.host == "127.0.0.1"
    assert url.port == 5433
    assert url.database == "jobpilot"
    assert "p%40ss%3A%2F%25word" in url.render_as_string(hide_password=False)
    assert password not in repr(settings)
