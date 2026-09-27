"""Shared Alembic runner. Each Postgres-backed service's migrations/env.py calls run(url, metadata)."""

import asyncio

from alembic import context
from sqlalchemy import MetaData
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine


def _run_sync(connection: Connection, metadata: MetaData) -> None:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online(url: str, metadata: MetaData) -> None:
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync, metadata)
    await engine.dispose()


def run(url: str, metadata: MetaData) -> None:
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
        with context.begin_transaction():
            context.run_migrations()
    else:
        asyncio.run(_run_online(url, metadata))
