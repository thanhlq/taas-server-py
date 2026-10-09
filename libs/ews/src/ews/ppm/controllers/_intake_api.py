"""Intake routes (taas-specs/ppm/intake/intake-spec.md §7): forms (designer, publish, link, versions, routing test,
responses), internal submit, requests (inbox / mine / all, detail, triage, conversation, withdraw) and the sign-in free
public form + tracking page. Rules in ``ews.ppm._intake`` (forms), ``_intake_requests`` (requests) and the pure
``_intake_forms``; capability ``intake``."""

from __future__ import annotations

from typing import Any, Optional

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from foundation.http import BaseController, delete, get, patch, post
from foundation.http.context_state import get_request_context
from foundation.http.response import PaginatedResponse, create_paginated_response

from ews.security import RequestScope, current_scope
from ews.shared import client_ip_hash, file_response

from .. import _access as access
from .. import _intake as intake
from .. import _intake_forms as forms
from .. import _intake_requests as requests
from .. import _settings
from ..schemas._intake_api import (
    PpmAcceptIn,
    PpmFormFillOut,
    PpmFormIn,
    PpmFormOut,
    PpmFormPatch,
    PpmFormVersionOut,
    PpmMergeIn,
    PpmRejectIn,
    PpmReplyIn,
    PpmRequestDetailOut,
    PpmRequestInfoIn,
    PpmRequestOut,
    PpmRequestStatusOut,
    PpmRoutingTestIn,
    PpmRoutingTestOut,
    PpmSubmissionIn,
    PpmSubmissionOut,
    PpmTrackingOut,
)


async def _scope(session: DBAsyncScopedSession) -> RequestScope:
    scope = await current_scope()
    await _settings.require_capability(session, scope, intake.CAPABILITY)
    return scope


def _idempotency_key() -> str | None:
    ctx = get_request_context()
    return ctx.req.headers.get('idempotency-key') if ctx is not None else None


async def _form(
    session: DBAsyncScopedSession, scope: RequestScope, form: Any
) -> PpmFormOut:
    return PpmFormOut(**await intake.form_out(session, scope, form))


def _submitted(
    s: requests.Submitted, settings: dict[str, Any] | None
) -> PpmSubmissionOut:
    return PpmSubmissionOut(
        request_id=str(s.task.id),
        code=s.task.code or '',
        status=s.request.status,
        tracking_url=requests.tracking_link(s.token) if s.token else None,
        confirmation=(settings or {}).get('confirmation'),
        redirect_url=(settings or {}).get('redirect_url'),
    )


class PpmFormController(BaseController):
    """Request forms: list, available, create, designer draft, publish / close / link, versions, routing test,
    fill + submit in the app, responses export."""

    api_prefix = '/api/v1/ppm/forms'
    tags = ('PPM intake',)

    @get('/', summary='Forms of the organization (project_id, status)')
    @db_context_session
    async def list_forms(
        self,
        session: DBAsyncScopedSession,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[PpmFormOut]:
        scope = await _scope(session)
        return [
            PpmFormOut(**f)
            for f in await intake.listing(
                session, scope, project_id=project_id, status=status
            )
        ]

    @get('/available', summary='Published forms I may submit')
    @db_context_session
    async def available(self, session: DBAsyncScopedSession) -> list[PpmFormOut]:
        scope = await _scope(session)
        return [PpmFormOut(**f) for f in await intake.available(session, scope)]

    @post(
        '/',
        summary='New form (blank, General request starter or copy)',
        status_code=201,
    )
    @db_context_session(auto_commit=True)
    async def create_form(
        self, data: PpmFormIn, session: DBAsyncScopedSession
    ) -> PpmFormOut:
        scope = await _scope(session)
        return await _form(
            session, scope, await intake.create(session, scope, data.as_dict())
        )

    @get('/{form_id}', summary='A form with its draft definition and settings')
    @db_context_session
    async def get_form(self, form_id: str, session: DBAsyncScopedSession) -> PpmFormOut:
        scope = await _scope(session)
        return await _form(
            session, scope, await intake.load_form(session, scope, form_id)
        )

    @patch(
        '/{form_id}', summary='Change the draft / settings on version (409 stale_form)'
    )
    @db_context_session(auto_commit=True)
    async def update_form(
        self, form_id: str, data: PpmFormPatch, session: DBAsyncScopedSession
    ) -> PpmFormOut:
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id, manage=True, lock=True)
        return await _form(
            session, scope, await intake.update(session, scope, form, data.as_dict())
        )

    @delete('/{form_id}', summary='Delete a form (its requests stay)', status_code=204)
    @db_context_session(auto_commit=True)
    async def delete_form(self, form_id: str, session: DBAsyncScopedSession) -> None:
        scope = await _scope(session)
        await intake.delete(
            session, scope, await intake.load_form(session, scope, form_id, manage=True)
        )

    @post(
        '/{form_id}/publish',
        summary='Publish the draft as a new version (400 invalid_form)',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def publish(self, form_id: str, session: DBAsyncScopedSession) -> PpmFormOut:
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id, manage=True, lock=True)
        return await _form(session, scope, await intake.publish(session, scope, form))

    @post('/{form_id}/close', summary='Stop submissions', status_code=200)
    @db_context_session(auto_commit=True)
    async def close(self, form_id: str, session: DBAsyncScopedSession) -> PpmFormOut:
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id, manage=True, lock=True)
        return await _form(session, scope, await intake.close(session, scope, form))

    @post(
        '/{form_id}/rotate-link',
        summary='New public link (the old one stops working)',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def rotate_link(
        self, form_id: str, session: DBAsyncScopedSession
    ) -> PpmFormOut:
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id, manage=True, lock=True)
        return await _form(
            session, scope, await intake.rotate_link(session, scope, form)
        )

    @get('/{form_id}/versions', summary='Published versions')
    @db_context_session
    async def versions(
        self, form_id: str, session: DBAsyncScopedSession
    ) -> list[PpmFormVersionOut]:
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id, manage=True)
        return [
            PpmFormVersionOut(**intake.version_out(v))
            for v in await intake.versions(session, form)
        ]

    @get(
        '/{form_id}/versions/{version}',
        summary='One published version with its definition',
    )
    @db_context_session
    async def version(
        self, form_id: str, version: int, session: DBAsyncScopedSession
    ) -> PpmFormVersionOut:
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id, manage=True)
        found = await intake.version_of(session, form.id, version)
        if found is None:
            from foundation.exceptions import NotFoundException

            raise NotFoundException(detail='version not found')
        return PpmFormVersionOut(**intake.version_out(found, definition=True))

    @post(
        '/{form_id}/routing/test',
        summary='Evaluate the draft on sample answers (no writes)',
        status_code=200,
    )
    @db_context_session
    async def routing_test(
        self, form_id: str, data: PpmRoutingTestIn, session: DBAsyncScopedSession
    ) -> PpmRoutingTestOut:
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id, manage=True)
        return PpmRoutingTestOut(**intake.test_routing(form, data.as_dict(), scope))

    @get('/{form_id}/published', summary='The published form to fill in the app')
    @db_context_session
    async def published(
        self, form_id: str, session: DBAsyncScopedSession
    ) -> PpmFormFillOut:
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id)
        return PpmFormFillOut(
            status=form.status, **await intake.published(session, scope, form)
        )

    @post(
        '/{form_id}/submissions',
        summary='Submit a request (Idempotency-Key header)',
        status_code=201,
    )
    @db_context_session(auto_commit=True)
    async def submit(
        self, form_id: str, data: PpmSubmissionIn, session: DBAsyncScopedSession
    ) -> PpmSubmissionOut:
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id)
        await intake.published(session, scope, form)
        requester = requests.Requester(
            ref=access.author(scope),
            name=scope.name,
            email=scope.email,
            is_member=True,
            locale=data.locale,
            user_id=scope.user_id,
        )
        done = await requests.submit(
            session,
            form,
            requester,
            data.answers,
            form_version=data.form_version,
            idempotency_key=_idempotency_key(),
        )
        return _submitted(done, form.settings)

    @get(
        '/{form_id}/responses/export',
        summary='Requests of the form with their answers (CSV / XLSX)',
    )
    @db_context_session
    async def export(
        self, form_id: str, session: DBAsyncScopedSession, format: str = 'csv'
    ) -> Any:  # noqa: A002
        scope = await _scope(session)
        form = await intake.load_form(session, scope, form_id)
        return file_response(
            *await intake.export_responses(session, scope, form, format)
        )


class PpmRequestController(BaseController):
    """Requests: list (inbox · mine · all), statuses, detail, triage, conversation, withdraw."""

    api_prefix = '/api/v1/ppm/requests'
    tags = ('PPM intake',)

    @get(
        '/',
        summary='Requests: tab inbox | mine | all, form_id, status (open | closed | <status>), q',
    )
    @db_context_session
    async def list_requests(
        self,
        session: DBAsyncScopedSession,
        tab: str = 'inbox',
        form_id: Optional[str] = None,
        status: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedResponse[PpmRequestOut]:
        scope = await current_scope()
        rows, total = await requests.listing(
            session,
            scope,
            tab=tab,
            form_id=form_id,
            status=status,
            q=q,
            limit=limit,
            offset=offset,
        )
        return create_paginated_response(
            [PpmRequestOut(**r) for r in rows], total=total
        )

    @get('/statuses', summary='Requester-facing status catalog (labels in the web)')
    async def statuses(self) -> list[PpmRequestStatusOut]:
        await current_scope()
        return [
            PpmRequestStatusOut(key=s, open=s in intake.OPEN_STATUSES)
            for s in requests.STATUSES
        ]

    @get('/{request_id}', summary='A request (requester view trimmed)')
    @db_context_session
    async def get_request(
        self, request_id: str, session: DBAsyncScopedSession
    ) -> PpmRequestDetailOut:
        scope = await _scope(session)
        loaded = await requests.load(session, scope, request_id)
        return PpmRequestDetailOut(**await requests.detail(session, scope, loaded))

    async def _after(
        self, session: DBAsyncScopedSession, scope: RequestScope, request_id: str
    ) -> PpmRequestDetailOut:
        loaded = await requests.load(session, scope, request_id)
        return PpmRequestDetailOut(**await requests.detail(session, scope, loaded))

    @post(
        '/{request_id}/accept',
        summary='Accept as item, in place or as project (409 already_decided)',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def accept(
        self, request_id: str, data: PpmAcceptIn, session: DBAsyncScopedSession
    ) -> PpmRequestDetailOut:
        scope = await _scope(session)
        await requests.accept(
            session,
            scope,
            await requests.load(session, scope, request_id, triage=True),
            data.as_dict(),
        )
        return await self._after(session, scope, request_id)

    @post('/{request_id}/reject', summary='Reject with a reason', status_code=200)
    @db_context_session(auto_commit=True)
    async def reject(
        self, request_id: str, data: PpmRejectIn, session: DBAsyncScopedSession
    ) -> PpmRequestDetailOut:
        scope = await _scope(session)
        await requests.reject(
            session,
            scope,
            await requests.load(session, scope, request_id, triage=True),
            data.reason,
        )
        return await self._after(session, scope, request_id)

    @post(
        '/{request_id}/merge', summary='Merge into an original request', status_code=200
    )
    @db_context_session(auto_commit=True)
    async def merge(
        self, request_id: str, data: PpmMergeIn, session: DBAsyncScopedSession
    ) -> PpmRequestDetailOut:
        scope = await _scope(session)
        loaded = await requests.load(session, scope, request_id, triage=True)
        await requests.merge(session, scope, loaded, data.original_id)
        return await self._after(session, scope, request_id)

    @post(
        '/{request_id}/request-info',
        summary='Ask the requester for more information',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def request_info(
        self, request_id: str, data: PpmRequestInfoIn, session: DBAsyncScopedSession
    ) -> PpmRequestDetailOut:
        scope = await _scope(session)
        loaded = await requests.load(session, scope, request_id, triage=True)
        await requests.request_info(session, scope, loaded, data.question)
        return await self._after(session, scope, request_id)

    @post(
        '/{request_id}/replies',
        summary='Reply to the requester, add an internal note, or answer as the requester',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def reply(
        self, request_id: str, data: PpmReplyIn, session: DBAsyncScopedSession
    ) -> PpmRequestDetailOut:
        scope = await _scope(session)
        loaded = await requests.load(session, scope, request_id)
        await requests.reply(
            session, scope, loaded, data.text, data.visibility or requests.REQUESTER
        )
        return await self._after(session, scope, request_id)

    @post(
        '/{request_id}/withdraw',
        summary='Withdraw my request (before a decision)',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def withdraw(
        self, request_id: str, session: DBAsyncScopedSession
    ) -> PpmRequestDetailOut:
        scope = await _scope(session)
        loaded = await requests.load(session, scope, request_id)
        if not loaded.requester:
            raise ClientException(
                detail='only the requester can withdraw',
                extra={'code': 'not_requester'},
            )
        await requests.withdraw(session, scope, loaded.request, loaded.task)
        return await self._after(session, scope, request_id)


class PpmPublicIntakeController(BaseController):
    """Sign-in free: a public form (definition, submit) and the requester's tracking page (token)."""

    api_prefix = '/api/v1/ppm'
    tags = ('PPM intake (public)',)

    @get(
        '/public-forms/{public_id}',
        summary='A public form to fill (closed forms: status only)',
    )
    @db_context_session
    async def public_form(
        self, public_id: str, session: DBAsyncScopedSession
    ) -> PpmFormFillOut:
        form = await requests.public_form(session, public_id)
        return PpmFormFillOut(**await requests.public_form_out(session, form))

    @post(
        '/public-forms/{public_id}/submissions',
        summary='Submit a public request (rate limited)',
        status_code=201,
    )
    @db_context_session(auto_commit=True)
    async def public_submit(
        self, public_id: str, data: PpmSubmissionIn, session: DBAsyncScopedSession
    ) -> PpmSubmissionOut:
        form = await requests.public_form(session, public_id)
        if (
            data.website
        ):  # honeypot: bots fill hidden fields — pretend success, store nothing
            return PpmSubmissionOut(
                request_id='',
                code='',
                status='submitted',
                confirmation=(form.settings or {}).get('confirmation'),
            )
        name = (data.requester_name or '').strip()
        email = (data.requester_email or '').strip().lower()
        errors = [
            *([{'field': 'requester_name', 'code': 'required'}] if not name else []),
            *(
                []
                if forms.EMAIL.match(email)
                else [
                    {
                        'field': 'requester_email',
                        'code': 'invalid_email' if email else 'required',
                    }
                ]
            ),
        ]
        if errors:
            raise ClientException(
                detail='some answers are missing or invalid',
                extra={'code': 'invalid_answers', 'errors': errors},
            )
        requester = requests.Requester(
            ref=None,
            name=name[:200],
            email=email[:320],
            is_member=False,
            locale=data.locale,
        )
        done = await requests.submit(
            session,
            form,
            requester,
            data.answers,
            form_version=data.form_version,
            idempotency_key=_idempotency_key(),
            ip_hash=client_ip_hash(),
        )
        return _submitted(done, form.settings)

    @get('/public-requests/{token}', summary='Tracking page of a request')
    @db_context_session
    async def tracking(
        self, token: str, session: DBAsyncScopedSession
    ) -> PpmTrackingOut:
        r, t = await requests.by_token(session, token)
        return PpmTrackingOut(**await requests.tracking_out(session, r, t))

    @post(
        '/public-requests/{token}/replies',
        summary='Reply as the requester',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def tracking_reply(
        self, token: str, data: PpmReplyIn, session: DBAsyncScopedSession
    ) -> PpmTrackingOut:
        r, t = await requests.by_token(session, token)
        await requests.public_reply(session, r, t, data.text)
        return PpmTrackingOut(**await requests.tracking_out(session, r, t))

    @post(
        '/public-requests/{token}/withdraw',
        summary='Withdraw the request (before a decision)',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def tracking_withdraw(
        self, token: str, session: DBAsyncScopedSession
    ) -> PpmTrackingOut:
        r, t = await requests.by_token(session, token)
        await requests.withdraw(session, None, r, t)
        return PpmTrackingOut(**await requests.tracking_out(session, r, t))
