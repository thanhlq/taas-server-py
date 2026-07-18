from db import BaseAsyncRepository
from db.models.core._organization import Organization


class OrganizationRepository(BaseAsyncRepository[Organization]):
    model_type = Organization
