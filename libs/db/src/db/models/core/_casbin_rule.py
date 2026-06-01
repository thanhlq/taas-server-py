from __future__ import annotations

from sqlalchemy import (
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import AdvancedDeclarativeBase


class CasbinRule(AdvancedDeclarativeBase):
    __tablename__ = 'casbin_rule'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ptype = mapped_column(String(255))
    v0 = mapped_column(String(255))
    v1 = mapped_column(String(255))
    v2 = mapped_column(String(255))
    v3 = mapped_column(String(255))
    v4 = mapped_column(String(255))
    v5 = mapped_column(String(255))

    def __str__(self):
        arr = [self.ptype]
        for v in (self.v0, self.v1, self.v2, self.v3, self.v4, self.v5):
            if v is None:
                break
            arr.append(v)
        return ', '.join(arr)

    def __repr__(self):
        return f'<CasbinRule {self.id}: "{str(self)}">'
