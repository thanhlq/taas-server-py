"""Intake forms (taas-specs/ppm/intake/intake-spec.md, Ppm-1101…1117, ADR-47): organization or project forms with a
draft definition (``_intake_forms``), immutable published versions, close / reopen, public link (rotate), routing test
and responses export. Requests (submit, inbox, triage, tracking) live in ``_intake_requests``.

Permissions: ``ppm.form:manage`` on the organization (organization forms) or on ``project:<id>`` (project forms);
reading a form = being a member of its organization (project forms: reading the project). Capability ``intake``."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import PpmForm, PpmFormVersion, PpmRequest
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)
from sqlalchemy import func, select

from ews.security import RequestScope, is_allowed
from ews.shared import ConflictException, parse_uuid, random_id, to_xlsx

from . import _access as access
from . import _events as events
from . import _intake_forms as forms
from . import _settings as ppm_settings
from ._export import to_csv

CAPABILITY = 'intake'
FORM = 'ppm.form'
REQUEST = 'ppm.request'
OPEN_STATUSES = ('submitted', 'in_review', 'needs_info')
MAX_FORMS = 200
MAX_DRAFT_BYTES = 256_000
SETTINGS_KEYS = (
    'confirmation',
    'redirect_url',
    'triagers',
    'notify_requester',
    'routing_state',
)


def _error(detail: str, code: str, **extra: Any) -> ClientException:
    return ClientException(detail=detail, extra={'code': code, **extra})


def domains(scope: RequestScope, project_id: UUID | None) -> list[str]:
    return (
        access.project_domains(scope, project_id)
        if project_id
        else list(scope.org_domains())
    )


async def can_manage(scope: RequestScope, project_id: UUID | None) -> bool:
    return await is_allowed(scope, FORM, 'manage', domains(scope, project_id))


async def require_manage(scope: RequestScope, project_id: UUID | None) -> None:
    if not await can_manage(scope, project_id):
        raise PermissionDeniedException(detail=f'missing permission {FORM}:manage')


def blank() -> dict[str, Any]:
    return {
        'schema_version': 1,
        'title_template': '{form} — {requester}',
        'fields': [],
        'routing': [],
    }


async def load_form(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    form_id: object,
    *,
    manage: bool = False,
    lock: bool = False,
) -> PpmForm:
    """A form of the request's organization (404 outside it or on an unreadable project; 403 without manage)."""
    stmt = select(PpmForm).where(
        PpmForm.id == parse_uuid(form_id, 'form'),
        PpmForm.tenant_id == scope.tenant_id,
        PpmForm.organization_id == scope.organization_id,
        PpmForm.deleted_at.is_(None),
    )
    form = await session.scalar(stmt.with_for_update() if lock else stmt)
    if form is None:
        raise NotFoundException(detail='form not found')
    if form.project_id is not None:
        await access.load_project(session, scope, form.project_id)
    if manage:
        await require_manage(scope, form.project_id)
    return form


async def latest_version(
    session: DBAsyncScopedSession, form: PpmForm
) -> PpmFormVersion | None:
    if not form.current_version:
        return None
    return await session.scalar(
        select(PpmFormVersion).where(
            PpmFormVersion.form_id == form.id,
            PpmFormVersion.version == form.current_version,
        )
    )


async def version_of(
    session: DBAsyncScopedSession, form_id: UUID, version: int
) -> PpmFormVersion | None:
    return await session.scalar(
        select(PpmFormVersion).where(
            PpmFormVersion.form_id == form_id, PpmFormVersion.version == version
        )
    )


async def _project_names(
    session: DBAsyncScopedSession, ids: set[UUID]
) -> dict[UUID, str]:
    if not ids:
        return {}
    P = ews_models.Project
    rows = await session.execute(select(P.id, P.name).where(P.id.in_(ids)))
    return {r.id: r.name or '' for r in rows}


async def _counts(
    session: DBAsyncScopedSession, ids: list[UUID]
) -> dict[UUID, tuple[int, int, datetime | None]]:
    if not ids:
        return {}
    R = PpmRequest
    rows = await session.execute(
        select(
            R.form_id,
            func.count(),
            func.count().filter(R.status.in_(OPEN_STATUSES)),
            func.max(R.submitted_at),
        )
        .where(R.form_id.in_(ids))
        .group_by(R.form_id)
    )
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _public_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (settings or {}).items() if k != 'routing_state'}


async def forms_out(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    rows: list[PpmForm],
    *,
    full: bool = False,
) -> list[dict[str, Any]]:
    names = await _project_names(
        session, {i for f in rows for i in (f.project_id, f.queue_project_id) if i}
    )
    counts = await _counts(session, [f.id for f in rows])
    manage_cache: dict[UUID | None, bool] = {}
    out: list[dict[str, Any]] = []
    for f in rows:
        if f.project_id not in manage_cache:
            manage_cache[f.project_id] = await can_manage(scope, f.project_id)
        manage = manage_cache[f.project_id]
        total, open_, last = counts.get(f.id, (0, 0, None))
        row: dict[str, Any] = {
            'id': str(f.id),
            'project_id': str(f.project_id) if f.project_id else None,
            'project_name': names.get(f.project_id) if f.project_id else None,
            'name': f.name,
            'description': f.description,
            'audience': f.audience,
            'status': f.status,
            'current_version': f.current_version,
            'queue_project_id': str(f.queue_project_id) if f.queue_project_id else None,
            'queue_project_name': names.get(f.queue_project_id)
            if f.queue_project_id
            else None,
            'request_type_key': f.request_type_key,
            'owner': f.owner,
            'version': f.version,
            'total_requests': total,
            'open_requests': open_,
            'last_submitted_at': last,
            'updated_at': f.updated_at,
            'can_manage': manage,
            'public_id': f.public_id if manage and f.audience == 'public' else None,
        }
        if full:
            draft = f.draft or blank()
            row['draft'] = draft
            row['settings'] = _public_settings(f.settings) if manage else {}
            row['issues'] = (
                [i.as_dict() for i in forms.validate(draft)] if manage else []
            )
            latest = await latest_version(session, f)
            row['has_changes'] = latest is None or latest.definition != draft
        out.append(row)
    return out


async def form_out(
    session: DBAsyncScopedSession, scope: RequestScope, form: PpmForm
) -> dict[str, Any]:
    return (await forms_out(session, scope, [form], full=True))[0]


async def listing(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    project_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    await ppm_settings.require_capability(session, scope, CAPABILITY)
    stmt = select(PpmForm).where(
        PpmForm.tenant_id == scope.tenant_id,
        PpmForm.organization_id == scope.organization_id,
        PpmForm.deleted_at.is_(None),
    )
    if project_id:
        stmt = stmt.where(
            PpmForm.project_id == parse_uuid(project_id, 'project', not_found=False)
        )
    if status:
        stmt = stmt.where(PpmForm.status == status)
    rows = list(await session.scalars(stmt.order_by(PpmForm.name).limit(MAX_FORMS)))
    readable = await _readable_projects(
        session, scope, {f.project_id for f in rows if f.project_id}
    )
    return await forms_out(
        session,
        scope,
        [f for f in rows if f.project_id is None or f.project_id in readable],
    )


async def _readable_projects(
    session: DBAsyncScopedSession, scope: RequestScope, ids: set[UUID]
) -> set[UUID]:
    if not ids:
        return set()
    P = ews_models.Project
    rows = await session.scalars(
        select(P.id).where(P.id.in_(ids), await access.readable_projects(scope))
    )
    return set(rows)


async def _check_queue(
    session: DBAsyncScopedSession, scope: RequestScope, project_id: object
) -> UUID:
    project = await access.load_project(session, scope, project_id)
    if project.kind not in (None, 'project'):
        raise _error('the queue must be a project', 'invalid_queue')
    return project.id


def _clean_settings(value: Any, current: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error('settings must be an object', 'invalid_form')
    out = dict(current or {})
    for key in ('confirmation', 'redirect_url'):
        if key in value:
            text = str(value[key] or '').strip()
            if key == 'redirect_url' and text and not text.startswith('https://'):
                raise _error(
                    'the redirect URL must start with https://', 'invalid_form'
                )
            out[key] = text[:2000] or None
    if 'triagers' in value:
        refs = value['triagers'] or []
        if (
            not isinstance(refs, list)
            or len(refs) > 20
            or not all(isinstance(r, str) and '@' in r for r in refs)
        ):
            raise _error('triagers: a list of at most 20 e-mails', 'invalid_form')
        out['triagers'] = list(dict.fromkeys(r.strip().lower() for r in refs))
    if 'notify_requester' in value:
        out['notify_requester'] = bool(value['notify_requester'])
    return {k: v for k, v in out.items() if v is not None}


def _clean_draft(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error('draft must be an object', 'invalid_form')
    import json

    if len(json.dumps(value, default=str)) > MAX_DRAFT_BYTES:
        raise _error('the form is too large', 'invalid_form')
    return {**blank(), **value, 'schema_version': 1}


async def create(
    session: DBAsyncScopedSession, scope: RequestScope, data: dict[str, Any]
) -> PpmForm:
    """New form: ``{name, project_id?, audience?, starter: blank | general, copy_of?}``."""
    await ppm_settings.require_capability(session, scope, CAPABILITY)
    project_id = (
        (await access.load_project(session, scope, data['project_id'])).id
        if data.get('project_id')
        else None
    )
    await require_manage(scope, project_id)
    count = await session.scalar(
        select(func.count()).where(
            PpmForm.organization_id == scope.organization_id,
            PpmForm.deleted_at.is_(None),
        )
    )
    if (count or 0) >= MAX_FORMS:
        raise ConflictException(
            detail=f'at most {MAX_FORMS} forms', extra={'code': 'form_limit'}
        )
    name = str(data.get('name') or '').strip()[:200]
    if not name:
        raise _error('a form needs a name', 'invalid_form')
    audience = data.get('audience') or 'internal'
    if audience not in ('internal', 'public'):
        raise _error('audience must be internal or public', 'invalid_form')
    draft: dict[str, Any] = blank()
    settings: dict[str, Any] = {'notify_requester': True}
    queue = project_id
    request_type = None
    if data.get('copy_of'):
        source = await load_form(session, scope, data['copy_of'])
        draft, settings = (
            copy.deepcopy(source.draft or blank()),
            _public_settings(source.settings),
        )
        queue, request_type = source.queue_project_id or queue, source.request_type_key
        audience = data.get('audience') or source.audience
    elif data.get('starter') == 'general':
        draft = copy.deepcopy(forms.STARTER)
    form = PpmForm(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        project_id=project_id,
        name=name,
        description=(str(data.get('description') or '').strip() or None),
        audience=audience,
        status='draft',
        current_version=0,
        draft=draft,
        queue_project_id=queue,
        request_type_key=request_type,
        settings=settings,
        owner=access.author(scope),
        owner_user_id=scope.user_id,
        version=1,
    )
    session.add(form)
    await session.flush()
    await _emit(session, scope, 'ppm.form.created', form)
    return form


async def update(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    form: PpmForm,
    data: dict[str, Any],
) -> PpmForm:
    """Draft and settings on ``version`` (409 ``stale_form``); publishing is separate."""
    if int(data.get('version') or 0) != form.version:
        raise ConflictException(
            detail='the form changed meanwhile, reload it', extra={'code': 'stale_form'}
        )
    if 'name' in data:
        name = str(data['name'] or '').strip()[:200]
        if not name:
            raise _error('a form needs a name', 'invalid_form')
        form.name = name
    if 'description' in data:
        form.description = str(data['description'] or '').strip() or None
    if 'audience' in data:
        if data['audience'] not in ('internal', 'public'):
            raise _error('audience must be internal or public', 'invalid_form')
        form.audience = data['audience']
        if (
            form.audience == 'public'
            and form.status == 'published'
            and not form.public_id
        ):
            form.public_id = random_id()
    if 'draft' in data:
        form.draft = _clean_draft(data['draft'])
    if 'queue_project_id' in data:
        form.queue_project_id = (
            await _check_queue(session, scope, data['queue_project_id'])
            if data['queue_project_id']
            else None
        )
    if 'request_type_key' in data:
        form.request_type_key = str(data['request_type_key'] or '').strip()[:64] or None
    if 'settings' in data:
        form.settings = _clean_settings(data['settings'], form.settings)
    form.version += 1
    await session.flush()
    await _emit(session, scope, 'ppm.form.updated', form)
    return form


async def publish(
    session: DBAsyncScopedSession, scope: RequestScope, form: PpmForm
) -> PpmForm:
    """A new immutable version when the draft changed (400 ``invalid_form`` + ``issues``); opens the form."""
    draft = form.draft or blank()
    issues = [i.as_dict() for i in forms.validate(draft)]
    if form.queue_project_id is None:
        issues.append(
            {
                'path': 'queue_project_id',
                'message': 'choose the project where requests land',
            }
        )
    if issues:
        raise _error('the form is not ready to publish', 'invalid_form', issues=issues)
    latest = await latest_version(session, form)
    if latest is None or latest.definition != draft:
        form.current_version += 1
        session.add(
            PpmFormVersion(
                tenant_id=form.tenant_id,
                form_id=form.id,
                version=form.current_version,
                definition=copy.deepcopy(draft),
                published_by=access.author(scope),
                published_at=datetime.now(UTC),
            )
        )
    form.status = 'published'
    if form.audience == 'public' and not form.public_id:
        form.public_id = random_id()
    form.version += 1
    await session.flush()
    await _emit(session, scope, 'ppm.form.published', form)
    return form


async def close(
    session: DBAsyncScopedSession, scope: RequestScope, form: PpmForm
) -> PpmForm:
    if form.status != 'closed':
        form.status = 'closed'
        form.version += 1
        await session.flush()
        await _emit(session, scope, 'ppm.form.closed', form)
    return form


async def rotate_link(
    session: DBAsyncScopedSession, scope: RequestScope, form: PpmForm
) -> PpmForm:
    if form.audience != 'public':
        raise _error('only a public form has a link', 'not_public')
    form.public_id = random_id()
    form.version += 1
    await session.flush()
    await _emit(session, scope, 'ppm.form.updated', form, data={'link_rotated': True})
    return form


async def delete(
    session: DBAsyncScopedSession, scope: RequestScope, form: PpmForm
) -> None:
    """Soft delete: the form disappears, its requests stay."""
    form.deleted_at = datetime.now(UTC)
    form.status = 'closed'
    form.public_id = None
    await session.flush()
    await _emit(session, scope, 'ppm.form.deleted', form)


async def versions(
    session: DBAsyncScopedSession, form: PpmForm
) -> list[PpmFormVersion]:
    return list(
        await session.scalars(
            select(PpmFormVersion)
            .where(PpmFormVersion.form_id == form.id)
            .order_by(PpmFormVersion.version.desc())
        )
    )


def version_out(v: PpmFormVersion, *, definition: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        'version': v.version,
        'published_by': v.published_by,
        'published_at': v.published_at,
    }
    if definition:
        out['definition'] = v.definition
    return out


async def available(
    session: DBAsyncScopedSession, scope: RequestScope
) -> list[dict[str, Any]]:
    """Published forms of the organization the caller may submit (Ppm-1126)."""
    await ppm_settings.require_capability(session, scope, CAPABILITY)
    rows = list(
        await session.scalars(
            select(PpmForm)
            .where(
                PpmForm.tenant_id == scope.tenant_id,
                PpmForm.organization_id == scope.organization_id,
                PpmForm.status == 'published',
                PpmForm.deleted_at.is_(None),
            )
            .order_by(PpmForm.name)
        )
    )
    readable = await _readable_projects(
        session, scope, {f.project_id for f in rows if f.project_id}
    )
    out = []
    for f in rows:
        if f.project_id and f.project_id not in readable:
            continue
        if await is_allowed(scope, REQUEST, 'create', domains(scope, f.project_id)):
            out.append(f)
    return await forms_out(session, scope, out)


def public_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """What a requester's browser needs: fields (logic included), no routing, no mapping."""
    fields = [
        {k: v for k, v in f.items() if k != 'map'}
        for f in definition.get('fields') or []
        if isinstance(f, dict)
    ]
    return {'schema_version': definition.get('schema_version', 1), 'fields': fields}


async def published(
    session: DBAsyncScopedSession, scope: RequestScope, form: PpmForm
) -> dict[str, Any]:
    """The published definition to fill in the app (``ppm.request:create``)."""
    if not await is_allowed(scope, REQUEST, 'create', domains(scope, form.project_id)):
        raise PermissionDeniedException(detail=f'missing permission {REQUEST}:create')
    latest = await latest_version(session, form)
    if form.status != 'published' or latest is None:
        raise ConflictException(
            detail='this form does not accept requests', extra={'code': 'form_closed'}
        )
    return {
        'id': str(form.id),
        'name': form.name,
        'description': form.description,
        'version': latest.version,
        'definition': public_definition(latest.definition),
        'confirmation': (form.settings or {}).get('confirmation'),
    }


def test_routing(
    form: PpmForm, data: dict[str, Any], scope: RequestScope
) -> dict[str, Any]:
    """Routing test on sample answers (no writes): cleaned answers + errors, mapped item fields, title, matched
    actions and the trace (Ppm-1152)."""
    definition = form.draft or blank()
    answers, errors = forms.clean_answers(
        definition, data.get('answers') or {}, member=access.author(scope)
    )
    email = str(data.get('requester_email') or access.author(scope) or '')
    requester = forms.requester_facts(email, bool(data.get('is_member', True)))
    actions, trace = forms.route(definition, answers, requester)
    return {
        'answers': answers,
        'errors': errors,
        'item': forms.mapped(definition, answers),
        'title': forms.title(
            definition, answers, form=form.name, requester=email or 'Requester', n=1
        ),
        'actions': actions,
        'trace': trace,
    }


async def export_responses(
    session: DBAsyncScopedSession, scope: RequestScope, form: PpmForm, fmt: str
) -> tuple[bytes, str, str]:
    """Requests of the form with the answers as columns (labels of the latest version), CSV or XLSX (Ppm-1109)."""
    if fmt not in ('csv', 'xlsx'):
        raise _error('format must be csv or xlsx', 'invalid_format')
    queue = form.queue_project_id or form.project_id
    if queue is None or not await is_allowed(
        scope, REQUEST, 'triage', access.project_domains(scope, queue)
    ):
        await require_manage(scope, form.project_id)
    latest = await latest_version(session, form)
    fields = [
        f
        for f in ((latest.definition if latest else form.draft) or {}).get('fields')
        or []
        if isinstance(f, dict) and f.get('type') in forms.INPUT_TYPES
    ]
    T = ews_models.Task
    rows = await session.execute(
        select(PpmRequest, T.code, T.name)
        .join(T, T.id == PpmRequest.task_id)
        .where(PpmRequest.form_id == form.id)
        .order_by(PpmRequest.submitted_at.desc())
        .limit(10_000)
    )
    header = [
        'Code',
        'Title',
        'Submitted',
        'Status',
        'Requester',
        'E-mail',
        *[str(f.get('label') or f['key']) for f in fields],
    ]
    body = [
        [
            code,
            name,
            r.submitted_at,
            r.status,
            r.requester_name or r.requester_ref or '',
            r.requester_email or r.requester_ref or '',
            *[
                forms.text_of(f, (r.answers or {}).get(f['key']))
                if f['key'] in (r.answers or {})
                else ''
                for f in fields
            ],
        ]
        for r, code, name in rows
    ]
    stamp = datetime.now(UTC).date().isoformat()
    file_name = f'requests-{stamp}.{fmt}'
    if fmt == 'csv':
        return (
            to_csv(header, body).encode('utf-8'),
            'text/csv; charset=utf-8',
            file_name,
        )
    media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    return to_xlsx(header, body, sheet='requests'), media, file_name


async def _emit(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    topic: str,
    form: PpmForm,
    data: dict[str, Any] | None = None,
) -> None:
    await events.emit(
        session,
        scope,
        topic,
        'form',
        form.id,
        project_id=form.project_id,
        data={
            'form_id': str(form.id),
            'name': form.name,
            'version': form.current_version,
            'audience': form.audience,
            'scope': 'project' if form.project_id else 'organization',
            **(data or {}),
        },
    )
