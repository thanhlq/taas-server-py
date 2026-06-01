from __future__ import annotations

from advanced_alchemy.base import orm_registry
from sqlalchemy import UUID, Column, ForeignKey, Table

from .constants import TAG_TABLE, TEAM_TABLE, TEAM_TAG_TABLE

team_tag = Table(
    TEAM_TAG_TABLE,
    orm_registry.metadata,
    Column(
        'org_id',
        UUID(as_uuid=True),
        ForeignKey(f'{TEAM_TABLE}.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column(
        'tag_id',
        UUID(as_uuid=True),
        ForeignKey(f'{TAG_TABLE}.id', ondelete='CASCADE'),
        primary_key=True,
    ),
)
