"""``/api/v1/ppm/my-work`` — the session user's personal task center (my-work-spec §7, ADR-18). Plans are private;
actions on items reuse the work item endpoints (complete, reopen, checklist PATCH, notifications read)."""

from __future__ import annotations

from datetime import date
from typing import Any

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, put, status

from ews.security import current_scope

from .. import _my_work as mw
from .. import _settings as ppm_settings
from ..schemas._my_work_api import (
    PpmMyWorkCount,
    PpmMyWorkCountsOut,
    PpmMyWorkDoneOut,
    PpmMyWorkEntryOut,
    PpmMyWorkOut,
    PpmMyWorkPlanIn,
    PpmMyWorkProjectRef,
    PpmMyWorkRescheduleIn,
    PpmMyWorkStageRef,
    PpmQuickAddIn,
)
from ..schemas._task_api import TaskResponse
from ._task_support import task_to_response


def _ids(value: str | None) -> list[str]:
    return [v for v in (value or '').split(',') if v.strip()]


def _filters(
    project_id: str | None,
    source: str | None,
    priority: str | None,
    role: str | None,
    inbox: bool,
    snoozed: bool,
    q: str | None,
) -> mw.Filters:
    from ews.shared import parse_uuid

    return mw.Filters(
        project_ids=[parse_uuid(p, 'project') for p in _ids(project_id)],
        sources=[s for s in _ids(source) if s in mw.SOURCES],
        priorities=[int(p) for p in _ids(priority) if p.isdigit()],
        role=role if role in ('owner', 'collaborator') else None,
        inbox=inbox,
        snoozed=snoozed,
        q=q,
    )


def _entry(e: mw.Entry) -> PpmMyWorkEntryOut:
    t = e.task
    remaining = None
    if t.estimated_minutes:
        remaining = max(0, t.estimated_minutes - (t.actual_minutes or 0))
    return PpmMyWorkEntryOut(
        source_type=e.source_type,
        source_id=e.source_id,
        task_id=str(t.id),
        code=t.code,
        name=e.name,
        task_name=t.name if e.source_type != 'task' else None,
        project=PpmMyWorkProjectRef(
            id=str(e.project.id),
            name=e.project.name,
            color=e.project.color,
            kind=e.project.kind or 'project',
        ),
        item_type=t.work_item_type,
        priority=t.priority or 0,
        stage=PpmMyWorkStageRef(
            id=str(e.stage.id), name=e.stage.name, stage_type=e.stage.stage_type
        )
        if e.stage
        else None,
        start_date=t.start_date,
        due_date=e.due,
        planned_date=e.planned,
        snoozed_until=e.snoozed_until,
        bucket=e.bucket,
        overdue_reason=e.overdue_reason,
        sort_key=e.sort_key,
        role=e.role,
        subtasks=PpmMyWorkCount(done=t.done_child_count or 0, total=t.child_count or 0)
        if t.child_count
        else None,
        checklist=PpmMyWorkCount(
            done=t.checklist_done or 0, total=t.checklist_total or 0
        )
        if t.checklist_total and e.source_type == 'task'
        else None,
        remaining_minutes=remaining if e.source_type == 'task' else None,
        excerpt=e.excerpt,
        actor_name=e.extra.get('actor_name'),
        workflow_id=str(t.workflow_id) if t.workflow_id else None,
    )


class MyWorkController(BaseController):
    api_prefix = '/api/v1/ppm/my-work'
    tags = ('My Work',)

    @get(
        '/',
        summary='Everything waiting for me, bucketed by my planned date (else the due date)',
    )
    @db_context_session
    async def my_work(
        self,
        session: DBAsyncScopedSession,
        tz: str | None = None,
        project_id: str | None = None,
        source: str | None = None,
        priority: str | None = None,
        role: str | None = None,
        inbox: bool = False,
        snoozed: bool = False,
        q: str | None = None,
        bucket: str | None = None,
        limit: int = mw.MAX_ENTRIES,
        offset: int = 0,
    ) -> PpmMyWorkOut:
        scope = await current_scope()
        await ppm_settings.require_capability(session, scope, 'my_work')
        settings = await mw.user_settings(session, scope)
        clock = mw.Clock.of(tz, settings['week_start'])
        entries = await mw.collect(
            session,
            scope,
            clock,
            _filters(project_id, source, priority, role, inbox, snoozed, q),
        )
        counts = dict.fromkeys(mw.BUCKETS, 0)
        for e in entries:
            counts[e.bucket] += 1
        planned = sum(
            max(0, (e.task.estimated_minutes or 0) - (e.task.actual_minutes or 0))
            for e in entries
            if e.bucket == 'today' and e.source_type == 'task'
        )
        if bucket in mw.BUCKETS:
            entries = [e for e in entries if e.bucket == bucket]
        page = entries[offset : offset + max(1, min(limit, mw.MAX_ENTRIES))]
        box = await mw.inbox(session, scope, create=False)
        done = await mw.done_today(session, scope, clock, tz)
        return PpmMyWorkOut(
            entries=[_entry(e) for e in page],
            counts=counts,
            today=clock.today,
            week_end=clock.week_end,
            inbox_project_id=str(box.id) if box else None,
            done_today=[
                PpmMyWorkDoneOut(
                    task_id=str(t.id),
                    code=t.code,
                    name=t.name,
                    project_name=p.name,
                    completed_at=t.completed_at,
                )
                for t, p in done
            ],
            settings=settings,
            planned_minutes_today=planned,
        )

    @get('/counts', summary='Bucket counts and the sidebar badge (Overdue + Today)')
    @db_context_session
    async def counts(
        self, session: DBAsyncScopedSession, tz: str | None = None
    ) -> PpmMyWorkCountsOut:
        scope = await current_scope()
        if not await ppm_settings.enabled(session, scope, 'my_work'):
            return PpmMyWorkCountsOut()
        settings = await mw.user_settings(session, scope)
        clock = mw.Clock.of(tz, settings['week_start'])
        counts = dict.fromkeys(mw.BUCKETS, 0)
        for e in await mw.collect(session, scope, clock, mw.Filters()):
            counts[e.bucket] += 1
        return PpmMyWorkCountsOut(
            counts=counts, badge=counts['overdue'] + counts['today']
        )

    @put(
        '/plans/{source_type}/{source_id}',
        summary='My planned date, order and snooze of one entry (private)',
    )
    @db_context_session(auto_commit=True)
    async def set_plan(
        self,
        source_type: str,
        source_id: str,
        data: PpmMyWorkPlanIn,
        session: DBAsyncScopedSession,
    ) -> PpmMyWorkPlanIn:
        scope = await current_scope()
        plan = await mw.set_plan(
            session,
            scope,
            source_type,
            source_id,
            planned_date=data.planned_date,
            sort_key=data.sort_key,
            snoozed_until=data.snoozed_until,
        )
        return PpmMyWorkPlanIn(
            planned_date=plan.planned_date,
            sort_key=plan.sort_key,
            snoozed_until=plan.snoozed_until,
        )

    @delete('/plans/{source_type}/{source_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def clear_plan(
        self, source_type: str, source_id: str, session: DBAsyncScopedSession
    ) -> None:
        await mw.clear_plan(session, await current_scope(), source_type, source_id)

    @post(
        '/reschedule', summary='Plan every overdue entry (or the given ones) on a day'
    )
    @db_context_session(auto_commit=True)
    async def reschedule(
        self,
        data: PpmMyWorkRescheduleIn,
        session: DBAsyncScopedSession,
        tz: str | None = None,
    ) -> PpmMyWorkCountsOut:
        scope = await current_scope()
        settings = await mw.user_settings(session, scope)
        clock = mw.Clock.of(tz, settings['week_start'])
        refs = (
            [(r.source_type, r.source_id) for r in data.refs]
            if data.refs is not None
            else None
        )
        moved = await mw.reschedule(
            session, scope, clock, planned_date=data.planned_date, refs=refs
        )
        return PpmMyWorkCountsOut(badge=moved)

    @post(
        '/tasks',
        status_code=status.HTTP_201_CREATED,
        summary='Quick add (to my Inbox without a project)',
    )
    @db_context_session(auto_commit=True)
    async def quick_add(
        self, data: PpmQuickAddIn, session: DBAsyncScopedSession
    ) -> TaskResponse:
        scope = await current_scope()
        task = await mw.quick_add(
            session,
            scope,
            name=data.name,
            project_id=data.project_id,
            planned_date=data.planned_date,
            due_date=data.due_date,
            priority=data.priority,
        )
        return task_to_response(task)

    @get(
        '/settings',
        summary='My Work settings (week start, working days, day capacity, default view)',
    )
    @db_context_session
    async def get_settings(self, session: DBAsyncScopedSession) -> dict[str, Any]:
        return await mw.user_settings(session, await current_scope())

    @patch('/settings')
    @db_context_session(auto_commit=True)
    async def patch_settings(
        self, data: dict[str, Any], session: DBAsyncScopedSession
    ) -> dict[str, Any]:
        return await mw.save_settings(session, await current_scope(), data)


__all__ = ['MyWorkController', 'date']
