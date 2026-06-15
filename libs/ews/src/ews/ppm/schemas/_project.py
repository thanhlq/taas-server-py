from typing import Optional
from datetime import datetime
from platform_core.serialization import ApiResponse
from platform_core.serialization._serializer_pydantic import BaseEntityPydantic


class Project(ApiResponse):
    id: int
    name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectEntityPy(BaseEntityPydantic):
    id: int
    name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None