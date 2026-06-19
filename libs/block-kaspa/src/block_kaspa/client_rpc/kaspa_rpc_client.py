from platform_core.utils.singleton import singleton
from block_kaspa import KaspaSettings
from kaspa import Generator, PrivateKey, Resolver, RpcClient, kaspa_to_sompi


@singleton
class KaspaRpcClient:
    _client: RpcClient | None
    _settings: KaspaSettings | None

    def __init__(self):
        self._client = None

    @property
    def settings(self) -> KaspaSettings:
        if not self._settings:
            self._settings = KaspaSettings()
        return self._settings

    async def connect(self) -> RpcClient:
        if self._client is None:
            client = RpcClient(resolver=Resolver(), network_id=self.settings.network_id)
            client.connect()
            self._client = client
        return self._client
