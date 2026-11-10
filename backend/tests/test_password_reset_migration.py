from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "f1a2c3d4e5b6_add_password_reset_tokens.py"
)
SPEC = spec_from_file_location("password_reset_migration", MIGRATION_PATH)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def test_password_reset_migration_adds_one_time_token_storage() -> None:
    engine = create_engine("sqlite+pysqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            connection.execute(text("CREATE TABLE users (id CHAR(32) PRIMARY KEY)"))
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                MIGRATION.upgrade()

            inspector = inspect(connection)
            assert "password_reset_tokens" in inspector.get_table_names()
            assert inspector.get_foreign_keys("password_reset_tokens")[0]["referred_table"] == "users"
            assert {index["name"] for index in inspector.get_indexes("password_reset_tokens")} == {
                "ix_password_reset_tokens_user",
                "ix_password_reset_tokens_expires",
            }
            assert MIGRATION.down_revision == "e7c4a9d2b6f3"
            with Operations.context(context):
                MIGRATION.downgrade()
            assert "password_reset_tokens" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()
