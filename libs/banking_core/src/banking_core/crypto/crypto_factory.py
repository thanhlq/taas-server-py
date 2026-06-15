
from libs.banking_core.src.banking_core.crypto.services._crypto_token import CryptoTokenService
from platform_core.db.types import DBAsyncScopedSession, DBAsyncSession

class CryptoFactory:

    @staticmethod
    def get_crypto_token_service(session: DBAsyncSession | DBAsyncScopedSession) -> CryptoTokenService:

        return Crypto()