from functools import lru_cache
from pathlib import Path

from pydantic import EmailStr, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    postgres_user: str = Field(validation_alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(validation_alias="POSTGRES_DB")
    postgres_host: str = Field(default="127.0.0.1", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5433, validation_alias="POSTGRES_PORT")
    postgres_sslmode: str | None = Field(default=None, validation_alias="POSTGRES_SSLMODE")
    auth_allowed_origin: str = Field(
        default="http://127.0.0.1:5173",
        validation_alias="AUTH_ALLOWED_ORIGIN",
    )
    auth_local_http: bool = Field(default=False, validation_alias="AUTH_LOCAL_HTTP")
    auth_cookie_samesite: str = Field(default="strict", validation_alias="AUTH_COOKIE_SAMESITE")
    password_reset_smtp_host: str | None = Field(default=None, validation_alias="PASSWORD_RESET_SMTP_HOST")
    password_reset_smtp_port: int = Field(
        default=587,
        ge=1,
        le=65535,
        validation_alias="PASSWORD_RESET_SMTP_PORT",
    )
    password_reset_smtp_username: str | None = Field(
        default=None,
        validation_alias="PASSWORD_RESET_SMTP_USERNAME",
    )
    password_reset_smtp_password: SecretStr | None = Field(
        default=None,
        validation_alias="PASSWORD_RESET_SMTP_PASSWORD",
    )
    password_reset_sender_email: EmailStr | None = Field(
        default=None,
        validation_alias="PASSWORD_RESET_SENDER_EMAIL",
    )
    password_reset_smtp_starttls: bool = Field(
        default=True,
        validation_alias="PASSWORD_RESET_SMTP_STARTTLS",
    )
    password_reset_smtp_use_ssl: bool = Field(
        default=False,
        validation_alias="PASSWORD_RESET_SMTP_USE_SSL",
    )
    document_storage_path: Path = Field(
        default=PROJECT_ROOT / "var" / "documents",
        validation_alias="DOCUMENT_STORAGE_PATH",
    )

    @property
    def auth_cookie_secure(self) -> bool:
        return self.auth_cookie_samesite == "none" or not self.auth_local_http

    @model_validator(mode="after")
    def validate_cookie_samesite(self) -> "Settings":
        if self.auth_cookie_samesite not in {"strict", "lax", "none"}:
            raise ValueError("AUTH_COOKIE_SAMESITE must be strict, lax, or none.")
        return self

    @model_validator(mode="after")
    def validate_local_http_origin(self) -> "Settings":
        if self.auth_local_http and self.auth_allowed_origin != "http://127.0.0.1:5173":
            raise ValueError("Local HTTP authentication requires the approved loopback browser origin.")
        return self

    @model_validator(mode="after")
    def validate_password_reset_email_settings(self) -> "Settings":
        required = (
            self.password_reset_smtp_host,
            self.password_reset_smtp_username,
            self.password_reset_smtp_password,
            self.password_reset_sender_email,
        )
        if any(value is not None for value in required) and not all(value is not None for value in required):
            raise ValueError("Configure all password-reset SMTP host, username, password, and sender settings.")
        if self.password_reset_smtp_use_ssl and self.password_reset_smtp_starttls:
            raise ValueError("Choose either password-reset SMTP SSL or STARTTLS, not both.")
        if self.password_reset_email_configured and not (
            self.password_reset_smtp_use_ssl or self.password_reset_smtp_starttls
        ):
            raise ValueError("Password-reset SMTP must use SSL or STARTTLS.")
        return self

    @property
    def password_reset_email_configured(self) -> bool:
        return all(
            value is not None
            for value in (
                self.password_reset_smtp_host,
                self.password_reset_smtp_username,
                self.password_reset_smtp_password,
                self.password_reset_sender_email,
            )
        )

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
            query={"sslmode": self.postgres_sslmode} if self.postgres_sslmode else {},
        )

    @property
    def resolved_document_storage_path(self) -> Path:
        if self.document_storage_path.is_absolute():
            return self.document_storage_path
        return PROJECT_ROOT / self.document_storage_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
