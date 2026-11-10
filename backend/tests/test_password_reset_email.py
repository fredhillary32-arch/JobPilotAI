from app.services import password_reset_email
from app.settings import Settings


def test_smtp_authentication_occurs_only_after_starttls(monkeypatch) -> None:
    events: list[str] = []

    class SmtpDouble:
        def __enter__(self):
            events.append("connect")
            return self

        def __exit__(self, *_args) -> None:
            return None

        def starttls(self, **_kwargs) -> None:
            events.append("starttls")

        def login(self, _username: str, _password: str) -> None:
            events.append("login")

        def send_message(self, _message) -> dict:
            events.append("send")
            return {}

    monkeypatch.setattr(password_reset_email.smtplib, "SMTP", lambda *_args, **_kwargs: SmtpDouble())
    settings = Settings(
        postgres_user="test-user",
        postgres_password="test-password",
        postgres_db="test-db",
        password_reset_smtp_host="smtp.example.com",
        password_reset_smtp_username="mailer",
        password_reset_smtp_password="smtp-secret",
        password_reset_sender_email="noreply@example.com",
    )

    password_reset_email.send_password_reset_email(
        settings,
        "owner@example.com",
        "https://app.example.com/#reset=one-time-token",
    )

    assert events == ["connect", "starttls", "login", "send"]
