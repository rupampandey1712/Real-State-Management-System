"""Initial schema for the listing service.

Revision ID: 0001
Revises:
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('listings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('agent_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('listing_type', sa.String(length=4), nullable=False),
    sa.Column('property_type', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('description_ai', sa.Boolean(), nullable=False),
    sa.Column('price_minor', sa.BigInteger(), nullable=False),
    sa.Column('deposit_minor', sa.BigInteger(), nullable=True),
    sa.Column('maintenance_minor', sa.BigInteger(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('bedrooms', sa.SmallInteger(), nullable=False),
    sa.Column('bathrooms', sa.SmallInteger(), nullable=True),
    sa.Column('balconies', sa.SmallInteger(), nullable=True),
    sa.Column('carpet_area_sqft', sa.Integer(), nullable=True),
    sa.Column('builtup_area_sqft', sa.Integer(), nullable=True),
    sa.Column('floor', sa.SmallInteger(), nullable=True),
    sa.Column('total_floors', sa.SmallInteger(), nullable=True),
    sa.Column('facing', sa.String(length=12), nullable=True),
    sa.Column('furnishing', sa.String(length=16), nullable=True),
    sa.Column('parking_covered', sa.SmallInteger(), nullable=False),
    sa.Column('parking_open', sa.SmallInteger(), nullable=False),
    sa.Column('pet_policy', sa.String(length=12), nullable=False),
    sa.Column('possession', sa.String(length=20), nullable=True),
    sa.Column('amenities', sa.ARRAY(sa.String()), nullable=False),
    sa.Column('address_line', sa.String(length=200), nullable=False),
    sa.Column('locality', sa.String(length=80), nullable=False),
    sa.Column('city', sa.String(length=40), nullable=False),
    sa.Column('pincode', sa.String(length=6), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('rera_id', sa.String(length=40), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_listings_agent_id'), 'listings', ['agent_id'], unique=False)
    op.create_index(op.f('ix_listings_city'), 'listings', ['city'], unique=False)
    op.create_index(op.f('ix_listings_locality'), 'listings', ['locality'], unique=False)
    op.create_index(op.f('ix_listings_status'), 'listings', ['status'], unique=False)
    op.create_table('outbox',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('topic', sa.String(length=100), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_outbox_created_at'), 'outbox', ['created_at'], unique=False)
    op.create_index(op.f('ix_outbox_published_at'), 'outbox', ['published_at'], unique=False)
    op.create_table('listing_documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('listing_id', sa.UUID(), nullable=False),
    sa.Column('storage_key', sa.String(length=300), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_listing_documents_listing_id'), 'listing_documents', ['listing_id'], unique=False)
    op.create_table('listing_images',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('listing_id', sa.UUID(), nullable=False),
    sa.Column('storage_key', sa.String(length=300), nullable=False),
    sa.Column('thumb_key', sa.String(length=300), nullable=False),
    sa.Column('caption', sa.String(length=200), nullable=True),
    sa.Column('position', sa.SmallInteger(), nullable=False),
    sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_listing_images_listing_id'), 'listing_images', ['listing_id'], unique=False)


def downgrade() -> None:
    op.drop_table('listing_images')
    op.drop_table('listing_documents')
    op.drop_table('outbox')
    op.drop_table('listings')
