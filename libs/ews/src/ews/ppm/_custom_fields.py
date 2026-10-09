"""Custom fields (taas-specs/ppm/work-model/work-model-spec.md Ppm-0850…0857, §5.3): typed definitions of the
organization or of a project, **bindings** that decide where a field shows (an item type everywhere, an item type in
one project, every item of a project) and one typed value per item and field.

- The type never changes; options keep stable ids (renaming never touches values, Ppm-0855).
- Writes are validated on the server → 400 with ``extra.issues`` ``{key: message}`` (Ppm-0853).
- Values travel as ``{key: value}``: text / url → str · number → decimal string · money → ``{amount, currency}`` ·
  date → ``YYYY-MM-DD`` (ISO date-time with ``with_time``) · select → option id · multi-select → ids · user → ref
  (list with ``multi``) · checkbox → bool.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import PpmCustomField, PpmCustomFieldBinding, PpmCustomFieldValue
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)
from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select

from ews.authz import EwsResources
from ews.security import RequestScope, is_allowed
from ews.shared import ConflictException, parse_uuid, slugify

from . import _events as events

CUSTOM_FIELD = EwsResources.CUSTOM_FIELD.value
TYPES = (
    'text',
    'textarea',
    'number',
    'money',
    'date',
    'select',
    'multi_select',
    'user',
    'url',
    'checkbox',
)
REQUIRED = ('never', 'on_create', 'before_done')
MAX_ORG_FIELDS = 200
MAX_BOUND = 50
MAX_OPTIONS = 500
_CURRENCY = re.compile(r'^[A-Z]{3,8}$')
_URL = re.compile(r'^https?://[^\s]+$', re.IGNORECASE)

Field = PpmCustomField
Binding = PpmCustomFieldBinding
Value = PpmCustomFieldValue


def _issue(issues: dict[str, str]) -> ClientException:
    return ClientException(
        detail='invalid custom field values',
        extra={'code': 'invalid_fields', 'issues': issues},
    )


# --- definitions -----------------------------------------------------------------------------------


async def can_manage(
    session: DBAsyncScopedSession, scope: RequestScope, project_id: UUID | None
) -> bool:
    if project_id is None:
        return await is_allowed(scope, CUSTOM_FIELD, 'manage', scope.org_domains())
    from ._access import PROJECTS

    return await PROJECTS.allowed(scope, project_id, CUSTOM_FIELD, 'manage')


async def require_manage(
    session: DBAsyncScopedSession, scope: RequestScope, project_id: UUID | None
) -> None:
    if not await can_manage(session, scope, project_id):
        raise PermissionDeniedException(
            detail=f'missing permission {CUSTOM_FIELD}:manage'
        )


def _option_id() -> str:
    return secrets.token_hex(4)


def clean_config(
    type_: str, config: Any, previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validated ``config`` for a field type; options keep their ids (new ones get one)."""
    raw = config if isinstance(config, dict) else {}
    out: dict[str, Any] = {}
    if type_ in ('select', 'multi_select'):
        known = {o['id']: o for o in (previous or {}).get('options', [])}
        options: list[dict[str, Any]] = []
        for i, o in enumerate(raw.get('options') or []):
            if not isinstance(o, dict) or not str(o.get('label') or '').strip():
                continue
            oid = (
                str(o.get('id') or '')
                if str(o.get('id') or '') in known
                else _option_id()
            )
            options.append(
                {
                    'id': oid,
                    'label': str(o['label']).strip()[:120],
                    'color': (str(o.get('color')) if o.get('color') else None),
                    'order': i,
                    'archived': bool(o.get('archived')),
                }
            )
        # options removed by the caller stay, archived (their values keep working)
        for oid, o in known.items():
            if all(x['id'] != oid for x in options):
                options.append({**o, 'archived': True, 'order': len(options)})
        if len(options) > MAX_OPTIONS:
            raise ConflictException(
                detail=f'at most {MAX_OPTIONS} options', extra={'code': 'limit'}
            )
        out['options'] = options
    if type_ in ('number', 'money'):
        decimals = raw.get('decimals')
        if decimals is not None:
            out['decimals'] = max(0, min(10, int(decimals)))
        for k in ('min', 'max'):
            if raw.get(k) is not None:
                out[k] = str(_decimal(raw[k], k))
    if type_ == 'number':
        if raw.get('unit'):
            out['unit'] = str(raw['unit'])[:16]
        out['percent'] = bool(raw.get('percent'))
    if type_ == 'money':
        if raw.get('currency'):
            cur = str(raw['currency']).upper()
            if not _CURRENCY.match(cur):
                raise ClientException(detail=f'invalid currency {cur!r}')
            out['currency'] = cur
        allowed = [
            str(c).upper()
            for c in raw.get('currencies') or []
            if _CURRENCY.match(str(c).upper())
        ]
        if allowed:
            out['currencies'] = allowed
    if type_ in ('text', 'textarea') and raw.get('max_length'):
        out['max_length'] = max(1, min(10000, int(raw['max_length'])))
    if type_ == 'user':
        out['multi'] = bool(raw.get('multi'))
    if type_ == 'date':
        out['with_time'] = bool(raw.get('with_time'))
    return out


def _decimal(value: Any, key: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except InvalidOperation, ValueError:
        raise ClientException(detail=f'{key} must be a number') from None
    if not d.is_finite():
        raise ClientException(detail=f'{key} must be a number')
    return d


async def definitions(
    session: DBAsyncScopedSession,
    organization_id: UUID,
    project_id: UUID | None = None,
    *,
    include_archived: bool = False,
) -> list[PpmCustomField]:
    """Organization fields + (with ``project_id``) the project's own fields."""
    scope_filter: ColumnElement[bool] = Field.project_id.is_(None)
    if project_id is not None:
        scope_filter = or_(Field.project_id.is_(None), Field.project_id == project_id)
    q = select(Field).where(Field.organization_id == organization_id, scope_filter)
    if not include_archived:
        q = q.where(Field.archived_at.is_(None))
    return list(
        (
            await session.scalars(
                q.order_by(Field.project_id.nulls_first(), Field.position, Field.label)
            )
        ).all()
    )


async def get(
    session: DBAsyncScopedSession, scope: RequestScope, field_id: Any
) -> PpmCustomField:
    row = await session.get(Field, parse_uuid(field_id, 'custom field'))
    if row is None or row.organization_id != scope.organization_id:
        raise NotFoundException(detail='custom field not found')
    return row


async def create(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    label: str,
    type_: str,
    config: Any = None,
    description: str | None = None,
    project_id: UUID | None = None,
) -> PpmCustomField:
    await require_manage(session, scope, project_id)
    label = (label or '').strip()[:200]
    if not label:
        raise ClientException(detail='a field needs a label')
    if type_ not in TYPES:
        raise ClientException(detail=f'unknown field type {type_!r}')
    existing = await definitions(session, scope.organization_id, project_id)
    if (
        project_id is None
        and sum(1 for f in existing if f.project_id is None) >= MAX_ORG_FIELDS
    ):
        raise ConflictException(
            detail=f'at most {MAX_ORG_FIELDS} fields per organization',
            extra={'code': 'limit'},
        )
    taken = {f.key for f in existing}
    base = slugify(label, 56).replace('-', '_') or 'field'
    key, n = base, 2
    while key in taken:
        key, n = f'{base}_{n}', n + 1
    row = Field(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        project_id=project_id,
        key=key,
        label=label,
        type=type_,
        description=(description or None),
        config=clean_config(type_, config),
        position=max((f.position for f in existing), default=0.0) + 1,
    )
    session.add(row)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.custom_field.created',
        'custom_field',
        row.id,
        project_id=project_id,
        data={'key': key, 'type': type_},
    )
    return row


async def update(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    row: PpmCustomField,
    data: dict[str, Any],
) -> PpmCustomField:
    await require_manage(session, scope, row.project_id)
    if 'type' in data and data['type'] != row.type:
        raise ConflictException(
            detail='the type of a field never changes: archive it and create a new one',
            extra={'code': 'type_locked'},
        )
    before = {'label': row.label, 'description': row.description, 'config': row.config}
    if 'label' in data:
        label = (data['label'] or '').strip()[:200]
        if not label:
            raise ClientException(detail='a field needs a label')
        row.label = label
    if 'description' in data:
        row.description = data['description'] or None
    if 'config' in data:
        row.config = clean_config(row.type, data['config'], row.config)
    if 'position' in data and data['position'] is not None:
        row.position = float(data['position'])
    await session.flush()
    changes = events.diff(
        before,
        {'label': row.label, 'description': row.description, 'config': row.config},
    )
    if changes:
        await events.emit(
            session,
            scope,
            'ppm.custom_field.updated',
            'custom_field',
            row.id,
            project_id=row.project_id,
            changes=changes,
            data={'key': row.key},
        )
    return row


async def set_archived(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    row: PpmCustomField,
    archived: bool,
) -> PpmCustomField:
    await require_manage(session, scope, row.project_id)
    if archived == (row.archived_at is not None):
        return row
    row.archived_at = datetime.now(UTC) if archived else None
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.custom_field.archived' if archived else 'ppm.custom_field.restored',
        'custom_field',
        row.id,
        project_id=row.project_id,
        data={'key': row.key},
    )
    return row


def field_out(row: PpmCustomField) -> dict[str, Any]:
    return {
        'id': str(row.id),
        'key': row.key,
        'label': row.label,
        'type': row.type,
        'description': row.description,
        'config': row.config or {},
        'project_id': str(row.project_id) if row.project_id else None,
        'archived': row.archived_at is not None,
    }


# --- bindings --------------------------------------------------------------------------------------


@dataclass(slots=True)
class BindingIn:
    field_id: Any
    item_type_key: str | None = None
    required: str = 'never'
    default_value: Any = None
    section: str | None = None
    on_create_form: bool = False
    on_card: bool = False


def binding_out(row: PpmCustomFieldBinding) -> dict[str, Any]:
    return {
        'field_id': str(row.field_id),
        'item_type_key': row.item_type_key,
        'project_id': str(row.project_id) if row.project_id else None,
        'required': row.required,
        'default_value': row.default_value,
        'section': row.section,
        'position': row.position,
        'on_create_form': row.on_create_form,
        'on_card': row.on_card,
    }


async def bindings_of(
    session: DBAsyncScopedSession, organization_id: UUID, project_id: UUID | None = None
) -> list[PpmCustomFieldBinding]:
    """Organization-wide item type bindings + (with ``project_id``) the project's bindings."""
    target: ColumnElement[bool] = Binding.project_id.is_(None)
    if project_id is not None:
        target = or_(Binding.project_id.is_(None), Binding.project_id == project_id)
    return list(
        (
            await session.scalars(
                select(Binding)
                .where(Binding.organization_id == organization_id, target)
                .order_by(Binding.position)
            )
        ).all()
    )


async def replace_bindings(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    project_id: UUID | None,
    item_type_key: str | None,
    items: list[BindingIn],
) -> list[PpmCustomFieldBinding]:
    """Replace the bindings of one target: an item type organization-wide (``project_id`` None), or a project (each
    binding names an item type or none = every item)."""
    await require_manage(session, scope, project_id)
    usable = {
        f.id: f for f in await definitions(session, scope.organization_id, project_id)
    }
    if project_id is None and item_type_key is None:
        raise ClientException(detail='bindings need an item type or a project')
    rows: list[PpmCustomFieldBinding] = []
    per_type: dict[str | None, int] = {}
    for i, b in enumerate(items):
        fid = parse_uuid(b.field_id, 'custom field')
        field = usable.get(fid)
        if field is None:
            raise ClientException(detail=f'unknown field {b.field_id}')
        if b.required not in REQUIRED:
            raise ClientException(detail=f'unknown required rule {b.required!r}')
        key = item_type_key if project_id is None else b.item_type_key
        per_type[key] = per_type.get(key, 0) + 1
        if per_type[key] > MAX_BOUND:
            raise ConflictException(
                detail=f'at most {MAX_BOUND} fields per item type',
                extra={'code': 'limit'},
            )
        default = None
        if b.default_value is not None:
            default = to_wire(field, _parse(field, b.default_value, None, {}))
        rows.append(
            Binding(
                tenant_id=scope.tenant_id,
                organization_id=scope.organization_id,
                field_id=fid,
                item_type_key=key,
                project_id=project_id,
                required=b.required,
                default_value=default,
                section=(b.section or None),
                position=float(i),
                on_create_form=b.on_create_form,
                on_card=b.on_card,
            )
        )
    target = (
        Binding.project_id == project_id
        if project_id is not None
        else and_(Binding.project_id.is_(None), Binding.item_type_key == item_type_key)
    )
    await session.execute(
        delete(Binding).where(Binding.organization_id == scope.organization_id, target)
    )
    session.add_all(rows)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.custom_field.bindings_changed',
        'custom_field',
        project_id or item_type_key,
        project_id=project_id,
        data={
            'item_type_key': item_type_key,
            'fields': [str(r.field_id) for r in rows],
        },
    )
    return rows


@dataclass(slots=True)
class Bound:
    field: PpmCustomField
    binding: PpmCustomFieldBinding


async def bound_fields(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    item_type_key: str | None,
) -> list[Bound]:
    """Fields shown on an item of ``item_type_key`` in ``project``; the most specific binding wins (project + type ›
    project › organization-wide type)."""
    if project.organization_id is None:
        return []
    fields = {
        f.id: f for f in await definitions(session, project.organization_id, project.id)
    }
    rank: dict[UUID, tuple[int, PpmCustomFieldBinding]] = {}
    for b in await bindings_of(session, project.organization_id, project.id):
        if b.field_id not in fields:
            continue
        if (
            b.project_id == project.id
            and b.item_type_key == item_type_key
            and item_type_key
        ):
            level = 3
        elif b.project_id == project.id and b.item_type_key is None:
            level = 2
        elif (
            b.project_id is None and b.item_type_key == item_type_key and item_type_key
        ):
            level = 1
        else:
            continue
        if b.field_id not in rank or rank[b.field_id][0] < level:
            rank[b.field_id] = (level, b)
    out = [Bound(fields[fid], b) for fid, (_, b) in rank.items()]
    out.sort(key=lambda x: (x.binding.section or '', x.binding.position))
    return out


# --- values ----------------------------------------------------------------------------------------


def _options(field: PpmCustomField) -> dict[str, dict[str, Any]]:
    return {o['id']: o for o in (field.config or {}).get('options', [])}


def _parse(
    field: PpmCustomField, value: Any, current: Any, ctx: dict[str, Any]
) -> dict[str, Any]:
    """Typed columns for a wire value (raises ``ValueError`` with a message)."""
    cfg = field.config or {}
    t = field.type
    if t in ('text', 'textarea'):
        text = str(value).strip()
        limit = cfg.get('max_length') or (10000 if t == 'textarea' else 500)
        if len(text) > limit:
            raise ValueError(f'at most {limit} characters')
        return {'value_text': text}
    if t == 'url':
        text = str(value).strip()
        if not _URL.match(text) or len(text) > 2048:
            raise ValueError('must be an http(s) URL')
        return {'value_text': text}
    if t in ('number', 'money'):
        raw = value.get('amount') if t == 'money' and isinstance(value, dict) else value
        if isinstance(raw, bool):
            raise ValueError('must be a number')
        try:
            number = Decimal(str(raw))
        except InvalidOperation, ValueError:
            raise ValueError('must be a number') from None
        if not number.is_finite():
            raise ValueError('must be a number')
        if cfg.get('decimals') is not None:
            number = number.quantize(Decimal(1).scaleb(-int(cfg['decimals'])))
        if cfg.get('min') is not None and number < Decimal(cfg['min']):
            raise ValueError(f'at least {cfg["min"]}')
        if cfg.get('max') is not None and number > Decimal(cfg['max']):
            raise ValueError(f'at most {cfg["max"]}')
        out: dict[str, Any] = {'value_number': number}
        if t == 'money':
            currency = cfg.get('currency') or (
                value.get('currency') if isinstance(value, dict) else None
            )
            currency = str(currency or '').upper()
            if not _CURRENCY.match(currency):
                raise ValueError('needs a currency')
            if cfg.get('currencies') and currency not in cfg['currencies']:
                raise ValueError(
                    f'currency must be one of {", ".join(cfg["currencies"])}'
                )
            out['value_currency'] = currency
        return out
    if t == 'date':
        text = str(value).strip()
        try:
            if cfg.get('with_time'):
                at = datetime.fromisoformat(text.replace('Z', '+00:00'))
                return {
                    'value_at': at if at.tzinfo else at.replace(tzinfo=UTC),
                    'value_date': at.date(),
                }
            return {'value_date': date.fromisoformat(text[:10])}
        except ValueError:
            raise ValueError('must be a date (YYYY-MM-DD)') from None
    if t in ('select', 'multi_select'):
        options = _options(field)
        ids = value if isinstance(value, list) else [value]
        ids = [str(i) for i in ids if i not in (None, '')]
        if t == 'select' and len(ids) != 1:
            raise ValueError('pick one option')
        kept = (
            set(current or [])
            if isinstance(current, list)
            else ({current} if current else set())
        )
        for i in ids:
            o = options.get(i)
            if o is None or (o.get('archived') and i not in kept):
                raise ValueError(f'unknown option {i}')
        return {'value_refs': list(dict.fromkeys(ids))}
    if t == 'user':
        refs = value if isinstance(value, list) else [value]
        refs = [str(r).strip().lower() for r in refs if str(r or '').strip()]
        if not cfg.get('multi') and len(refs) != 1:
            raise ValueError('pick one person')
        allowed = ctx.get('readers')
        if allowed is not None:
            outsiders = [r for r in refs if r not in allowed]
            if outsiders:
                raise ValueError(f'not a project member: {", ".join(outsiders)}')
        return {'value_refs': list(dict.fromkeys(refs))}
    if t == 'checkbox':
        if not isinstance(value, bool):
            raise ValueError('must be true or false')
        return {'value_bool': value}
    raise ValueError(f'unknown type {t}')


def to_wire(field: PpmCustomField, cols: dict[str, Any] | PpmCustomFieldValue) -> Any:
    get = cols.get if isinstance(cols, dict) else (lambda k: getattr(cols, k))
    t = field.type
    if t in ('text', 'textarea', 'url'):
        return get('value_text')
    if t == 'number':
        n = get('value_number')
        return None if n is None else format(n.normalize(), 'f')
    if t == 'money':
        n = get('value_number')
        if n is None:
            return None
        decimals = (field.config or {}).get('decimals')
        amount = (
            n.quantize(Decimal(1).scaleb(-int(decimals)))
            if decimals is not None
            else n.normalize()
        )
        return {'amount': format(amount, 'f'), 'currency': get('value_currency')}
    if t == 'date':
        if (field.config or {}).get('with_time') and get('value_at'):
            return get('value_at').isoformat()
        d = get('value_date')
        return d.isoformat() if d else None
    if t == 'select':
        refs = get('value_refs') or []
        return refs[0] if refs else None
    if t == 'multi_select':
        return list(get('value_refs') or [])
    if t == 'user':
        refs = list(get('value_refs') or [])
        return (
            refs if (field.config or {}).get('multi') else (refs[0] if refs else None)
        )
    if t == 'checkbox':
        return get('value_bool')
    return None


async def values_of(
    session: DBAsyncScopedSession, organization_id: UUID | None, task_ids: list[UUID]
) -> dict[UUID, dict[str, Any]]:
    """``{task_id: {field key: wire value}}`` for every stored value (bound or hidden)."""
    if not task_ids or organization_id is None:
        return {}
    rows = await session.execute(
        select(Value, Field)
        .join(Field, Field.id == Value.field_id)
        .where(Value.task_id.in_(task_ids), Field.organization_id == organization_id)
    )
    out: dict[UUID, dict[str, Any]] = {}
    for value, field in rows.all():
        wire = to_wire(field, value)
        if wire is not None and wire != []:
            out.setdefault(value.task_id, {})[field.key] = wire
    return out


async def set_values(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    project: ews_models.Project,
    task: ews_models.Task,
    patch: dict[str, Any],
    *,
    creating: bool = False,
) -> dict[str, dict[str, Any]]:
    """Write ``{key: value | None}`` for fields bound to the item (400 ``invalid_fields`` with ``issues``); on create,
    defaults fill the gaps and ``on_create`` fields are required. Returns ``changes`` ``{cf_<key>: {from, to}}``."""
    bound = {
        b.field.key: b
        for b in await bound_fields(session, project, task.work_item_type)
    }
    if not bound and not patch:
        return {}
    issues: dict[str, str] = {}
    current_rows = {
        v.field_id: v
        for v in (
            await session.scalars(select(Value).where(Value.task_id == task.id))
        ).all()
    }
    needs_readers = any(bound[k].field.type == 'user' for k in patch if k in bound)
    ctx: dict[str, Any] = {}
    if needs_readers:
        from ._members import readers

        ctx['readers'] = await readers(session, scope, project)
    values = dict(patch)
    if creating:
        for key, b in bound.items():
            if key not in values and b.binding.default_value is not None:
                values[key] = b.binding.default_value
    changes: dict[str, dict[str, Any]] = {}
    for key, value in values.items():
        b = bound.get(key)
        if b is None:
            issues[key] = 'not a field of this item'
            continue
        field = b.field
        row = current_rows.get(field.id)
        old = to_wire(field, row) if row is not None else None
        if value is None or value == '' or value == []:
            if row is not None:
                await session.delete(row)
                changes[f'cf_{key}'] = {'from': old, 'to': None}
            continue
        try:
            cols = _parse(field, value, old, ctx)
        except ValueError as err:
            issues[key] = str(err)
            continue
        if row is None:
            row = Value(tenant_id=project.tenant_id, task_id=task.id, field_id=field.id)
            session.add(row)
        for col in (
            'value_text',
            'value_number',
            'value_currency',
            'value_date',
            'value_at',
            'value_bool',
            'value_refs',
        ):
            setattr(row, col, cols.get(col))
        row.updated_by = (scope.email or str(scope.user_id)) if scope else None
        new = to_wire(field, cols)
        if new != old:
            changes[f'cf_{key}'] = {'from': old, 'to': new}
    if creating:
        for key, b in bound.items():
            if (
                b.binding.required == 'on_create'
                and values.get(key) in (None, '', [])
                and key not in issues
            ):
                issues[key] = 'required'
    if issues:
        raise _issue(issues)
    await session.flush()
    return changes


async def missing_before_done(
    session: DBAsyncScopedSession, task: ews_models.Task
) -> list[str]:
    """Keys of ``before_done`` fields (and ``on_create`` ones) without a value."""
    project = (
        await session.get(ews_models.Project, task.project_id)
        if task.project_id
        else None
    )
    if project is None:
        return []
    required = [
        b
        for b in await bound_fields(session, project, task.work_item_type)
        if b.binding.required in ('on_create', 'before_done')
    ]
    if not required:
        return []
    have = set(
        (
            await session.scalars(
                select(Value.field_id).where(
                    Value.task_id == task.id,
                    Value.field_id.in_([b.field.id for b in required]),
                )
            )
        ).all()
    )
    return [b.field.key for b in required if b.field.id not in have]


# --- filters (§5.3) --------------------------------------------------------------------------------

_SUFFIXES = (
    '_contains',
    '_empty',
    '_gte',
    '_lte',
    '_from',
    '_to',
    '_all',
    '_not',
    '_currency',
)


def parse_filters(params: list[tuple[str, str]]) -> dict[str, dict[str, str]]:
    """``[(name, value)]`` of the query → ``{key: {op: value}}`` for the ``cf_*`` parameters."""
    out: dict[str, dict[str, str]] = {}
    for name, value in params:
        if not name.startswith('cf_'):
            continue
        rest = name[3:]
        op = 'eq'
        for suffix in _SUFFIXES:
            if rest.endswith(suffix):
                rest, op = rest[: -len(suffix)], suffix[1:]
                break
        if rest:
            out.setdefault(rest, {})[op] = value
    return out


async def filter_clauses(
    session: DBAsyncScopedSession,
    organization_id: UUID,
    project_id: UUID | None,
    filters: dict[str, dict[str, str]],
) -> list[ColumnElement[bool]]:
    """SQL conditions on ``taas_tasks`` for the parsed filters (unknown keys → 400)."""
    if not filters:
        return []
    fields = {
        f.key: f
        for f in await definitions(
            session, organization_id, project_id, include_archived=True
        )
    }
    task = ews_models.Task
    clauses: list[ColumnElement[bool]] = []
    for key, ops in filters.items():
        field = fields.get(key)
        if field is None:
            raise ClientException(detail=f'unknown custom field {key!r}')
        base = and_(Value.task_id == task.id, Value.field_id == field.id)
        for op, raw in ops.items():
            if op == 'empty':
                has = exists(select(Value.id).where(base))
                clauses.append(~has if raw.lower() == 'true' else has)
                continue
            cond: ColumnElement[bool]
            if field.type in ('text', 'textarea', 'url'):
                cond = (
                    func.lower(Value.value_text).contains(raw.lower())
                    if op == 'contains'
                    else func.lower(Value.value_text) == raw.lower()
                )
            elif field.type in ('number', 'money'):
                n = _decimal(raw, f'cf_{key}') if op != 'currency' else None
                if op == 'currency':
                    cond = Value.value_currency == raw.upper()
                elif op == 'gte':
                    cond = Value.value_number >= n
                elif op == 'lte':
                    cond = Value.value_number <= n
                else:
                    cond = Value.value_number == n
            elif field.type == 'date':
                d = date.fromisoformat(raw[:10])
                cond = (
                    Value.value_date >= d
                    if op in ('from', 'gte')
                    else Value.value_date <= d
                    if op in ('to', 'lte')
                    else Value.value_date == d
                )
            elif field.type == 'checkbox':
                cond = Value.value_bool.is_(raw.lower() == 'true')
            else:
                ids = [
                    i.strip().lower() if field.type == 'user' else i.strip()
                    for i in raw.split(',')
                    if i.strip()
                ]
                if op == 'all':
                    cond = Value.value_refs.contains(ids)
                elif op == 'not':
                    clauses.append(
                        ~exists(
                            select(Value.id).where(base, Value.value_refs.overlap(ids))
                        )
                    )
                    continue
                else:
                    cond = Value.value_refs.overlap(ids)
            clauses.append(exists(select(Value.id).where(base, cond)))
    return clauses


async def sort_key(
    session: DBAsyncScopedSession,
    organization_id: UUID,
    project_id: UUID | None,
    key: str,
) -> Any:
    """A correlated scalar to order tasks by ``cf_<key>``."""
    field = next(
        (
            f
            for f in await definitions(
                session, organization_id, project_id, include_archived=True
            )
            if f.key == key
        ),
        None,
    )
    if field is None:
        raise ClientException(detail=f'unknown custom field {key!r}')
    column = {
        'number': Value.value_number,
        'money': Value.value_number,
        'date': Value.value_date,
        'checkbox': Value.value_bool,
    }.get(field.type, Value.value_text)
    if field.type in ('select', 'multi_select', 'user'):
        column = func.array_to_string(Value.value_refs, ',')
    task = ews_models.Task
    return (
        select(column)
        .where(Value.task_id == task.id, Value.field_id == field.id)
        .scalar_subquery()
    )


# --- completion guard (Ppm-0852: required before done) ----------------------------------------------

from . import _work_items as _items  # noqa: E402 — registers the guard; _work_items does not import this module


@_items.register_done_guard
async def _required_fields(
    session: DBAsyncScopedSession, task: ews_models.Task
) -> _items.DoneBlock | None:
    missing = await missing_before_done(session, task)
    if not missing:
        return None
    return _items.DoneBlock(
        'fields_required', 'fill in the required fields first', {'fields': missing}
    )
