from platform_core.config import Settings
import logging
from logging import Logger
from platform_core.cli import get_console
from rich.console import Console
from abc import abstractmethod, ABC
from dataclasses import field

from platform_core.config.allowed_hosts import AllowedHostsConfig
from platform_core.config.app import AppConfig
from platform_core.config.compression import CompressionConfig
from platform_core.config.cors import CORSConfig
from platform_core.config.csrf import CSRFConfig
from platform_core.openapi.config import OpenAPIConfig
from platform_core.utils.singleton import singleton


__all__ = ('BaseApiApplication', 'AppConfig')


class BaseApiApplication[A](ABC):
    _app: A
    _config: AppConfig
    _console: Console
    _logger: Logger

    def __init__(self, settings: Settings) -> None:
        self._config = AppConfig(
            compression_config=settings.app.get_compression_config(),
            ratelimit_config=settings.app.get_ratelimit_config(),
            distributed_lock_config=settings.app.get_distributed_lock_config(),
            websocket_config=settings.app.get_websocket_config(),
            cors_config=settings.app.get_cors_config(),
            # csrf_config=config.app.get_csrf_config(),
        )
        self.template_engine = None

    @property
    def logger(self) -> Logger:
        if not hasattr(self, '_logger'):
            self._logger = logging.getLogger(self.get_app_id())
        return self._logger

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def console(self) -> Console:
        if not hasattr(self, '_console'):
            self._console = get_console()
        return self._console

    @abstractmethod
    def get_app_id(self) -> str:
        """Return a unique identifier for this application, used for things like caching."""
        raise NotImplementedError('Subclasses must implement this method.')

    def build_app(self) -> A:
        """Build the actual ASGI app instance, this is called during app initialization."""
        raise NotImplementedError('Subclasses must implement this method.')

    def get_app(self) -> A:
        """Return the ASGI app instance, building it if it hasn't been built yet."""
        if not hasattr(self, '_app'):
            self._app = self.build_app()
        return self._app
