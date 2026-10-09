"""ppm: item descriptions as site documents (``taas_tasks.description_doc``)

The task description is written with the shared document editor (Visual · Markdown modes chosen per project / organization,
ADR-35); the document is the source, ``description`` its plain text and ``html_text`` its rich text for older readers.

Revision ID: a6c3e8b1d742
Revises: 4d7a1c9e5b32
Create Date: 2026-10-10 09:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'a6c3e8b1d742'
down_revision = '4d7a1c9e5b32'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'taas_tasks',
        sa.Column(
            'description_doc', postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column('taas_tasks', 'description_doc')
