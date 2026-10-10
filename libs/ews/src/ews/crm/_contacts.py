"""CRM contacts (taas-specs/crm/contacts/contacts-spec.md, Crm-02xx, ADR-8 … 10): people at accounts — validation of
names, e-mails, phones and addresses, the duplicate guard on the primary e-mail, listing with search / filters, soft
delete, the account's primary contact (write-through of the legacy ``primary_contact`` fields) and the summaries other
apps embed (PPM project contacts). Permission ``crm.contact`` on the organization chain; records of the request's
organization only."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ews._crm_contact import ADDRESS_KINDS, PHONE_KINDS
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy import update as sql_update

from ews.authz import EwsResources
from ews.security import RequestScope, authorize, current_scope
from ews.shared import ConflictException, parse_uuid

Contact = ews_models.CrmContact
Account = ews_models.CrmAccount
CONTACT = EwsResources.CRM_CONTACT.value
LEAD_SOURCES = (
    'web',
    'referral',
    'event',
    'outreach',
    'partner',
    'social',
    'advertising',
    'other',
)
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MAX_ITEMS = 10
TEXT_FIELDS = {
    'salutation': 20,
    'first_name': 100,
    'last_name': 100,
    'job_title': 200,
    'department': 200,
    'linkedin_url': 500,
    'description': 10_000,
}
ADDRESS_FIELDS = ('street', 'postal_code', 'city', 'state', 'country')


def _error(detail: str, field: str) -> ClientException:
    return ClientException(
        detail=detail, extra={'code': 'invalid_contact', 'field': field}
    )


async def scope_for(action: str) -> RequestScope:
    """The caller, with ``crm.contact:<action>`` on the request's organization chain (403 otherwise)."""
    scope = await current_scope()
    await authorize(scope, CONTACT, action)
    return scope


def author(scope: RequestScope) -> str:
    return scope.email or str(scope.user_id)


def in_scope(scope: RequestScope) -> ColumnElement[bool]:
    return and_(
        Contact.tenant_id == scope.tenant_id,
        Contact.organization_id == scope.organization_id,
        Contact.deleted_at.is_(None),
    )


def _text(value: Any, limit: int) -> str | None:
    text = str(value or '').strip()
    return text[:limit] or None


def clean_emails(raw: Any) -> list[dict[str, Any]]:
    """``[{value, primary, opt_out, invalid}]``: trimmed, lower case, format checked, duplicates dropped, one primary
    (the first marked, else the first)."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        raise _error(f'emails: a list of at most {MAX_ITEMS}', 'emails')
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        value = (
            str((item or {}).get('value') if isinstance(item, dict) else item or '')
            .strip()
            .lower()
        )
        if not value:
            continue
        if not EMAIL.match(value) or len(value) > 320:
            raise _error(f'emails[{i}]: not an e-mail address', f'emails[{i}]')
        if value in seen:
            continue
        seen.add(value)
        flags = item if isinstance(item, dict) else {}
        out.append(
            {
                'value': value,
                'primary': bool(flags.get('primary')),
                'opt_out': bool(flags.get('opt_out')),
                'invalid': bool(flags.get('invalid')),
            }
        )
    return _one_primary(out)


def clean_phones(raw: Any) -> list[dict[str, Any]]:
    """``[{value, kind, primary}]``: trimmed (≤ 40), kind in ``PHONE_KINDS`` (default office), one primary."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        raise _error(f'phones: a list of at most {MAX_ITEMS}', 'phones')
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        flags = item if isinstance(item, dict) else {}
        value = str(flags.get('value') if flags else item or '').strip()
        if not value:
            continue
        if len(value) > 40 or not re.search(r'\d', value):
            raise _error(f'phones[{i}]: not a phone number', f'phones[{i}]')
        kind = flags.get('kind') or 'office'
        if kind not in PHONE_KINDS:
            raise _error(
                f'phones[{i}].kind: one of {", ".join(PHONE_KINDS)}',
                f'phones[{i}].kind',
            )
        out.append(
            {'value': value, 'kind': kind, 'primary': bool(flags.get('primary'))}
        )
    return _one_primary(out)


def _one_primary(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first = next((i for i, x in enumerate(items) if x['primary']), 0)
    for i, x in enumerate(items):
        x['primary'] = i == first
    return items


def clean_addresses(raw: Any) -> list[dict[str, Any]]:
    """At most one ``primary`` and one ``other`` address; empty ones dropped."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > len(ADDRESS_KINDS):
        raise _error('addresses: a primary and an other address at most', 'addresses')
    out: list[dict[str, Any]] = []
    kinds: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise _error(f'addresses[{i}]: must be an object', f'addresses[{i}]')
        kind = item.get('kind') or 'primary'
        if kind not in ADDRESS_KINDS or kind in kinds:
            raise _error(
                f'addresses[{i}].kind: primary or other, once each',
                f'addresses[{i}].kind',
            )
        address = {
            k: _text(item.get(k), 500 if k == 'street' else 120) for k in ADDRESS_FIELDS
        }
        if any(address.values()):
            kinds.add(kind)
            out.append({'kind': kind, **{k: v for k, v in address.items() if v}})
    return out


def clean_labels(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 30:
        raise _error('labels: a list of at most 30', 'labels')
    return list(dict.fromkeys(s for s in (str(x).strip()[:60] for x in raw) if s))


def display_name(first: str | None, last: str | None, email: str | None) -> str:
    return ' '.join(x for x in (first, last) if x) or email or ''


def primary_of(items: list[dict[str, Any]]) -> str | None:
    return next((x['value'] for x in items if x.get('primary')), None)


async def account_in_scope(
    session: DBAsyncScopedSession, scope: RequestScope, account_id: object
) -> Account:
    """An account of the request's organization (400 ``invalid_account`` otherwise) — for references from contacts and
    other apps (PPM project client)."""
    try:
        aid = parse_uuid(account_id, 'account', not_found=False)
    except ClientException as error:
        raise ClientException(
            detail='unknown account', extra={'code': 'invalid_account'}
        ) from error
    account = await session.scalar(
        select(Account).where(
            Account.id == aid,
            Account.tenant_id == scope.tenant_id,
            Account.organization_id == scope.organization_id,
        )
    )
    if account is None:
        raise ClientException(
            detail='unknown account', extra={'code': 'invalid_account'}
        )
    return account


async def load(
    session: DBAsyncScopedSession, scope: RequestScope, contact_id: object
) -> Contact:
    """A live contact of the request's organization (404 otherwise, also for a malformed id)."""
    contact = await session.scalar(
        select(Contact).where(
            Contact.id == parse_uuid(contact_id, 'contact'), in_scope(scope)
        )
    )
    if contact is None:
        raise NotFoundException(detail='contact not found')
    return contact


async def contacts_in_scope(
    session: DBAsyncScopedSession, scope: RequestScope, ids: list[object]
) -> list[Contact]:
    """Live contacts of the organization in the given order (400 ``invalid_contact`` for an unknown one)."""
    wanted: list[UUID] = []
    for value in ids:
        try:
            cid = parse_uuid(value, 'contact', not_found=False)
        except ClientException as error:
            raise _error('unknown contact', 'contact_ids') from error
        if cid not in wanted:
            wanted.append(cid)
    if not wanted:
        return []
    rows = {
        c.id: c
        for c in await session.scalars(
            select(Contact).where(Contact.id.in_(wanted), in_scope(scope))
        )
    }
    if len(rows) != len(wanted):
        raise _error('unknown contact', 'contact_ids')
    return [rows[i] for i in wanted]


async def _apply(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    contact: Contact,
    data: dict[str, Any],
) -> None:
    for field, limit in TEXT_FIELDS.items():
        if field in data:
            setattr(contact, field, _text(data[field], limit))
    if 'emails' in data:
        contact.emails = clean_emails(data['emails'])
        contact.email = primary_of(contact.emails)
    if 'phones' in data:
        contact.phones = clean_phones(data['phones'])
        contact.phone = primary_of(contact.phones)
    if 'addresses' in data:
        contact.addresses = clean_addresses(data['addresses'])
    if 'labels' in data:
        contact.labels = clean_labels(data['labels'])
    if 'owner' in data:
        contact.owner = _text(data['owner'], 320)
    if 'lead_source' in data:
        source = _text(data['lead_source'], 40)
        if source and source not in LEAD_SOURCES:
            raise _error(
                f'lead_source: one of {", ".join(LEAD_SOURCES)}', 'lead_source'
            )
        contact.lead_source = source
    if 'account_id' in data:
        contact.account_id = (
            (await account_in_scope(session, scope, data['account_id'])).id
            if data['account_id']
            else None
        )
    if 'reports_to_id' in data:
        if data['reports_to_id']:
            boss = await load(session, scope, data['reports_to_id'])
            if boss.id == contact.id:
                raise _error('a contact cannot report to itself', 'reports_to_id')
            contact.reports_to_id = boss.id
        else:
            contact.reports_to_id = None
    contact.name = display_name(contact.first_name, contact.last_name, contact.email)[
        :320
    ]
    if not contact.name:
        raise _error('a contact needs a first or last name, or an e-mail', 'last_name')


async def _guard_duplicate(
    session: DBAsyncScopedSession, scope: RequestScope, contact: Contact
) -> None:
    """Crm-0205: one live contact per primary e-mail in the organization."""
    if not contact.email:
        return
    other = await session.scalar(
        select(Contact.id).where(
            in_scope(scope),
            func.lower(Contact.email) == contact.email,
            Contact.id != contact.id,
        )
    )
    if other is not None:
        raise ConflictException(
            detail='a contact with this e-mail already exists',
            extra={'code': 'contact_exists', 'contact_id': str(other)},
        )


async def create(
    session: DBAsyncScopedSession, scope: RequestScope, data: dict[str, Any]
) -> Contact:
    contact = Contact(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        name='',
        emails=[],
        phones=[],
        addresses=[],
        labels=[],
        owner=author(scope),
        created_by=author(scope),
    )
    await _apply(session, scope, contact, data)
    if not data.get('allow_duplicate'):
        await _guard_duplicate(session, scope, contact)
    session.add(contact)
    await session.flush()
    if data.get('primary_for_account') and contact.account_id:
        await set_primary(session, scope, contact.account_id, contact.id)
    return contact


async def update(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    contact: Contact,
    data: dict[str, Any],
) -> Contact:
    before = contact.email
    await _apply(session, scope, contact, data)
    if contact.email != before:
        await _guard_duplicate(session, scope, contact)
    await session.flush()
    return contact


async def delete(
    session: DBAsyncScopedSession, scope: RequestScope, contact: Contact
) -> None:
    """Soft delete (Crm-0207): out of lists, pickers and projects; no longer an account's primary contact."""
    contact.deleted_at = datetime.now(UTC)
    await session.execute(
        sql_update(Account)
        .where(Account.primary_contact_id == contact.id)
        .values(primary_contact_id=None)
    )
    await session.flush()


async def set_primary(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    account_id: UUID,
    contact_id: UUID | None,
) -> None:
    await session.execute(
        sql_update(Account)
        .where(
            Account.id == account_id, Account.organization_id == scope.organization_id
        )
        .values(primary_contact_id=contact_id)
    )


async def listing(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    q: str | None = None,
    account_id: str | None = None,
    owner: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Contact], int]:
    """Crm-0201: newest first; ``q`` over name, e-mail, phone, job title and account name."""
    stmt = select(Contact).where(in_scope(scope))
    if account_id:
        stmt = stmt.where(
            Contact.account_id == parse_uuid(account_id, 'account', not_found=False)
        )
    if owner:
        stmt = stmt.where(func.lower(Contact.owner) == owner.strip().lower())
    if q and q.strip():
        like = f'%{q.strip()}%'
        names = select(Account.id).where(
            Account.organization_id == scope.organization_id, Account.name.ilike(like)
        )
        stmt = stmt.where(
            or_(
                Contact.name.ilike(like),
                Contact.email.ilike(like),
                Contact.phone.ilike(like),
                Contact.job_title.ilike(like),
                Contact.account_id.in_(names),
            )
        )
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        await session.scalars(
            stmt.order_by(Contact.id.desc())
            .limit(min(max(limit, 1), 200))
            .offset(max(offset, 0))
        )
    )
    return rows, total


async def _account_names(
    session: DBAsyncScopedSession, ids: set[UUID]
) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Account.id, Account.display_name, Account.name).where(
            Account.id.in_(ids)
        )
    )
    return {r.id: r.display_name or r.name or '' for r in rows}


async def _contact_names(
    session: DBAsyncScopedSession, ids: set[UUID]
) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Contact.id, Contact.name).where(
            Contact.id.in_(ids), Contact.deleted_at.is_(None)
        )
    )
    return {r.id: r.name for r in rows}


async def primary_accounts(
    session: DBAsyncScopedSession, contact_ids: set[UUID]
) -> set[UUID]:
    """Contacts that are their account's primary contact."""
    if not contact_ids:
        return set()
    return set(
        await session.scalars(
            select(Account.primary_contact_id).where(
                Account.primary_contact_id.in_(contact_ids)
            )
        )
    )


async def outs(
    session: DBAsyncScopedSession, rows: list[Contact], *, full: bool = False
) -> list[dict[str, Any]]:
    accounts = await _account_names(
        session, {c.account_id for c in rows if c.account_id}
    )
    bosses = (
        await _contact_names(
            session, {c.reports_to_id for c in rows if c.reports_to_id}
        )
        if full
        else {}
    )
    primary = await primary_accounts(session, {c.id for c in rows})
    out: list[dict[str, Any]] = []
    for c in rows:
        row: dict[str, Any] = {
            'id': str(c.id),
            'name': c.name,
            'salutation': c.salutation,
            'first_name': c.first_name,
            'last_name': c.last_name,
            'job_title': c.job_title,
            'department': c.department,
            'email': c.email,
            'phone': c.phone,
            'account_id': str(c.account_id) if c.account_id else None,
            'account_name': accounts.get(c.account_id) if c.account_id else None,
            'is_primary': c.id in primary,
            'owner': c.owner,
            'labels': c.labels or [],
            'created_at': c.created_at,
            'updated_at': c.updated_at,
        }
        if full:
            row |= {
                'emails': c.emails or [],
                'phones': c.phones or [],
                'addresses': c.addresses or [],
                'lead_source': c.lead_source,
                'reports_to_id': str(c.reports_to_id) if c.reports_to_id else None,
                'reports_to_name': bosses.get(c.reports_to_id)
                if c.reports_to_id
                else None,
                'linkedin_url': c.linkedin_url,
                'description': c.description,
                'created_by': c.created_by,
            }
        out.append(row)
    return out


async def out(session: DBAsyncScopedSession, contact: Contact) -> dict[str, Any]:
    return (await outs(session, [contact], full=True))[0]


async def summaries(
    session: DBAsyncScopedSession, ids: set[UUID]
) -> dict[UUID, Contact]:
    """Live contacts by id (accounts' primary contacts, project contacts)."""
    if not ids:
        return {}
    return {
        c.id: c
        for c in await session.scalars(
            select(Contact).where(Contact.id.in_(ids), Contact.deleted_at.is_(None))
        )
    }


async def write_primary(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    account: Account,
    value: dict[str, Any] | None,
) -> None:
    """ADR-10, Crm-0209: the account form's *Primary contact* (name, e-mail, phone) writes through to the primary
    contact — created on the first write; ``{}`` / empty values unlink it (the contact stays)."""
    name = _text((value or {}).get('name'), 200)
    email = _text((value or {}).get('email'), 320)
    phone = _text((value or {}).get('phone'), 40)
    if not (name or email or phone):
        account.primary_contact_id = None
        return
    contact = (
        (await summaries(session, {account.primary_contact_id})).get(
            account.primary_contact_id
        )
        if account.primary_contact_id
        else None
    )
    first, _, last = (name or '').partition(' ')
    data: dict[str, Any] = {
        'first_name': first or None,
        'last_name': last or None,
        'emails': [{'value': email, 'primary': True}] if email else [],
        'phones': [{'value': phone, 'kind': 'office', 'primary': True}]
        if phone
        else [],
    }
    if contact is None:
        contact = await create(
            session,
            scope,
            {**data, 'account_id': str(account.id), 'allow_duplicate': True},
        )
        account.primary_contact_id = contact.id
        return
    # keep the contact's other e-mails / phones: only the primary ones change
    others_e = [
        x
        for x in contact.emails or []
        if not x.get('primary') and x.get('value') != (email or '').lower()
    ]
    others_p = [
        x
        for x in contact.phones or []
        if not x.get('primary') and x.get('value') != phone
    ]
    data['emails'] = data['emails'] + others_e
    data['phones'] = data['phones'] + others_p
    await _apply(session, scope, contact, data)
