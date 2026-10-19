"""Programmatic Alembic upgrade, used at startup and by scripts."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from app.core.config import BACKEND_DIR, get_settings


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "app" / "db" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    cfg.attributes["configure_logger"] = False
    return cfg


def upgrade_to_head(database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), "head")


if __name__ == "__main__":
    upgrade_to_head()
