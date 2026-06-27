from db import BaseAsyncRepository

import db.models.core as core_models


class UserOAuthAccountRepository(BaseAsyncRepository[core_models.UserOAuthAccount]):
    model_type = core_models.UserOAuthAccount
