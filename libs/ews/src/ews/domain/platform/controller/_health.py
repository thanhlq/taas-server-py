from platform_core.config import Settings
from platform_core.utils.datetime_utils import now_as_iso


class PlatformController:
    api_prefix = "/"
    settings: Settings

    def __init__(self, router):
        self.router = router
        self.settings = Settings()
        self._register_routes()

    def _register_routes(self):
        @self.router.get(path="/health")
        def health() -> dict:
            healthcheck = {
                'status': 'healthy',
                'timestamp': now_as_iso(),
                'environment': self.settings.environment,
                'version': 'v0.0.1',
            }

            return healthcheck

