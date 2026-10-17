from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from backend.app.config import get_settings


def migration_config(database_path: Path, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    return Config("alembic.ini")


def test_migrations_create_current_membership_schema(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "migration.db"
    config = migration_config(database_path, monkeypatch)
    command.upgrade(config, "head")

    columns = {
        column["name"]
        for column in inspect(create_engine(f"sqlite:///{database_path}")).get_columns(
            "memberships"
        )
    }
    assert {"notification_channels", "recipe_preferences", "voice_preferences"} <= columns
    get_settings.cache_clear()


def test_repair_migration_adds_preferences_to_incomplete_database(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "repair.db"
    config = migration_config(database_path, monkeypatch)
    command.upgrade(config, "0012")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE memberships DROP COLUMN notification_channels")
        connection.exec_driver_sql("ALTER TABLE memberships DROP COLUMN recipe_preferences")
    command.stamp(config, "0014")
    command.upgrade(config, "head")

    columns = {column["name"] for column in inspect(engine).get_columns("memberships")}
    assert {"notification_channels", "recipe_preferences", "voice_preferences"} <= columns
    get_settings.cache_clear()
