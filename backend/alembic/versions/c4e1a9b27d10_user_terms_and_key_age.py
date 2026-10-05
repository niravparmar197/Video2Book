"""user terms acceptance and api key age

Revision ID: c4e1a9b27d10
Revises: 9b3f2c7a1d4e
Create Date: 2026-10-05 10:00:00.000000

Sign-up now requires accepting the terms of use (stored when), and API
keys can expire and be rotated (needs the time the key was issued).
Existing keys count as issued at migration time.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e1a9b27d10'
down_revision: Union[str, None] = '9b3f2c7a1d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'api_key_created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column('users', sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'terms_accepted_at')
    op.drop_column('users', 'api_key_created_at')
