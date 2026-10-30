"""day_plans.accepted_at

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('day_plans', schema=None) as batch_op:
        batch_op.add_column(sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('day_plans', schema=None) as batch_op:
        batch_op.drop_column('accepted_at')
