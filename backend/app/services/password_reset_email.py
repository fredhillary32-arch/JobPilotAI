import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.settings import Settings

logger = logging.getLogger(__name__)


def send_password_reset_email(settings: Settings, recipient: str, reset_url: str) -> None:
    host = settings.password_reset_smtp_host
    username = settings.password_reset_smtp_username
    password = settings.password_reset_smtp_password
    sender = settings.password_reset_sender_email
    if not settings.password_reset_email_configured or host is None or username is None or password is None or sender is None:
        raise RuntimeError("Password-reset email is not configured.")
    if settings.password_reset_smtp_use_ssl == settings.password_reset_smtp_starttls:
        raise RuntimeError("Password-reset SMTP must use exactly one secure transport.")

    message = EmailMessage()
    message["Subject"] = "Reset your JobPilot AI password"
    message["From"] = str(sender)
    message["To"] = recipient
    message.set_content(
        "A password reset was requested for your JobPilot AI account.\n\n"
        f"Use this one-time link within 30 minutes:\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )

    try:
        if settings.password_reset_smtp_use_ssl:
            with smtplib.SMTP_SSL(
                host,
                settings.password_reset_smtp_port,
                timeout=20,
                context=ssl.create_default_context(),
            ) as server:
                _send_message(server, username, password.get_secret_value(), message)
        else:
            with smtplib.SMTP(host, settings.password_reset_smtp_port, timeout=20) as server:
                if settings.password_reset_smtp_starttls:
                    server.starttls(context=ssl.create_default_context())
                _send_message(server, username, password.get_secret_value(), message)
    except (OSError, smtplib.SMTPException) as error:
        logger.error("Password-reset email delivery failed (%s).", type(error).__name__)


def _send_message(server: smtplib.SMTP, username: str, password: str, message: EmailMessage) -> None:
    server.login(username, password)
    refused = server.send_message(message)
    if refused:
        logger.error("Password-reset email was rejected by the SMTP server.")
