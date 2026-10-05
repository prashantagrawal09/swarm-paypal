"""Alembic migration environment. Uses the app's DATABASE_URL and model metadata."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db import models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ALEMBIC_DATABASE_URL lets tests migrate the test database without touching dev data.
database_url = os.environ.get("ALEMBIC_DATABASE_URL") or get_settings().database_url
config.set_main_option("sqlalchemy.url", database_url)
target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
