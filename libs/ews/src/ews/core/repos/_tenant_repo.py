from db import BaseAsyncRepository
from db.models.core._tenant import Tenant


class TenantRepository(BaseAsyncRepository[Tenant]):
    model_type = Tenant
