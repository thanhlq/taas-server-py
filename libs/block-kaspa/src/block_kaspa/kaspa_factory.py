from foundation.utils.singleton import singleton
from block_kaspa.client_rest import KaspaRestClient


@singleton
class KaspaFactory:

    @staticmethod
    def get_rest_client() -> KaspaRestClient:
        return KaspaRestClient()
