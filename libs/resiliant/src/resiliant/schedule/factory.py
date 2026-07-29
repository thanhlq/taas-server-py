"""Builders for the durable-timer / scheduler components."""

from __future__ import annotations

from typing import Callable, Optional

from foundation.messaging.types import IMessagingService
from foundation.resiliant.schedule import ScheduleConfig
from sqlalchemy.ext.asyncio import AsyncSession

from .schedule_poller import SchedulerPoller
from .schedule_repository import ScheduleRepository
from .schedule_service import ScheduleService
from .schedule_settings import get_schedule_config


def build_schedule_repository(config: ScheduleConfig | None = None) -> ScheduleRepository:
    """Return a :class:`ScheduleRepository` built from ``config``."""
    return ScheduleRepository(config or get_schedule_config())


def build_schedule_service(config: ScheduleConfig | None = None) -> ScheduleService:
    """Return a :class:`ScheduleService` wired to a fresh repository."""
    config = config or get_schedule_config()
    return ScheduleService(config=config, repository=build_schedule_repository(config))


def build_scheduler_poller(
    session_factory: Callable[[], AsyncSession],
    config: ScheduleConfig | None = None,
    publisher: Optional[IMessagingService] = None,
) -> SchedulerPoller:
    """Return a :class:`SchedulerPoller` wired to a fresh repository."""
    config = config or get_schedule_config()
    return SchedulerPoller(
        config=config,
        session_factory=session_factory,
        publisher=publisher,
        repository=build_schedule_repository(config),
    )
