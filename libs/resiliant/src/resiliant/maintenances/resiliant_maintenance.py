"""
Scheduled maintenance for the transactional outbox.

The ``message_outbox`` table is weekly-partitioned; two PL/pgSQL functions
(shipped with its migration) create the upcoming partitions and drop expired
ones. :class:`OutboxPartitionMaintainer` wraps them, and here we drive it from a
**durable CRON schedule** so the relay's hot table stays small — no external
cron, no Faust timer.

How it fits together:

* :func:`define_maintenance_jobs` — creates the CRON job row (idempotent, safe to
  call on every startup). Scheduling can run in any process.
* :func:`register_maintenance_callbacks` — registers the in-process handler on
  the ``SchedulerPoller`` (in ``outbox_worker``) that actually runs the
  maintenance when the job fires. The job has **no channel**, so the scheduler
  dispatches it to this callback rather than publishing to a topic.

Manual testing: set ``RESILIANT_MAINTENANCE_TEST_MODE=true`` to switch the cron
to every 5 minutes instead of the daily 02:00 UTC schedule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from foundation.config import get_settings
from foundation.db.advanced_db_manager import AdvancedDBManager, MainDatabase
from foundation.observability.log_factory import LogFactory
from foundation.resiliant.schedule import IScheduleService
from foundation.utils.env_utils import get_env

from resiliant import ResiliantServiceFactory
from resiliant.outbox.partition_maintenance import OutboxPartitionMaintainer

if TYPE_CHECKING:
    from db.models.resiliant import ScheduledJobTable
    from resiliant.schedule import SchedulerPoller

_logger = LogFactory().get_logger('ResiliantMaintenance')

# Job name — also the key the SchedulerPoller uses to find the callback below.
OUTBOX_MAINTENANCE_JOB = 'outbox_maintenance'

# Production cron: daily at 02:00 UTC (a low-traffic window).
DEFAULT_MAINTENANCE_CRON = '0 2 * * *'
# Manual-test cron: every 5 minutes. Toggle with RESILIANT_MAINTENANCE_TEST_MODE.
TEST_MAINTENANCE_CRON = '*/5 * * * *'

# Partition window defaults (overridable via env).
DEFAULT_LOOKAHEAD_WEEKS = 4
DEFAULT_RETENTION_WEEKS = 12


def maintenance_cron() -> str:
    """Return the cron expression, honouring the 5-minute manual-test toggle."""
    if get_env('RESILIANT_MAINTENANCE_TEST_MODE', False)():
        return TEST_MAINTENANCE_CRON
    return get_env('RESILIANT_MAINTENANCE_CRON', DEFAULT_MAINTENANCE_CRON)()


def _maintenance_payload() -> dict[str, int]:
    return {
        'lookahead_weeks': get_env(
            'OUTBOX_PARTITION_LOOKAHEAD_WEEKS', DEFAULT_LOOKAHEAD_WEEKS, int
        )(),
        'retention_weeks': get_env(
            'OUTBOX_PARTITION_RETENTION_WEEKS', DEFAULT_RETENTION_WEEKS, int
        )(),
    }


def get_outbox_partition_maintainer() -> OutboxPartitionMaintainer:
    """Return an :class:`OutboxPartitionMaintainer` for the active tenant."""
    settings = get_settings()
    return OutboxPartitionMaintainer(prefix=settings.app.TENANT_PREFIX)


async def run_outbox_maintenance(job: ScheduledJobTable) -> None:
    """SchedulerPoller callback: create upcoming and drop expired partitions.

    Reads the partition window from ``job.payload`` (falling back to defaults),
    so the cadence and the window can be tuned independently of the code.
    """
    payload = job.payload or {}
    maintainer = get_outbox_partition_maintainer()
    result = await maintainer.maintain(
        lookahead_weeks=int(payload.get('lookahead_weeks', DEFAULT_LOOKAHEAD_WEEKS)),
        retention_weeks=int(payload.get('retention_weeks', DEFAULT_RETENTION_WEEKS)),
    )
    _logger.info(
        'outbox_maintenance fired: created=%s dropped=%s',
        result.created or 'none',
        result.dropped or 'none',
    )


def register_maintenance_callbacks(poller: SchedulerPoller) -> None:
    """Register the in-process maintenance handlers on a ``SchedulerPoller``.

    Call once in the worker that hosts the scheduler (``outbox_worker``), after
    the poller is built and before it starts firing jobs.
    """
    poller.register(OUTBOX_MAINTENANCE_JOB, run_outbox_maintenance)


async def define_maintenance_jobs() -> None:
    """Idempotently ensure the outbox-maintenance CRON job exists.

    Safe to call on every startup: if an active job with the same name is
    already scheduled, this is a no-op.
    """
    if not get_env('RESILIANT_MAINTENANCE_ENABLED', True)():
        _logger.info('Resiliant maintenance disabled; skipping job definition')
        return

    schedule: IScheduleService = ResiliantServiceFactory().get_schedule_service()
    db: AdvancedDBManager = MainDatabase.get_instance()
    cron = maintenance_cron()

    async with db.new_session() as session:
        async with session.begin():
            if await schedule.exists_active(session, OUTBOX_MAINTENANCE_JOB):
                _logger.info(
                    'outbox_maintenance already scheduled; leaving it unchanged'
                )
                return
            await schedule.schedule_cron(
                session,
                job_name=OUTBOX_MAINTENANCE_JOB,
                cron_expr=cron,
                payload=_maintenance_payload(),
                # No channel -> dispatched to the registered in-process callback.
            )
    _logger.info('Scheduled outbox_maintenance (cron=%s)', cron)
