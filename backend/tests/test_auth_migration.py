from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

MIGRATION_PATH = Path(__file__).parents[1] / "alembic" / "versions" / "d4f7a19c2b86_add_local_auth_identity_tables.py"
SPEC = spec_from_file_location("local_auth_migration", MIGRATION_PATH)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def test_additive_auth_migration_preserves_unassigned_legacy_profile() -> None:
    profile_id = uuid4()
    engine = create_engine("sqlite+pysqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            connection.execute(
                text(
                    "CREATE TABLE candidate_profiles ("
                    "id CHAR(32) PRIMARY KEY, "
                    "name VARCHAR(200) NOT NULL, "
                    "contact_email VARCHAR(254)"
                    ")"
                )
            )
            connection.execute(
                text("INSERT INTO candidate_profiles (id, name, contact_email) VALUES (:id, :name, :email)"),
                {
                    "id": profile_id.hex,
                    "name": "Synthetic legacy profile",
                    "email": "candidate@example.test",
                },
            )
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                MIGRATION.upgrade()

            preserved = connection.execute(
                text("SELECT id, name, contact_email, user_id FROM candidate_profiles WHERE id = :id"),
                {"id": profile_id.hex},
            ).one()
            assert preserved.name == "Synthetic legacy profile"
            assert preserved.contact_email == "candidate@example.test"
            assert preserved.user_id is None

            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            assert {
                "users",
                "auth_sessions",
                "pre_auth_challenges",
                "profile_ownership_adoptions",
            }.issubset(tables)
            assert any(fk["referred_table"] == "users" for fk in inspector.get_foreign_keys("candidate_profiles"))
            assert inspector.get_foreign_keys("auth_sessions")[0]["referred_table"] == "users"
            assert MIGRATION.down_revision == "7ce347caa873"
    finally:
        engine.dispose()
