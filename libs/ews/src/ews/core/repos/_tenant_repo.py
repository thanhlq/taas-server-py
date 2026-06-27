from db import BaseAsyncRepository
from db.models.core._tenant import TenantTable


class TenantTableRepository(BaseAsyncRepository[TenantTable]):
    model_type = TenantTable
