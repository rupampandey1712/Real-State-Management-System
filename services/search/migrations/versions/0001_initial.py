"""Initial schema for the search service.

Revision ID: 0001
Revises:
Create Date: 2026-09-27
"""

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('search_listings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('listing_type', sa.String(length=4), nullable=False),
    sa.Column('property_type', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('price_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('bedrooms', sa.SmallInteger(), nullable=False),
    sa.Column('bathrooms', sa.SmallInteger(), nullable=True),
    sa.Column('carpet_area_sqft', sa.Integer(), nullable=True),
    sa.Column('furnishing', sa.String(length=16), nullable=True),
    sa.Column('pet_policy', sa.String(length=12), nullable=False),
    sa.Column('amenities', sa.ARRAY(sa.String()), nullable=False),
    sa.Column('locality', sa.String(length=80), nullable=False),
    sa.Column('city', sa.String(length=40), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('thumbnail_key', sa.String(length=300), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=True),
    sa.Column('search_text', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english', title || ' ' || description || ' ' || locality || ' ' || city)", persisted=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_search_amenities', 'search_listings', ['amenities'], unique=False, postgresql_using='gin')
    op.create_index('ix_search_embedding', 'search_listings', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_search_filters', 'search_listings', ['city', 'listing_type', 'bedrooms', 'price_minor'], unique=False)
    op.create_index('ix_search_fts', 'search_listings', ['search_text'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    op.drop_table('search_listings')
