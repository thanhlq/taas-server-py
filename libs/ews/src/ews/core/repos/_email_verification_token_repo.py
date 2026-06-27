from db import BaseAsyncRepository

import db.models.core as core_models


class EmailVerificationTokenRepository(BaseAsyncRepository[core_models.EmailVerificationToken]):
    model_type = core_models.EmailVerificationToken
