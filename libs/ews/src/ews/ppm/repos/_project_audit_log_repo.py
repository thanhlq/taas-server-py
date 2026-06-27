from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectAuditLogRepository(BaseAsyncRepository[ews_models.ProjectAuditLog]):
    model_type = ews_models.ProjectAuditLog
