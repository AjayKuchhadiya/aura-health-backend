"""add_medications_table

Revision ID: 47e29d5a74a8
Revises: c3f1a29e8b47
Create Date: 2026-06-07 15:58:43.521959

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '47e29d5a74a8'
down_revision: Union[str, None] = 'c3f1a29e8b47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('medications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('medication_name', sa.String(), nullable=False),
    sa.Column('dosage', sa.String(), nullable=False),
    sa.Column('frequency', sa.String(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('notes', sa.String(), nullable=True),
    sa.Column('google_calendar_event_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_medications_id'), 'medications', ['id'], unique=False)
    op.create_index(op.f('ix_medications_user_id'), 'medications', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_medications_user_id'), table_name='medications')
    op.drop_index(op.f('ix_medications_id'), table_name='medications')
    op.drop_table('medications')