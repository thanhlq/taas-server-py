import logging
from abc import ABC, abstractmethod
from logging import Logger
from typing import Optional

import socketio
from litestar.utils import join_paths
from rich.console import Console

from foundation.app.app_config import AppConfig
from foundation.cli import get_console
from foundation.config import DatabaseSettings, Settings
from foundation.config.openapi import build_openapi_config
from foundation.messaging.types import MessagingServiceT
from foundation.observability.types import ServiceInstrumentConfig
from foundation.state import get_service

__all__ = ('BaseApiApplication', 'AppConfig')


class BaseApiApplication[A](ABC):
    _app: A
    _config: AppConfig
    _db_config: DatabaseSettings
    _settings: Settings
    _console: Console
    _logger: Logger
    _runtime_path: str
    _socketio_app: Optional[socketio.ASGIApp] = None

    def __init__(self, settings: Settings, runtime_path: str, instrumentation: ServiceInstrumentConfig | None = None) -> None:
        self._settings = settings
        self._config = AppConfig(
            name=settings.app.NAME,
            debug=settings.app.DEBUG,
            compression_config=settings.app.get_compression_config(),
            ratelimit_config=settings.app.get_ratelimit_config(),
            distributed_lock_config=settings.app.get_distributed_lock_config(),
            websocket_config=settings.app.get_websocket_config(),
            cors_config=settings.app.get_cors_config(),
            # csrf_config=config.app.get_csrf_config(),
            instrumentation=instrumentation or ServiceInstrumentConfig(),
        )
        self._runtime_path = runtime_path
        self._db_config = settings.db
        self.openapi_enabled = settings.app.OPENAPI_ENABLED
        if self.openapi_enabled:
            self._config.openapi_config = build_openapi_config(
                title=f'{settings.app.NAME} API',
                version=settings.app.VERSION,
            )

        self.template_engine = None

        self.show_app_info()

    def get_instrument_settings(self) -> ServiceInstrumentConfig:
        return self._config.instrumentation # type: ignore

    @property
    def messaging_service(self) -> MessagingServiceT:
        return get_service(MessagingServiceT)

    @property
    def settings(self) -> Settings:
        return self._settings

    def get_app_runtime_path(self, *subpaths: Optional[str]) -> str:
        """Construct a path relative to the app's runtime path."""
        if not subpaths:
            return self._runtime_path
        else:
            return join_paths(self._runtime_path, *subpaths)

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

    def is_websocket_enabled(self) -> bool:
        return True

    def is_wss_logging_enable(self) -> bool:
        """ Check if websocket logging is enabled based on the configuration. """
        return (
            self.config.websocket_config is not None
            and self.config.websocket_config.debug
        )

    @property
    def websocket_app(self) -> socketio.ASGIApp:
        if self._socketio_app is None:
            raise RuntimeError(
                'WebSocket app has not been built yet. Call get_app() first to build the app.'
            )
        return self._socketio_app

    @abstractmethod
    def get_app_id(self) -> str:
        """Return a unique identifier for this application, used for things like caching."""
        raise NotImplementedError('Subclasses must implement this method.')

    def get_app(self) -> A:
        """Return the ASGI app instance, building it if it hasn't been built yet."""
        if not hasattr(self, '_app'):
            self._app = self.build_application()
        return self._app

    @abstractmethod
    def build_application(self) -> A:
        """Build the actual ASGI app instance, this is called during app initialization."""
        ...

    def show_app_info(self) -> None:
        from foundation.cli._show_app_info import (
            show_api_app_info,
        )

        show_api_app_info(self)

        # if self.config.debug:
        #     show_all_environment_variables()

    @abstractmethod
    def _get_enabled_app_controllers(self) -> list:
        """Return a list of controller instances to register on the app."""
        ...
