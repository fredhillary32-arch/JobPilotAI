from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
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
    auth_allowed_origin: str = Field(
        default="http://127.0.0.1:5173",
        validation_alias="AUTH_ALLOWED_ORIGIN",
    )
    auth_local_http: bool = Field(default=False, validation_alias="AUTH_LOCAL_HTTP")
    document_storage_path: Path = Field(
        default=PROJECT_ROOT / "var" / "documents",
        validation_alias="DOCUMENT_STORAGE_PATH",
    )

    @property
    def auth_cookie_secure(self) -> bool:
        return not self.auth_local_http

    @model_validator(mode="after")
    def validate_local_http_origin(self) -> "Settings":
        if self.auth_local_http and self.auth_allowed_origin != "http://127.0.0.1:5173":
            raise ValueError(
                "Local HTTP authentication requires the approved loopback browser origin."
            )
        return self

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def resolved_document_storage_path(self) -> Path:
        if self.document_storage_path.is_absolute():
            return self.document_storage_path
        return PROJECT_ROOT / self.document_storage_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
