from foundation.db.types import DBAsyncScopedSession, DBAsyncSession

from banking_core.crypto.services import CryptoTokenService


class CryptoFactory:
    @staticmethod
    def get_crypto_token_service(
        session: DBAsyncSession | DBAsyncScopedSession,
    ) -> CryptoTokenService:

        return CryptoTokenService(session)
