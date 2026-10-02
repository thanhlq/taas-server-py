"""Builders for the durable-timer / scheduler components (entry point of this folder)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from foundation.resiliant.schedule import ScheduleConfig
from sqlalchemy.ext.asyncio import AsyncSession

from .schedule_poller import SchedulerPoller
from .schedule_repository import ScheduleRepository
from .schedule_service import Clock, ScheduleService
from .schedule_settings import get_schedule_config


def build_schedule_repository(config: ScheduleConfig | None = None) -> ScheduleRepository:
    """Return a :class:`ScheduleRepository`."""
    return ScheduleRepository(config or get_schedule_config())


def build_schedule_service(config: ScheduleConfig | None = None, clock: Clock | None = None) -> ScheduleService:
    """Return a :class:`ScheduleService` (config from the ``SCHEDULE_*`` environment by default)."""
    config = config or get_schedule_config()
    return ScheduleService(config=config, repository=build_schedule_repository(config), clock=clock)


def build_scheduler_poller(
    session_factory: Callable[[], AsyncSession],
    config: ScheduleConfig | None = None,
    publisher: Any | None = None,
    service: ScheduleService | None = None,
) -> SchedulerPoller:
    """Return a :class:`SchedulerPoller` (pass the app's ``service`` to share its config / clock)."""
    return SchedulerPoller(
        session_factory,
        service=service or build_schedule_service(config),
        publisher=publisher,
    )
