"""chapter rework

Revision ID: 08e8a0ac2d8a
Revises: 4a7d64d0e75c
Create Date: 2026-09-24 20:35:38.566572

Chapter now belongs directly to Book (not a single Video) -- ai_llm's
default BOOK_ORDER=topic merges chapters across multiple source videos, so
a single-video FK can't represent that. v1/v2 never populated this table
(sprints/v1/PRD.md: "intentionally unpopulated in v1"), so this drops and
recreates it rather than attempting a piecemeal column migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08e8a0ac2d8a'
down_revision: Union[str, None] = '4a7d64d0e75c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('chapters')
    op.create_table(
        'chapters',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('book_id', sa.String(length=36), nullable=False),
        sa.Column('ai_llm_chapter_id', sa.String(length=128), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('skip', sa.Boolean(), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('source_video_ids', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['book_id'], ['books.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('book_id', 'ai_llm_chapter_id'),
    )


def downgrade() -> None:
    op.drop_table('chapters')
    op.create_table(
        'chapters',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('video_id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id']),
        sa.PrimaryKeyConstraint('id'),
    )
