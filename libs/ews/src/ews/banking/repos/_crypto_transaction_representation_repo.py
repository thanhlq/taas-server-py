from db import BaseAsyncRepository
from db.models.banking._crypto_tx_representation import CryptoTransactionRepresentationOrm


class CryptoTransactionRepresentationRepository(
    BaseAsyncRepository[CryptoTransactionRepresentationOrm]
):
    model_type = CryptoTransactionRepresentationOrm
