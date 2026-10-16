from collections.abc import Generator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import Depends
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import get_settings

ALEMBIC_SCRIPT_LOCATION = Path(__file__).resolve().parents[1] / "alembic"


class Base(DeclarativeBase):
    pass


class DatabaseSchemaNotCurrentError(RuntimeError):
    pass


@lru_cache
def get_expected_schema_heads() -> frozenset[str]:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database_connection() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
        revisions = frozenset(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
    if revisions != get_expected_schema_heads():
        raise DatabaseSchemaNotCurrentError("Database schema revision is not current.")


DatabaseSession = Annotated[Session, Depends(get_db_session)]
