from db import BaseAsyncRepository
from db.models.core._organization import OrganizationTable


class OrganizationTableRepository(BaseAsyncRepository[OrganizationTable]):
    model_type = OrganizationTable
