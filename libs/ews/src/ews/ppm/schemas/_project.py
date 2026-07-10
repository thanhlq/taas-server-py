from datetime import datetime
from typing import Optional

from foundation.serialization import ApiResponse
from foundation.serialization._serializer_pydantic import BaseEntityPydantic


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
