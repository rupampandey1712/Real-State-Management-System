"""Initial schema for the ai service.

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
    op.create_table('document_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('listing_id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('page_from', sa.Integer(), nullable=False),
    sa.Column('page_to', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('token_estimate', sa.Integer(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=768), nullable=False),
    sa.Column('embedding_model', sa.String(length=60), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_chunks_embedding', 'document_chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index(op.f('ix_document_chunks_document_id'), 'document_chunks', ['document_id'], unique=False)
    op.create_index(op.f('ix_document_chunks_listing_id'), 'document_chunks', ['listing_id'], unique=False)
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


def downgrade() -> None:
    op.drop_table('outbox')
    op.drop_table('document_chunks')
