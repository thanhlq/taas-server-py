from db import BaseAsyncRepository

import db.models.core as core_models


class RefreshTokenRepository(BaseAsyncRepository[core_models.RefreshToken]):
    model_type = core_models.RefreshToken
