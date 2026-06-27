from db import BaseAsyncRepository

import db.models.core as core_models


class PasswordResetTokenRepository(BaseAsyncRepository[core_models.PasswordResetToken]):
    model_type = core_models.PasswordResetToken
