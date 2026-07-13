"""

Revision ID: c765c8fc81a4
Revises: c1a2b3c4d5e6
Create Date: 2026-07-13 15:06:57.694318

"""

import warnings
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from advanced_alchemy.types import (
    GUID,
    ORA_JSONB,
    DateTimeUTC,
    EncryptedString,
    EncryptedText,
    FernetBackend,
    PasswordHash,
    StoredObject,
)
from advanced_alchemy.types.encrypted_string import PGCryptoBackend
from alembic import op
from sqlalchemy import Text  # noqa: F401

try:
    from advanced_alchemy.types.password_hash.argon2 import Argon2Hasher
except ImportError:
    Argon2Hasher = Any  # type: ignore
try:
    from advanced_alchemy.types.password_hash.passlib import PasslibHasher
except ImportError:
    PasslibHasher = Any  # type: ignore
try:
    from advanced_alchemy.types.password_hash.pwdlib import PwdlibHasher
except ImportError:
    PwdlibHasher = Any  # type: ignore

if TYPE_CHECKING:
    pass

__all__ = ["downgrade", "upgrade", "schema_upgrades", "schema_downgrades", "data_upgrades", "data_downgrades"]

sa.GUID = GUID
sa.DateTimeUTC = DateTimeUTC
sa.ORA_JSONB = ORA_JSONB
sa.EncryptedString = EncryptedString
sa.EncryptedText = EncryptedText
sa.StoredObject = StoredObject
sa.PasswordHash = PasswordHash
sa.Argon2Hasher = Argon2Hasher
sa.PasslibHasher = PasslibHasher
sa.PwdlibHasher = PwdlibHasher
sa.FernetBackend = FernetBackend
sa.PGCryptoBackend = PGCryptoBackend

# revision identifiers, used by Alembic.
revision = 'c765c8fc81a4'
down_revision = 'c1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            schema_upgrades()
            data_upgrades()

def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            data_downgrades()
            schema_downgrades()

def schema_upgrades() -> None:
    """schema upgrade migrations go here."""
    op.create_table(
        'resiliant_processed_events',
        sa.Column('id', sa.GUID(length=16), nullable=False),
        sa.Column('idempotency_key', sa.String(length=512), nullable=False, comment="Composite idempotency key: '<handler_name>:<event_id>'"),
        sa.Column('event_id', sa.String(length=255), nullable=False, comment='Original event ID from event.metadata.event_id'),
        sa.Column('event_type', sa.String(length=255), nullable=False, comment="Event type for analytics (e.g. 'deposit.completed')"),
        sa.Column('handler_name', sa.String(length=255), nullable=False, comment='Name of the handler that processed this event'),
        sa.Column('saga_id', sa.Text(), nullable=True, comment='Optional saga UUID for linking to saga_state rows'),
        sa.Column('correlation_id', sa.String(length=255), nullable=True, comment='W3C correlation ID propagated from the original request'),
        sa.Column('tenant_id', sa.Text(), nullable=True, comment='Tenant ID for multi-tenant replay queries'),
        sa.Column('extra_metadata', sa.JSON(), nullable=True, comment='Free-form JSON for future extensibility'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False, comment='Wall-clock time when the row was inserted'),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_resiliant_processed_events')),
        sa.UniqueConstraint('idempotency_key', name='uq_processed_events_key'),
    )
    with op.batch_alter_table('resiliant_processed_events', schema=None) as batch_op:
        batch_op.create_index('idx_idempotency_created_at', ['created_at'], unique=False)
        batch_op.create_index('idx_idempotency_event_id', ['event_id'], unique=False)
        batch_op.create_index('idx_idempotency_tenant', ['tenant_id', 'event_id'], unique=False)

def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    with op.batch_alter_table('resiliant_processed_events', schema=None) as batch_op:
        batch_op.drop_index('idx_idempotency_tenant')
        batch_op.drop_index('idx_idempotency_event_id')
        batch_op.drop_index('idx_idempotency_created_at')
    op.drop_table('resiliant_processed_events')

def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""

def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
