from platform_core.config import Settings
from platform_core.http import BaseController, get
from platform_core.http.context import Context
from platform_core.utils.datetime_utils import now_as_iso


class PlatformController(BaseController):
    api_prefix = "/"
    settings: Settings

    def __init__(self):
        self.settings = Settings()

    @get(path='/health')
    def health(self, ctx: Context) -> dict:
        """
        Health check endpoint.
        Args:
            ctx (Context): The request context. Injected by the framework (Litestar/FastAPI).
        Returns:
            dict: A dictionary containing the health status and metadata.
        """
        healthcheck = {
            'status': 'healthy',
            'timestamp': now_as_iso(),
            'environment': self.settings.environment,
            'version': 'v0.0.1',
        }

        req = ctx.req

        request_info = {
            'method': req.method,
            'path': req.url.path,
            'query_params': str(req.url.query) if req.url.query else None,
            'client_host': req.client.host if req.client else None,
            'user_agent': req.headers.get('user-agent', 'unknown'),
            'accept': req.headers.get('accept', 'unknown'),
            'accept_encoding': req.headers.get('accept-encoding', 'unknown'),
            'accept_language': req.headers.get('accept-language', 'unknown'),
        }
        healthcheck['request'] = request_info

        return healthcheck

