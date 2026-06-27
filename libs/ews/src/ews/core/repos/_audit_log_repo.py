from db import BaseAsyncRepository

import db.models.core as core_models


class AuditLogRepository(BaseAsyncRepository[core_models.AuditLog]):
    model_type = core_models.AuditLog
