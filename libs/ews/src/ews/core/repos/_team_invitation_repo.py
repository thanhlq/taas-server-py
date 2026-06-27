from db import BaseAsyncRepository

import db.models.core as core_models


class TeamInvitationRepository(BaseAsyncRepository[core_models.TeamInvitation]):
    model_type = core_models.TeamInvitation
