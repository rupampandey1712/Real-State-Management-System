"""Property age, admin moderation log (FR-1, FR-7.1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("property_age_years", sa.SmallInteger(), nullable=True))
    op.create_table(
        "moderation_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("listing_id", sa.UUID(), nullable=False),
        sa.Column("admin_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_moderation_actions_listing_id", "moderation_actions", ["listing_id"])


def downgrade() -> None:
    op.drop_index("ix_moderation_actions_listing_id", table_name="moderation_actions")
    op.drop_table("moderation_actions")
    op.drop_column("listings", "property_age_years")
