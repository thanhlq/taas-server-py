from db import BaseAsyncRepository

import db.models.core as core_models


class TeamMemberRepository(BaseAsyncRepository[core_models.TeamMember]):
    model_type = core_models.TeamMember
