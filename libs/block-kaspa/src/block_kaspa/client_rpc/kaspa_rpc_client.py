from logging import Logger
from platform_core.utils.singleton import singleton
from block_kaspa import KaspaSettings
from kaspa import Generator, PrivateKey, Resolver, RpcClient, kaspa_to_sompi


@singleton
class KaspaRpcClient:
    _client: RpcClient | None
    _settings: KaspaSettings | None = None
    _logger: Logger | None = None

    def __init__(self):
        self._client = None

    @property
    def logger(self):
        if self._logger is None:
             from platform_core.logger import logger
             self._logger = logger
        return self._logger


    @property
    def settings(self) -> KaspaSettings:
        if not self._settings:
            self._settings = KaspaSettings()
        return self._settings

    async def connect(self) -> RpcClient:
        if self._client is None:
            config = self.settings
            if config.rpc_url is not None:
                # Supported as: url1, url2, url3 -> need to split and trim
                urls = [url.strip() for url in config.rpc_url.split(',') if url.strip()]
                self.logger.info(f'Connecting to Kaspa, network {config.network_id}, RPC at {config.rpc_url}...')
                # client = RpcClient(url=config.rpc_url, network_id=self.settings.network_id)
                client = RpcClient(resolver=Resolver(urls=urls), network_id=self.settings.network_id)
            else:
                self.logger.info(f'Connecting to Kaspa, network {config.network_id}, RPC with resolver...')
                client = RpcClient(resolver=Resolver(), network_id=self.settings.network_id)
            await client.connect()
            self._client = client
        return self._client
