"""
🏃 Worker Application

Main worker application that orchestrates the Kafka consumer and handlers.

Start command: EXTRA_CONFIG=ews-worker uv run python -m ews_worker.main --reload
"""
import asyncio
import datetime
import os
import signal
import sys
import traceback
from asyncio.events import AbstractEventLoop
from typing import Optional

from aiohttp import web
from messaging_faststream import initialize_messaging_service

from foundation.config import get_settings
from foundation.exceptions.report_error import report_error
from foundation.messaging.types import IMessagingService
from foundation.observability.log_factory import LogFactory
from foundation.observability.tracing_factory import TracingFactory


def handle_asyncio_exception(loop, context):
    # context["message"] will have a description
    # context["exception"] will have the exception object
    err = context.get('exception')
    msg = context.get('message', 'Unknown error')
    if err:
        tm = TracingFactory().get_tracing_manager()
        if tm:
            tm.capture_exception(err)
        LogFactory().get_logger().error(f'🔴  [asyncio] {msg}: {err}', exc_info=True)
    else:
        LogFactory().get_logger().error(f'🔴  [asyncio] {msg}')


def _install_global_exception_handler() -> None:
    """Log unhandled exception tracebacks instead of dropping them silently."""

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        print('Unhandled exception occurred in worker:')
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        LogFactory().get_logger().error(
            'Unhandled exception in worker',
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = handle_exception


def get_current_datetime_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class BaseWorker:
    """
    A base worker for worker applications.

    Manages the lifecycle of the Kafka consumer,... and handles graceful shutdown.
    """

    def __init__(self, name: Optional[str] = 'BaseWorker'):
        self.running = False
        settings = get_settings()
        self.name = (
            name or f'{settings.app.TENANT_PREFIX}-{settings.app.SERVICE_NAME}'
        )
        self.logger = LogFactory().get_logger(self.name)
        self.start_time: Optional[datetime.datetime] = None
        self.health_server: Optional[web.Application] = None
        self.health_runner: Optional[web.AppRunner] = None
        self.messaging_service: Optional[IMessagingService] = None
        self.worker_tasks: list[tuple[str, asyncio.Task]] = []
        self.health_check_enabled: bool = getattr(settings, 'HEALTH_CHECK_ENABLE', True)
        self.health_check_server_port: int = getattr(
            settings, 'WORKER_LISTEN_PORT', 7000
        )
        self.outbox_poller_enabled: bool = getattr(
            settings, 'OUTBOX_POLLER_ENABLE', True
        )
        self.health_check_interval_seconds: int = getattr(
            settings, 'HEALTH_CHECK_INTERVAL', 10
        )

        self._health_check_task: Optional[asyncio.Task] = None

    def _owned_pending_tasks(self) -> list[asyncio.Task]:
        """Tasks owned by this worker (worker tasks + health check loop) still pending.

        Tasks spawned internally by the messaging service are not included —
        they are cleaned up by ``messaging_service.stop()`` during shutdown.
        """
        tasks = [task for _, task in self.worker_tasks]
        if self._health_check_task:
            tasks.append(self._health_check_task)
        current = asyncio.current_task()
        return [t for t in tasks if t is not current and not t.done()]

    async def health_check_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint for Docker/K8s."""
        if not self.running:
            return web.json_response(
                data={'status': 'unhealthy', 'reason': 'Worker not running'},
                status=503,
            )

        uptime = None
        if self.start_time:
            uptime = (get_current_datetime_utc() - self.start_time).total_seconds()

        # Report the actual state of each worker task; a task that finished
        # while the worker is still "running" means it died unexpectedly.
        tasks_status = {
            task_name: 'stopped' if task.done() else 'running'
            for task_name, task in self.worker_tasks
        }
        dead_tasks = [name for name, status in tasks_status.items() if status == 'stopped']
        if dead_tasks:
            return web.json_response(
                data={
                    'status': 'unhealthy',
                    'reason': f'Worker task(s) stopped: {", ".join(dead_tasks)}',
                    'worker_tasks': tasks_status,
                    'uptime_seconds': uptime,
                },
                status=503,
            )

        return web.json_response(
            {
                'status': 'OK',
                'worker_tasks': tasks_status,
                'uptime_seconds': uptime,
                # TODO: add more health metrics here, e.g. Kafka connectivity, last processed message timestamp, etc.
            }
        )

    async def start_health_server(self) -> None:
        """Start health check HTTP server."""
        if not self.health_check_enabled:
            self.logger.info('Health check server is disabled by configuration')
            return

        self.health_server = web.Application()
        self.health_server.router.add_get('/health', self.health_check_handler)

        self.health_runner = web.AppRunner(self.health_server)
        await self.health_runner.setup()

        site = web.TCPSite(self.health_runner, '0.0.0.0', self.health_check_server_port)
        await site.start()
        self.logger.info(
            f'⚙️ Health check server started on port {self.health_check_server_port}'
        )

    async def stop_health_server(self) -> None:
        """Stop health check HTTP server."""
        if self.health_runner:
            await self.health_runner.cleanup()
            self.logger.info('Health check server stopped')

    def setup_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Setup signal handlers for graceful shutdown.

        First Ctrl+C triggers graceful shutdown. Second Ctrl+C forces immediate exit.

        Args:
            loop: The asyncio event loop to attach signal handlers to
        """

        shutdown_requested = False

        def handle_shutdown():
            nonlocal shutdown_requested
            if shutdown_requested:
                # Second signal: force immediate exit
                self.logger.warning(
                    '⚡ Second shutdown signal received — forcing immediate exit'
                )
                os._exit(1)

            shutdown_requested = True
            self.logger.info(
                'Received shutdown signal (Ctrl+C or SIGTERM) — press again to force exit'
            )
            if not self.running:
                return

            self.logger.info('Cancelling worker tasks...')
            for task in self._owned_pending_tasks():
                self.logger.debug(f'⏹️ Cancelling task: {task.get_name()}')
                task.cancel()

        # Use asyncio's signal handling (works properly with event loop)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_shutdown)

        self.logger.debug('Signal handlers registered for SIGINT and SIGTERM')

    async def main(self):
        """Main entry point for the worker application."""

        if not self.worker_tasks:
            raise RuntimeError('No workers enabled!')

        self.logger.info('=' * 80)
        self.logger.info('🚀 Worker starting up')
        self.logger.info('=' * 80)

        # Get the current event loop and setup signal handlers
        loop: AbstractEventLoop = asyncio.get_running_loop()
        loop.set_exception_handler(handle_asyncio_exception)

        # FIXME Only for trace log bug, tobe remove when all bugs fixed
        _install_global_exception_handler()

        self.setup_signal_handlers(loop)

        # Start health check loop
        self._health_check_task = asyncio.create_task(self.health_check_loop())

        try:
            await self.start()
        except KeyboardInterrupt:
            self.logger.info('Received keyboard interrupt (Ctrl+C)')
        except asyncio.CancelledError:
            self.logger.info('Worker tasks cancelled')
        except Exception:
            self.logger.error('Worker application failed', exc_info=True)
        finally:
            # Shutdown is called inside self.start()'s finally block.
            # Only call it again if start() wasn't reached.
            if self.running:
                await self.shutdown()

            # Cancel health check task
            if not self._health_check_task.done():
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass

            self.logger.info('=' * 80)
            self.logger.info('👋 Worker shut down complete')
            self.logger.info('=' * 80)

    def register_event_handlers(self) -> None:
        """Hook for subclasses: register topics and event handlers.

        Called by :meth:`initialize_worker_tasks` after the messaging service
        is initialized and *before* the consumer task is created, so
        registrations are guaranteed to be in place before consumption starts.
        """
        self.logger.warning(
            'register_event_handlers() not implemented in subclass — no topics/handlers registered'
        )

    async def initialize_worker_tasks(self) -> 'BaseWorker':
        """Initialize worker tasks based on configuration."""

        # Initialize messaging service
        self.messaging_service = await initialize_messaging_service()

        # Register topics/handlers before the consumer task exists — avoids
        # relying on the consumer task not being scheduled until the next await.
        self.register_event_handlers()

        # Track background tasks at this level (store as instance variable for shutdown)
        self.worker_tasks = []

        if self.messaging_service.is_consumer_enabled():
            self.logger.info('📬 Kafka consumer enabled, initializing...')
            # Start consuming creates its own background tasks
            consumer_task = asyncio.create_task(
                self.messaging_service.start_consuming()
            )
            self.worker_tasks.append(('kafka_consumer', consumer_task))
        else:
            self.logger.info('📬 ⚫ Kafka consumer disabled by configuration')

        # Start Outbox poller if enabled
        # TODO: implement outbox poller and add here

        return self

    async def start(self) -> None:
        """Start the worker."""
        self.running = True
        self.start_time = get_current_datetime_utc()

        # Start health check server first
        await self.start_health_server()

        task_names = ', '.join(task_name for task_name, _ in self.worker_tasks)
        self.logger.info(
            f'🚀 Worker started with {len(self.worker_tasks)} background task(s): {task_names}'
        )

        # Wait for all tasks - if any fails, all should stop (fail-fast)
        try:
            await asyncio.gather(*[task for _, task in self.worker_tasks])
        except asyncio.CancelledError:
            self.logger.info('Worker tasks cancelled, initiating graceful shutdown...')
            # Don't re-raise, let it fall through to finally block
        except Exception as e:
            report_error(
                e,
                title='Worker Task Error',
                logger=self.logger,
            )
            raise
        finally:
            # Always cleanup on exit
            await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully shutdown the worker application."""
        if not self.running:
            return

        self.logger.info('[Shutdown] Shutting down worker application')
        self.running = False

        # Cancel tasks owned by this worker (worker_tasks + health check loop).
        # The helper excludes the current task to avoid self-cancellation inside
        # the finally/shutdown path; messaging-service internals are cleaned up
        # by messaging_service.stop() below.
        pending = self._owned_pending_tasks()
        if pending:
            self.logger.info(f'[Shutdown] Cancelling {len(pending)} tasks...')
            for task in pending:
                self.logger.debug(f'[Shutdown] Cancelling task: {task.get_name()}')
                task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=5.0,
                )
            except TimeoutError:
                self.logger.warning(
                    '[Shutdown] Timed out waiting for tasks to cancel — proceeding'
                )
            self.logger.info('[Shutdown] All tasks cancelled')

        # Stop consumer (this will clean up consumer-specific resources)
        if self.messaging_service:
            await self.messaging_service.stop()

        # TODO: stop outbox poller here once implemented

        # Stop health server
        await self.stop_health_server()

        # Calculate uptime
        if self.start_time:
            uptime = (get_current_datetime_utc() - self.start_time).total_seconds()
            self.logger.info(
                f'Worker application stopped, uptime_seconds {uptime}',
            )

    async def health_check_loop(self) -> None:
        """
        Periodic health check loop.

        Logs worker health metrics at regular intervals.
        """
        while self.running:
            try:
                await asyncio.sleep(delay=self.health_check_interval_seconds)
                uptime = None
                if self.start_time:
                    uptime = (
                        get_current_datetime_utc() - self.start_time
                    ).total_seconds()
                self.logger.info(
                    f'Worker [{self.name}] health check - uptime_seconds: {uptime} '
                )

            except Exception as e:
                report_error(
                    e,
                    title='Worker Health Check Error',
                    logger=self.logger,
                )
