import logging
from logging import Logger
from typing import TYPE_CHECKING, Any, Optional

from platform_core.http import AppConfig
from platform_core.utils.singleton import singleton

from .config import (
    is_elk_tracing_enabled,
    is_otel_tracing_enabled,
    is_tracing_enabled,
)
from .defaults import NoopContextTracer
from .types import IContextTracer, ITracingManager

if TYPE_CHECKING:
    from platform_core.observability.types import InstrumentSettings


@singleton
class TracingFactory:
    _tracing_manager: Optional[ITracingManager] = None
    _logger: Optional[Logger] = None

    @property
    def logger(self) -> Logger:
        if not self._logger:
            self._logger = logging.getLogger('TracingFactory')
        return self._logger

    def get_tracing_manager(self) -> Optional[ITracingManager]:
        if not self._tracing_manager:
            from .factory import TracingManager
            self._tracing_manager = TracingManager(self.logger)
        return self._tracing_manager

    def init_instrumentation(self, app_settings: AppConfig) -> None:
        _config: 'InstrumentSettings' = app_settings.get_instrumentation_settings()
        if _config.logger:
            self._logger = _config.logger

        if not is_tracing_enabled():
            self.logger.info('⚫ Tracing is not enabled.')
            return

        if _config.database_instrument:

        if _config.fastapi_app:
            self.trace_fastapi_app(_config.fastapi_app)

        if _config.aiokafka_instrument:
            self.trace_aiokafka(
                a_producer_hook=_config.aiokafka_producer_hook,
                a_consumer_hook=_config.aiokafka_consumer_hook,
            )

        self._tracing_manager = _config.tracing_manager_class(self.logger)  if _config.tracing_manager_class else self.get_tracing_manager()
        self.__initialized = True
        self.logger.info('TracingFactory initialized with manager: %s', type(self._tracing_manager).__name__)

    def trace_database(self) -> None:
        if is_otel_tracing_enabled():
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            # Instrument every engine via `engines=[...]` (a single `engine=` covers
            # only one, and a second instrument() call is a no-op). Async engines are
            # instrumented through their `.sync_engine`.
            engines = []

            # Main application DB (e.g. crypto_vn)
            try:
                from db. import db as _db
                if _db._engine is not None:  # type: ignore[attr-defined]
                    engines.append(_db._engine.sync_engine)  # type: ignore[attr-defined]
            except Exception:
                pass

            # Keycloak / identity DB (e.g. crypto_ids) — a separate engine
            # (core/keycloak/kc_db.py); without it those queries are never traced.
            try:
                from core.keycloak.kc_db import db as _kc_db
                if _kc_db._engine is not None:  # type: ignore[attr-defined]
                    engines.append(_kc_db._engine.sync_engine)  # type: ignore[attr-defined]
            except Exception:
                pass

            if engines:
                SQLAlchemyInstrumentor().instrument(engines=engines)

                # Per-database dependency resource ("postgresql/<db>"): the
                # instrumentor only sets db.system, so a before_cursor_execute
                # listener (registered after it) stamps peer.service per query.
                from sqlalchemy import event

                for _eng in engines:
                    event.listen(_eng, 'before_cursor_execute', _set_db_peer_service)
            else:
                SQLAlchemyInstrumentor().instrument()

            self.logger.info(
                f'🔭 SqlAlchemy Instrumented with OpenTelemetry ({len(engines)} engine(s))'
            )

        # ELK SQLAlchemy instrumentation is handled by elasticapm.instrument()

    def get_context_tracer(self) -> type[IContextTracer]:
        if is_elk_tracing_enabled() or is_otel_tracing_enabled():
            if not self._tracing_manager:
                raise ValueError('TracingManager is not initialized.')

            return self._tracing_manager.get_context_tracer()
        else:
            return NoopContextTracer

    def trace_fastapi_app(self, fastapi_app: Any) -> None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(fastapi_app)
        self.logger.info('🔭 FastAPI Instrumented with OpenTelemetry configured')

    def trace_aiokafka(self, a_producer_hook, a_consumer_hook) -> None:
        if is_otel_tracing_enabled():
            from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor

            AIOKafkaInstrumentor().instrument(
                async_produce_hook=a_producer_hook, async_consume_hook=a_consumer_hook
            )
            self.logger.info('🔭 AIOKafka Instrumented with OpenTelemetry configured')

        elif is_elk_tracing_enabled():
            pass
