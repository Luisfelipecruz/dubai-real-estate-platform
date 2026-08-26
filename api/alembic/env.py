"""Alembic environment.

Migrations run through psycopg2 (sync) even though the application uses asyncpg.
That is the normal arrangement: migrations are a short-lived batch process with no
concurrency to gain from async, and the sync driver keeps env.py simple.

Only the ORM-managed tables are under Alembic control. The legacy analytics schema
(raw_transactions, raw_rent_contracts, raw_valuations, area_trends, communities...)
is created by infra/postgres/init.sql on first boot, so `include_object` filters
autogenerate down to the tables registered on `Base.metadata`. Without that filter,
an autogenerate run would cheerfully emit DROP TABLE for everything it did not
recognise.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SYNC_DATABASE_URL  # noqa: E402
from db_models import Base  # noqa: E402

config = context.config
config.set_main_option("sqlalchemy.url", SYNC_DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

MANAGED_TABLES = set(Base.metadata.tables.keys())


def include_object(object_, name, type_, reflected, compare_to):
    """Keep autogenerate away from the init.sql-owned tables."""
    if type_ == "table":
        return name in MANAGED_TABLES
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=SYNC_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
