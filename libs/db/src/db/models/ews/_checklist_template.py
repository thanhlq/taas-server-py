from __future__ import annotations
from foundation.types.types import SimpleStatus

from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, Boolean, ForeignKey, text, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, JSONB, SoftDeleteColumns
from .constants import CHECKLIST_TEMPLATES_TABLE, PROJECTS_TABLE

if TYPE_CHECKING:
    from ._checklist_template_item import ChecklistTemplateItem


class ChecklistTemplate(UUIDv7Base, SoftDeleteColumns):
    """Checklist Template"""

    __tablename__ = CHECKLIST_TEMPLATES_TABLE

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    template_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(
        TEXT,
        nullable=True,
        server_default=text("'task'::character"),
        index=True,
    )

    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True, index=True
    )

    is_template: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('true')
    )
    status: Mapped[SimpleStatus] = mapped_column(
        Enum(SimpleStatus), nullable=True, server_default=text('1')
    )

    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    items: Mapped[list['ChecklistTemplateItem']] = relationship(
        'ChecklistTemplateItem',
        foreign_keys='ChecklistTemplateItem.template_id',
        back_populates='template',
        lazy='selectin',
    )
