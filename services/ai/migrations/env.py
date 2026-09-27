"""Alembic environment: this service's models + the shared runner (estate_common.migrations)."""

from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401 — registers this service's tables on Base.metadata
from app.config import settings
from estate_common.db import Base
from estate_common.migrations import run

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

run(settings.database_url, Base.metadata)
