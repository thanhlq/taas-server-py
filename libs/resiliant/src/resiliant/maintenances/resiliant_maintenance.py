"""
Housekeeping on a durable cron — the Python twin of ``ResiliantMaintenance`` of
``@taas/resiliant`` (same job name, same sweeps). No external cron, no leader
election: the job is a singleton row (``unique_key``) and the scheduler's
SKIP LOCKED claim makes exactly one replica (Python or Node) run it.

One run: purge published outbox rows past retention, delete expired idempotency
keys, archive terminal dead letters, return stale DLQ leases. Every sweep is bounded
(batches, max rounds, one short transaction each); what is left goes to the next run.

    register_maintenance_callbacks(scheduler_poller)   # the worker hosting the scheduler
    await define_maintenance_jobs()                     # any process, idempotent

Settings: ``RESILIANT_MAINTENANCE_ENABLED`` (default true), ``RESILIANT_MAINTENANCE_CRON``
(default ``0 2 * * *``, UTC).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from foundation.db.advanced_db_manager import MainDatabase
from foundation.observability.log_factory import LogFactory
from foundation.utils.env_utils import get_env
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.outbox.outbox_repository import OutboxRepository
from resiliant.outbox.outbox_settings import get_outbox_config
from resiliant.outbox.registry import outbox_definitions
from resiliant.sql import describe_error

if TYPE_CHECKING:
    from resiliant.schedule import SchedulerPoller

RESILIANT_MAINTENANCE_JOB = 'resiliant:maintenance'
DEFAULT_MAINTENANCE_CRON = '0 2 * * *'
MAX_ROUNDS = 50

_logger = LogFactory().get_logger('ResiliantMaintenance')


@dataclass
class MaintenanceReport:
    outbox_purged: dict[str, int] = field(default_factory=dict)
    idempotency_expired: int = 0
    dlq_archived: int = 0
    dlq_stale_reset: int = 0
    errors: list[str] = field(default_factory=list)


def maintenance_cron() -> str:
    return get_env('RESILIANT_MAINTENANCE_CRON', DEFAULT_MAINTENANCE_CRON)()


class ResiliantMaintenance:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        idempotency: Any,
        dlq: Any,
        schedule: Any,
    ) -> None:
        self.session_factory = session_factory
        self.idempotency = idempotency
        self.dlq = dlq
        self.schedule = schedule

    async def _step(self, step: Callable[[AsyncSession], Awaitable[int]]) -> int:
        async with self.session_factory() as session, session.begin():
            return await step(session)

    async def _sweep(
        self,
        what: str,
        report: MaintenanceReport,
        step: Callable[[AsyncSession], Awaitable[int]],
    ) -> int:
        total = 0
        try:
            for _ in range(MAX_ROUNDS):
                n = await self._step(step)
                total += n
                if n == 0:
                    break
        except Exception as error:  # noqa: BLE001 - recorded, the next sweep still runs
            report.errors.append(f'{what}: {describe_error(error)}')
        return total

    async def run(self) -> MaintenanceReport:
        report = MaintenanceReport()
        for definition in outbox_definitions():
            config = definition.config or get_outbox_config()
            repository = OutboxRepository(definition.model, config)
            older_than_ms = config.retention_days * 86_400_000
            report.outbox_purged[definition.name] = await self._sweep(
                f'outbox {definition.name}',
                report,
                lambda s, r=repository, ms=older_than_ms: r.purge_published(s, ms),
            )
        report.idempotency_expired = await self._sweep(
            'idempotency', report, self.idempotency.cleanup_expired
        )
        report.dlq_archived = await self._sweep('dlq archive', report, self.dlq.archive)
        try:
            report.dlq_stale_reset = await self._step(self.dlq.reset_stale)
        except Exception as error:  # noqa: BLE001
            report.errors.append(f'dlq reset: {describe_error(error)}')
        _logger.info(f'maintenance done: {asdict(report)}')
        return report

    async def ensure_scheduled(self, session: AsyncSession, cron_expr: str) -> bool:
        """Idempotently create the cron job; ``False`` when it already exists."""
        job = await self.schedule.schedule_cron(
            session,
            job_name=RESILIANT_MAINTENANCE_JOB,
            unique_key=RESILIANT_MAINTENANCE_JOB,
            cron_expr=cron_expr,
        )
        if job is not None:
            _logger.info(
                f'scheduled {RESILIANT_MAINTENANCE_JOB} ({cron_expr}), first run {job.next_run_at.isoformat()}'
            )
        return job is not None

    def register(self, poller: SchedulerPoller) -> None:
        """The job's callback on the poller of the worker hosting the scheduler."""

        async def callback(_job: Any) -> None:
            report = await self.run()
            if report.errors:
                raise RuntimeError(
                    f'maintenance finished with errors: {"; ".join(report.errors)}'
                )

        poller.register(RESILIANT_MAINTENANCE_JOB, callback)


def build_maintenance(
    session_factory: Callable[[], AsyncSession] | None = None,
) -> ResiliantMaintenance:
    from resiliant import ResiliantServiceFactory

    factory = ResiliantServiceFactory()
    return ResiliantMaintenance(
        session_factory or MainDatabase.get_instance().new_session,
        idempotency=factory.get_idempotency_service(),
        dlq=factory.get_dlq_service(),
        schedule=factory.get_schedule_service(),
    )


def register_maintenance_callbacks(poller: SchedulerPoller) -> None:
    """Register the maintenance callback (call once in ``outbox_worker``, before the poller fires)."""
    build_maintenance().register(poller)


async def define_maintenance_jobs() -> bool:
    """Ensure the maintenance cron job exists (safe on every startup)."""
    if not get_env('RESILIANT_MAINTENANCE_ENABLED', True)():
        _logger.info('Resiliant maintenance disabled; skipping job definition')
        return False
    maintenance = build_maintenance()
    async with maintenance.session_factory() as session, session.begin():
        return await maintenance.ensure_scheduled(session, maintenance_cron())


__all__ = [
    'DEFAULT_MAINTENANCE_CRON',
    'MaintenanceReport',
    'RESILIANT_MAINTENANCE_JOB',
    'ResiliantMaintenance',
    'build_maintenance',
    'define_maintenance_jobs',
    'maintenance_cron',
    'register_maintenance_callbacks',
]
