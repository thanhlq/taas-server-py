from db import BaseAsyncRepository

import db.models.core as core_models


class TeamRepository(BaseAsyncRepository[core_models.Team]):
    model_type = core_models.Team
