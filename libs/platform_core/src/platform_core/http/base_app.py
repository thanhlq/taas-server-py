import logging
from abc import ABC, abstractmethod
from logging import Logger
from typing import Optional

from litestar.utils import join_paths
from rich.console import Console

from platform_core.cli import get_console
from platform_core.config import DatabaseSettings, Settings
from platform_core.config.app import AppConfig
from platform_core.config.openapi import build_openapi_config
from platform_core.observability.types import InstrumentSettings

__all__ = ('BaseApiApplication', 'AppConfig')


class BaseApiApplication[A](ABC):
    _app: A
    _config: AppConfig
    _db_config: DatabaseSettings
    _all_settings: Settings
    _console: Console
    _logger: Logger
    _runtime_path: str

    def __init__(self, settings: Settings, runtime_path: str, instrumentation: InstrumentSettings | None) -> None:
        self._all_settings = settings
        self._config = AppConfig(
            app_name=settings.app.NAME,
            debug=settings.app.DEBUG,
            compression_config=settings.app.get_compression_config(),
            ratelimit_config=settings.app.get_ratelimit_config(),
            distributed_lock_config=settings.app.get_distributed_lock_config(),
            websocket_config=settings.app.get_websocket_config(),
            cors_config=settings.app.get_cors_config(),
            # csrf_config=config.app.get_csrf_config(),
            instrumentation=instrumentation or InstrumentSettings(),
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

    def get_instrument_settings(self) -> InstrumentSettings:
        return self._config.instrumentation # type: ignore

    @property
    def all_settings(self) -> Settings:
        return self._all_settings

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
        from platform_core.cli._show_app_info import (
            show_api_app_info,
        )

        show_api_app_info(self)

        # if self.config.debug:
        #     show_all_environment_variables()

    @abstractmethod
    def get_app_controllers(self) -> list:
        """Return a list of controller instances to register on the app."""
        ...
