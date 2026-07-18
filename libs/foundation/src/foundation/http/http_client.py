from typing import Optional

import httpx
from httpx import Limits


class HttpxClient:
    """
    - A simple wrapper around httpx.AsyncClient to provide a consistent interface for making HTTP requests.
    - The implementation also allow to define a reusable connection pool for multiple requests
    - Singleton

    Usage: This wrapper can be used exactly same as httpx.AsyncClient i.e. with async with HttpxClient() as client: ...


    Examples:
        async with HttpxClient() as client:
            try:
                response = await client.request(method='POST',
                                                url=webhook_url,
                                                headers={
                                                    'Content-Type': 'application/json'
                                                },
                                                json=dict(text=message),
                                                timeout=self.request_timeout)
                if not response.is_success:
                    self.logger.error(
                        'Failed to send Mattermost Webhook for channel {}, error {}'.format(channel, response.json()))
            except httpx.RequestError as e:
    """

    _instance: Optional['HttpxClient'] = None
    _enabled_pool = True
    """ Whether to enable connection pooling. If True, a single AsyncClient instance will be reused for all requests."""
    _timeout_seconds = 10.0
    _client: Optional[httpx.AsyncClient] = None

    def __init__(self):
        pass

    def __new__(cls):
        if not hasattr(cls, '_instance'):
            cls._instance = HttpxClient()
        return cls._instance

    def get_client(self, **kwargs) -> httpx.AsyncClient:
        if self._enabled_pool:
            if self._client is None:
                # connection pool
                limits: Limits = Limits(max_connections=10, max_keepalive_connections=5)
                self._client = httpx.AsyncClient(
                    timeout=self._timeout_seconds,
                    follow_redirects=True,
                    limits=limits,
                    **kwargs,
                )
            return self._client
        else:
            # Pool is disabled, create a new client for each request
            return httpx.AsyncClient(
                timeout=self._timeout_seconds, follow_redirects=True, **kwargs
            )

    async def __aenter__(self):
        return self.get_client()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._enabled_pool:
            pass
        else:
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    async def fetch(self, url: str):
        return await self.get_client().get(url)

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
