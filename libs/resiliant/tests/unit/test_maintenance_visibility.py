"""Maintenance (retention sweeps, singleton cron job) and the visibility snapshot on the
real database — same behaviour as ``ResiliantMaintenance`` / ``ResilienceVisibilityService``
of ``@taas/resiliant``."""

from __future__ import annotations

from foundation.resiliant.dlq import DLQStatus
from foundation.resiliant.outbox import OutboxConfig, OutboxStatus
from resiliant import ResiliantServiceBuilder
from resiliant.maintenances import RESILIANT_MAINTENANCE_JOB, ResiliantMaintenance
from resiliant.models import (
    DLQEventArchiveTable,
    DLQEventTable,
    MessagingOutboxTable,
    ProcessedEventTable,
    ScheduledJobTable,
)
from resiliant.outbox.factory import build_messaging_outbox_service
from resiliant.visibility import ResilienceVisibilityService
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def services():
    return (
        ResiliantServiceBuilder.build_idempotency_service(),
        ResiliantServiceBuilder.build_dlq_service(),
        ResiliantServiceBuilder.build_schedule_service(),
    )


async def _count(session: AsyncSession, model) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(model))).scalar() or 0
    )


async def test_maintenance_run_sweeps_every_table(
    db_session: AsyncSession, db_engine
) -> None:
    maker = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    idempotency, dlq, schedule = services()
    outbox = build_messaging_outbox_service(OutboxConfig())
    old = await outbox.save_raw_message(
        db_session, channel='c', payload={}, event_type='E'
    )
    await outbox.save_raw_message(db_session, channel='c', payload={}, event_type='E')
    await db_session.execute(
        update(MessagingOutboxTable)
        .where(MessagingOutboxTable.id == old.id)
        .values(
            status=OutboxStatus.PUBLISHED,
            processed_at=text("now() - interval '30 days'"),
        )
    )
    await idempotency.mark_processed(db_session, 'H:old', 'old', '', 'H')
    await db_session.execute(
        text(
            f"update {ProcessedEventTable.__tablename__} set created_at = now() - interval '400 days'"
        )
    )
    dead_id = (
        await dlq.save_event(
            db_session,
            event_id='e1',
            event_type='E',
            handler_name='H',
            payload={},
            error='x',
        )
    ).id
    await db_session.execute(
        update(DLQEventTable).values(
            status=DLQStatus.CANCELLED, updated_at=text("now() - interval '400 days'")
        )
    )
    await db_session.commit()

    report = await ResiliantMaintenance(
        maker, idempotency=idempotency, dlq=dlq, schedule=schedule
    ).run()
    assert report.errors == []
    assert report.outbox_purged['messaging'] == 1
    assert report.idempotency_expired == 1
    assert report.dlq_archived == 1
    async with maker() as s:
        assert await _count(s, MessagingOutboxTable) == 1
        assert await _count(s, ProcessedEventTable) == 0
        assert (await s.get(DLQEventArchiveTable, dead_id)) is not None


async def test_maintenance_job_is_a_singleton(
    db_session: AsyncSession, db_engine
) -> None:
    maker = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    idempotency, dlq, schedule = services()
    maintenance = ResiliantMaintenance(
        maker, idempotency=idempotency, dlq=dlq, schedule=schedule
    )
    assert await maintenance.ensure_scheduled(db_session, '0 2 * * *') is True
    assert await maintenance.ensure_scheduled(db_session, '0 2 * * *') is False
    await db_session.commit()
    jobs = (await db_session.execute(select(ScheduledJobTable))).scalars().all()
    assert [(j.job_name, j.unique_key, j.cron_expr) for j in jobs] == [
        (RESILIANT_MAINTENANCE_JOB, RESILIANT_MAINTENANCE_JOB, '0 2 * * *')
    ]


async def test_visibility_snapshot_reports_problems(db_session: AsyncSession) -> None:
    _, dlq, schedule = services()
    visibility = ResilienceVisibilityService(dlq=dlq, schedule=schedule)
    healthy = await visibility.snapshot(db_session)
    assert healthy['healthy'] is True and healthy['problems'] == []
    assert {o['outbox'] for o in healthy['outboxes']} == {'messaging', 'transaction'}

    outbox = build_messaging_outbox_service(OutboxConfig())
    row = await outbox.save_raw_message(
        db_session, channel='c', payload={}, event_type='E'
    )
    await db_session.execute(
        update(MessagingOutboxTable)
        .where(MessagingOutboxTable.id == row.id)
        .values(status=OutboxStatus.DEAD_LETTER)
    )
    await dlq.save_event(
        db_session,
        event_id='e2',
        event_type='E',
        handler_name='H',
        payload={},
        error='x',
    )
    snap = await visibility.snapshot(db_session)
    assert snap['healthy'] is False
    assert 'outbox messaging: 1 dead-lettered' in snap['problems']
    assert 'dlq: 1 awaiting retry' in snap['problems']
