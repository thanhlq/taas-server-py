"""drop outbox_events.deleted_at

The ``outbox_events`` table was created with a ``deleted_at`` column
(``NOT NULL``, no default) inherited from the ``SoftDeleteColumns`` mixin.
That made ORM inserts impossible (every insert violated the NOT NULL
constraint) and soft-deletion is not part of the outbox lifecycle anyway — the
outbox uses explicit archiving and hard-deletion instead. This migration drops
the column to match the corrected ``OutboxEventTable`` model.

Revision ID: c1a2b3c4d5e6
Revises: b28a9ffadaab
Create Date: 2026-07-11 12:00:00.000000

"""
import sqlalchemy as sa
from advanced_alchemy.types import DateTimeUTC
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c1a2b3c4d5e6'
down_revision = 'b28a9ffadaab'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('outbox_events', schema=None) as batch_op:
        batch_op.drop_column('deleted_at')


def downgrade() -> None:
    # Re-add as NULLABLE so the downgrade succeeds even when rows exist.
    with op.batch_alter_table('outbox_events', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('deleted_at', DateTimeUTC(timezone=True), nullable=True)
        )
