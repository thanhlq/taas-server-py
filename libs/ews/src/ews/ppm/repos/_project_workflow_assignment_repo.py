from db import BaseAsyncRepository

import db.models.ews as ews_models


class ProjectWorkflowAssignmentRepository(BaseAsyncRepository[ews_models.ProjectWorkflowAssignment]):
    model_type = ews_models.ProjectWorkflowAssignment
