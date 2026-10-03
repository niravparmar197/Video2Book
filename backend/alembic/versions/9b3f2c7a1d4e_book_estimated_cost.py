"""book estimated cost

Revision ID: 9b3f2c7a1d4e
Revises: 27e9a46bfeda
Create Date: 2026-09-25 09:00:00.000000

sprints/v8: persist the playlist cost estimate computed at book-creation
time so a global daily spend total can be summed without re-estimating
every book on every request.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b3f2c7a1d4e'
down_revision: Union[str, None] = '27e9a46bfeda'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'books',
        sa.Column('estimated_cost_usd', sa.Float(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('books', 'estimated_cost_usd')
