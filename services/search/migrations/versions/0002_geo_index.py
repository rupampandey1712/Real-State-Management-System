"""Index for map-area (bbox) searches (FR-2.3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_search_geo", "search_listings", ["lat", "lng"])


def downgrade() -> None:
    op.drop_index("ix_search_geo", table_name="search_listings")
