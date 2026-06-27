from db import BaseAsyncRepository

import db.models.banking as banking_models


class CryptoTokenRepository(BaseAsyncRepository[banking_models.CryptoToken]):
    model_type = banking_models.CryptoToken
