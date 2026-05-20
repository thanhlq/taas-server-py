from typing import Optional
from datetime import datetime
from platform_core.api.schema import CamelizedBaseStruct


class Project(CamelizedBaseStruct):
    id: int
    name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None