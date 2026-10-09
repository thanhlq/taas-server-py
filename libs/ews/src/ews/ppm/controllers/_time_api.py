"""Time tracking routes (taas-specs/ppm/time-expense/time-tracking-spec.md §7): categories, entries (+ corrections), the
timer, weekly timesheets (grid cells, copy, submit, approve / reject, reopen, approval queue), item effort and a
project's time (+ CSV). Rules live in ``ews.ppm._time``; capability ``time_tracking`` (Ppm-0009) is enforced here."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException, PermissionDeniedException
from foundation.http import BaseController, delete, get, patch, post, put, status
from foundation.http.context_state import get_request_context

from ews.security import RequestScope, current_scope, is_allowed
from ews.shared import parse_uuid, raw_response

from .. import _access as access
from .. import _settings
from .. import _time as time
from ..schemas._time_api import (
    PpmEffortOut,
    PpmProjectTimeOut,
    PpmTimeCategoryOut,
    PpmTimeCorrectionIn,
    PpmTimeEntryIn,
    PpmTimeEntryOut,
    PpmTimeEntryPatch,
    PpmTimerStartIn,
    PpmTimesheetCellIn,
    PpmTimesheetCellsIn,
    PpmTimesheetCopyIn,
    PpmTimesheetCopyOut,
    PpmTimesheetDecisionIn,
    PpmTimesheetOut,
    PpmTimesheetQueueItemOut,
    PpmTimesheetReopenIn,
)


async def _scope(session: DBAsyncScopedSession) -> RequestScope:
    scope = await current_scope()
    await _settings.require_capability(session, scope, 'time_tracking')
    return scope


async def _entries(
    session: DBAsyncScopedSession, rows: list[Any]
) -> list[PpmTimeEntryOut]:
    return [PpmTimeEntryOut(**e) for e in await time.entries_out(session, rows)]


def _entry_in(
    data: PpmTimeEntryIn | PpmTimerStartIn, source: str = 'manual'
) -> time.EntryIn:
    return time.EntryIn(
        task_id=data.task_id,
        project_id=data.project_id,
        category=data.category,
        entry_date=data.entry_date,
        minutes=getattr(data, 'minutes', None),
        start_time=getattr(data, 'start_time', None),
        end_time=getattr(data, 'end_time', None),
        is_billable=data.is_billable,
        description=data.description,
        user=getattr(data, 'user_id', None),
        source=source,
    )


async def _sheet_out(
    session: DBAsyncScopedSession, scope: RequestScope, sheet: Any
) -> PpmTimesheetOut:
    return PpmTimesheetOut(**await time.week_view(session, scope, sheet))


class PpmTimeController(BaseController):
    """Categories, entries and the timer of the caller (``/api/v1/ppm``)."""

    api_prefix = '/api/v1/ppm'
    tags = ('Time',)

    @get('/time-categories')
    @db_context_session(auto_commit=True)
    async def list_categories(
        self, session: DBAsyncScopedSession
    ) -> list[PpmTimeCategoryOut]:
        scope = await _scope(session)
        return [
            PpmTimeCategoryOut(
                id=str(c.id),
                key=c.key,
                name=c.name,
                kind=c.kind,
                billable_allowed=c.billable_allowed,
                active=c.active,
            )
            for c in await time.categories(session, scope)
        ]

    @get('/time-entries')
    @db_context_session
    async def list_entries(
        self,
        session: DBAsyncScopedSession,
        user_id: Optional[str] = None,
        task_id: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        status: Optional[str] = None,
    ) -> list[PpmTimeEntryOut]:
        """The caller's entries (another person's with ``ppm.time_entry:manage`` on the organization)."""
        scope = await _scope(session)
        me = access.author(scope)
        user = (user_id or '').strip() or me
        if user != me and not await is_allowed(
            scope, time.TIME_ENTRY, 'manage', scope.org_domains()
        ):
            raise PermissionDeniedException(
                detail=f'missing permission {time.TIME_ENTRY}:manage'
            )
        rows = await time.my_entries(
            session,
            scope,
            user=user,
            date_from=date_from,
            date_to=date_to,
            task_id=parse_uuid(task_id, 'task') if task_id else None,
            status=status,
        )
        return await _entries(session, rows)

    @post('/time-entries', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_entry(
        self, data: PpmTimeEntryIn, session: DBAsyncScopedSession
    ) -> PpmTimeEntryOut:
        scope = await _scope(session)
        entry = await time.create_entry(session, scope, _entry_in(data))
        return (await _entries(session, [entry]))[0]

    @patch('/time-entries/{entry_id}')
    @db_context_session(auto_commit=True)
    async def update_entry(
        self, entry_id: str, data: PpmTimeEntryPatch, session: DBAsyncScopedSession
    ) -> PpmTimeEntryOut:
        scope = await _scope(session)
        entry = await time.load_entry(session, scope, entry_id, 'update')
        entry = await time.update_entry(session, scope, entry, data.as_dict())
        return (await _entries(session, [entry]))[0]

    @delete('/time-entries/{entry_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_entry(self, entry_id: str, session: DBAsyncScopedSession) -> None:
        scope = await _scope(session)
        entry = await time.load_entry(session, scope, entry_id, 'delete')
        await time.delete_entry(session, scope, entry)

    @post('/time-entries/{entry_id}/correct', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def correct_entry(
        self, entry_id: str, data: PpmTimeCorrectionIn, session: DBAsyncScopedSession
    ) -> list[PpmTimeEntryOut]:
        """Reversal (− minutes) + corrected entry for a locked / approved one (Ppm-1243)."""
        scope = await _scope(session)
        entry = await time.load_entry(session, scope, entry_id, 'update')
        rows = await time.correct_entry(
            session,
            scope,
            entry,
            minutes=data.minutes,
            reason=data.reason,
            description=data.description,
        )
        return await _entries(session, rows)

    @get('/timers/current')
    @db_context_session
    async def current_timer(
        self, session: DBAsyncScopedSession
    ) -> list[PpmTimeEntryOut]:
        """The caller's running timer (empty list when none)."""
        scope = await _scope(session)
        running = await time.current_timer(session, scope)
        return await _entries(session, [running] if running else [])

    @post('/timers/start', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def start_timer(
        self, data: PpmTimerStartIn, session: DBAsyncScopedSession
    ) -> PpmTimeEntryOut:
        """Start a timer (a running one stops first, Ppm-1211)."""
        scope = await _scope(session)
        entry = await time.start_timer(session, scope, _entry_in(data, 'timer'))
        return (await _entries(session, [entry]))[0]

    @post('/timers/stop')
    @db_context_session(auto_commit=True)
    async def stop_timer(self, session: DBAsyncScopedSession) -> list[PpmTimeEntryOut]:
        scope = await _scope(session)
        running = await time.current_timer(session, scope)
        if running is None:
            return []
        return await _entries(session, [await time.stop_timer(session, scope, running)])


class PpmTimesheetController(BaseController):
    """Weekly timesheets (Ppm-1230 … 1243)."""

    api_prefix = '/api/v1/ppm/timesheets'
    tags = ('Time',)

    @get('/approvals')
    @db_context_session
    async def approval_queue(
        self, session: DBAsyncScopedSession
    ) -> list[PpmTimesheetQueueItemOut]:
        """Timesheets waiting for the caller's decision."""
        scope = await _scope(session)
        return [
            PpmTimesheetQueueItemOut(**t)
            for t in await time.approval_queue(session, scope)
        ]

    @get('/')
    @db_context_session(auto_commit=True)
    async def week(
        self,
        session: DBAsyncScopedSession,
        week: Optional[date] = None,
        user_id: Optional[str] = None,
    ) -> PpmTimesheetOut:
        """The week holding ``week`` (default today) of the caller or of ``user_id`` (approvers), created lazily."""
        scope = await _scope(session)
        settings = await time.settings_for(session, scope.organization_id)
        user = (user_id or '').strip() or access.author(scope)
        sheet = await time.sheet_for(
            session, scope, user, week or time.today(), settings
        )
        if not await time.can_view_sheet(session, scope, sheet):
            raise NotFoundException(detail='timesheet not found')
        return await _sheet_out(session, scope, sheet)

    @get('/{sheet_id}')
    @db_context_session
    async def get_sheet(
        self, sheet_id: str, session: DBAsyncScopedSession
    ) -> PpmTimesheetOut:
        scope = await _scope(session)
        sheet = await time.load_sheet(session, scope, sheet_id)
        if not await time.can_view_sheet(session, scope, sheet):
            raise NotFoundException(detail='timesheet not found')
        return await _sheet_out(session, scope, sheet)

    @put('/{sheet_id}/cells')
    @db_context_session(auto_commit=True)
    async def write_cells(
        self, sheet_id: str, data: PpmTimesheetCellsIn, session: DBAsyncScopedSession
    ) -> PpmTimesheetOut:
        scope = await _scope(session)
        sheet = await time.load_sheet(session, scope, sheet_id)
        await time.write_cells(session, scope, sheet, [_cell(c) for c in data.cells])
        return await _sheet_out(session, scope, sheet)

    @post('/{sheet_id}/copy-previous')
    @db_context_session(auto_commit=True)
    async def copy_previous(
        self, sheet_id: str, data: PpmTimesheetCopyIn, session: DBAsyncScopedSession
    ) -> PpmTimesheetCopyOut:
        scope = await _scope(session)
        sheet = await time.load_sheet(session, scope, sheet_id)
        if sheet.user_id != access.author(scope):
            raise PermissionDeniedException(
                detail='only the person edits their timesheet'
            )
        out = await time.copy_previous(
            session, scope, sheet, with_hours=data.with_hours
        )
        return PpmTimesheetCopyOut(
            **out, timesheet=await _sheet_out(session, scope, sheet)
        )

    @post('/{sheet_id}/submit')
    @db_context_session(auto_commit=True)
    async def submit(
        self, sheet_id: str, session: DBAsyncScopedSession
    ) -> PpmTimesheetOut:
        scope = await _scope(session)
        sheet = await time.submit(
            session, scope, await time.load_sheet(session, scope, sheet_id)
        )
        return await _sheet_out(session, scope, sheet)

    @post('/{sheet_id}/approve')
    @db_context_session(auto_commit=True)
    async def approve(
        self, sheet_id: str, data: PpmTimesheetDecisionIn, session: DBAsyncScopedSession
    ) -> PpmTimesheetOut:
        scope = await _scope(session)
        sheet = await time.load_sheet(session, scope, sheet_id)
        await time.decide(
            session,
            scope,
            sheet,
            decision='approved',
            note=data.note,
            section=data.section,
        )
        return await _sheet_out(session, scope, sheet)

    @post('/{sheet_id}/reject')
    @db_context_session(auto_commit=True)
    async def reject(
        self, sheet_id: str, data: PpmTimesheetDecisionIn, session: DBAsyncScopedSession
    ) -> PpmTimesheetOut:
        """A rejection needs a note (400 ``comment_required``)."""
        scope = await _scope(session)
        sheet = await time.load_sheet(session, scope, sheet_id)
        await time.decide(
            session,
            scope,
            sheet,
            decision='rejected',
            note=data.note,
            section=data.section,
        )
        return await _sheet_out(session, scope, sheet)

    @post('/{sheet_id}/reopen')
    @db_context_session(auto_commit=True)
    async def reopen(
        self, sheet_id: str, data: PpmTimesheetReopenIn, session: DBAsyncScopedSession
    ) -> PpmTimesheetOut:
        scope = await _scope(session)
        sheet = await time.reopen(
            session, scope, await time.load_sheet(session, scope, sheet_id), data.reason
        )
        return await _sheet_out(session, scope, sheet)


def _cell(c: PpmTimesheetCellIn) -> time.CellIn:
    return time.CellIn(
        entry_date=c.entry_date,
        minutes=c.minutes,
        task_id=c.task_id,
        project_id=c.project_id,
        category=c.category,
        is_billable=c.is_billable,
    )


class TaskEffortController(BaseController):
    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get(
        '/{task_id}/effort',
        summary='Own + roll-up estimate, actual, remaining, forecast, variance',
    )
    @db_context_session
    async def effort(self, task_id: str, session: DBAsyncScopedSession) -> PpmEffortOut:
        scope = await current_scope()
        task, _ = await access.load_task(session, scope, task_id)
        return PpmEffortOut(**time.effort_out(task))


class ProjectTimeController(BaseController):
    """A project's time (Ppm-1250)."""

    api_prefix = '/api/v1/projects'
    tags = ('Time',)

    @staticmethod
    async def _rows(
        session: DBAsyncScopedSession,
        project_id: str,
        date_from: Optional[date],
        date_to: Optional[date],
        status_: Optional[str],
        billable: Optional[bool],
        user_id: Optional[str],
    ) -> list[Any]:
        scope = await _scope(session)
        project = await access.load_project(
            session, scope, project_id, time.TIME_ENTRY, 'read'
        )
        return await time.project_entries(
            session,
            project,
            date_from=date_from,
            date_to=date_to,
            status=status_,
            billable=billable,
            user=user_id,
        )

    @get('/{project_id}/time-entries.csv')
    @db_context_session
    async def export(
        self,
        project_id: str,
        session: DBAsyncScopedSession,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        status: Optional[str] = None,
        billable: Optional[bool] = None,
        user_id: Optional[str] = None,
    ) -> Any:
        rows = await self._rows(
            session, project_id, date_from, date_to, status, billable, user_id
        )
        ctx = get_request_context()
        return raw_response(
            time.entries_csv(rows).encode('utf-8'),
            media_type='text/csv; charset=utf-8',
            request=ctx.req if ctx else None,
            headers={
                'content-disposition': 'attachment; filename="time-entries.csv"',
                'cache-control': 'no-store',
            },
        )

    @get('/{project_id}/time-entries')
    @db_context_session
    async def list_entries(
        self,
        project_id: str,
        session: DBAsyncScopedSession,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        status: Optional[str] = None,
        billable: Optional[bool] = None,
        user_id: Optional[str] = None,
    ) -> PpmProjectTimeOut:
        rows = await self._rows(
            session, project_id, date_from, date_to, status, billable, user_id
        )
        return PpmProjectTimeOut(
            items=[
                PpmTimeEntryOut(**e)
                for e in await time.entries_out(session, [e for e, _ in rows])
            ],
            **time.totals(rows),
        )


__all__ = [
    'PpmTimeController',
    'PpmTimesheetController',
    'ProjectTimeController',
    'TaskEffortController',
]
