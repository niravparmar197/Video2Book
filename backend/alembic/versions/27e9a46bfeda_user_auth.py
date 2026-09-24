"""user auth

Revision ID: 27e9a46bfeda
Revises: 08e8a0ac2d8a
Create Date: 2026-09-24 20:45:44.570971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '27e9a46bfeda'
down_revision: Union[str, None] = '08e8a0ac2d8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('books', sa.Column('user_id', sa.String(length=36), nullable=False))
    op.create_foreign_key('books_user_id_fkey', 'books', 'users', ['user_id'], ['id'])
    op.add_column('users', sa.Column('api_key_hash', sa.String(length=64), nullable=False))
    op.create_unique_constraint('users_api_key_hash_key', 'users', ['api_key_hash'])


def downgrade() -> None:
    op.drop_constraint('users_api_key_hash_key', 'users', type_='unique')
    op.drop_column('users', 'api_key_hash')
    op.drop_constraint('books_user_id_fkey', 'books', type_='foreignkey')
    op.drop_column('books', 'user_id')
