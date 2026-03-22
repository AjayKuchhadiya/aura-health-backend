"""Add location fields to doctors and users

Revision ID: c3f1a29e8b47
Revises: b9364f6b3cd8
Create Date: 2026-03-22 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3f1a29e8b47"
down_revision: Union[str, None] = "72c8eaadb668"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- doctors: add city, state, country for location context matching ---
    op.add_column("doctors", sa.Column("city", sa.String(), nullable=True))
    op.add_column("doctors", sa.Column("state", sa.String(), nullable=True))
    op.add_column("doctors", sa.Column("country", sa.String(), nullable=True))

    # --- users: add last known location + timezone fields ---
    op.add_column("users", sa.Column("last_known_latitude", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("last_known_longitude", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("last_known_city", sa.String(), nullable=True))
    op.add_column("users", sa.Column("last_known_country", sa.String(), nullable=True))
    op.add_column("users", sa.Column("timezone", sa.String(), nullable=True))
    op.add_column(
        "users", sa.Column("location_updated_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    # --- remove users location fields ---
    op.drop_column("users", "location_updated_at")
    op.drop_column("users", "timezone")
    op.drop_column("users", "last_known_country")
    op.drop_column("users", "last_known_city")
    op.drop_column("users", "last_known_longitude")
    op.drop_column("users", "last_known_latitude")

    # --- remove doctors location fields ---
    op.drop_column("doctors", "country")
    op.drop_column("doctors", "state")
    op.drop_column("doctors", "city")
