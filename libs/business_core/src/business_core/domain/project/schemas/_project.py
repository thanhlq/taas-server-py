from typing import Optional
from datetime import datetime
from platform_core.api.schema import CamelizedBaseStruct
from platform_core.pydantic._serializer import BaseEntityPydantic


class Project(CamelizedBaseStruct):
    id: int
    name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectEntityPy(BaseEntityPydantic):
    id: int
    name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None