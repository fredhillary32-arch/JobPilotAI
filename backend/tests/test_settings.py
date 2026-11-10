import pytest
from pydantic import SecretStr, ValidationError

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


def test_cross_site_cookie_policy_requires_secure_cookies() -> None:
    settings = Settings(
        postgres_user="jobpilot",
        postgres_password=SecretStr("test-password"),
        postgres_db="jobpilot",
        auth_cookie_samesite="none",
    )

    assert settings.auth_cookie_samesite == "none"
    assert settings.auth_cookie_secure is True


def test_database_url_supports_provider_required_tls() -> None:
    settings = Settings(
        postgres_user="jobpilot",
        postgres_password=SecretStr("test-password"),
        postgres_db="jobpilot",
        postgres_sslmode="require",
    )

    assert settings.database_url.query["sslmode"] == "require"


def test_password_reset_email_configuration_is_optional_but_complete_when_enabled() -> None:
    settings = Settings(
        postgres_user="jobpilot",
        postgres_password="test-password",
        postgres_db="jobpilot",
        password_reset_smtp_host="smtp.example.com",
        password_reset_smtp_username="mailer",
        password_reset_smtp_password="smtp-secret",
        password_reset_sender_email="noreply@example.com",
    )

    assert settings.password_reset_email_configured
    assert "smtp-secret" not in repr(settings)

    with pytest.raises(ValidationError):
        Settings(
            postgres_user="jobpilot",
            postgres_password="test-password",
            postgres_db="jobpilot",
            password_reset_smtp_host="smtp.example.com",
        )

    with pytest.raises(ValidationError):
        Settings(
            postgres_user="jobpilot",
            postgres_password="test-password",
            postgres_db="jobpilot",
            password_reset_smtp_host="smtp.example.com",
            password_reset_smtp_username="mailer",
            password_reset_smtp_password="smtp-secret",
            password_reset_sender_email="noreply@example.com",
            password_reset_smtp_starttls=False,
            password_reset_smtp_use_ssl=False,
        )
