from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from .constants import CHECKLIST_ITEMS_TABLE, CHECKLIST_TEMPLATES_TABLE

if TYPE_CHECKING:
    from ._checklist_template import ChecklistTemplate


class ChecklistTemplateItem(UUIDv7Base, SoftDeleteColumns):
    """Checklist Template Item.

    How to apply the items to a task: When a task is created with a checklist
    template, the corresponding checklist items are copied from the template to
    the task's checklist. Each task is only linked to a specific checklist
    template, and the items are duplicated for that task.
    """

    __tablename__ = CHECKLIST_ITEMS_TABLE

    template_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{CHECKLIST_TEMPLATES_TABLE}.id'), nullable=True
    )
    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    is_mandatory: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    display_order: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text("'-1'::integer")
    )

    template: Mapped[Optional['ChecklistTemplate']] = relationship(
        'ChecklistTemplate',
        foreign_keys=[template_id],
        back_populates='items',
    )
