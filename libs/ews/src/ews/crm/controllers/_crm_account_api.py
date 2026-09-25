"""CRM Account HTTP controller (EWS CRM).

Thin controller over :class:`CrmAccountRepository`. Provides create, list,
detail, update and delete for accounts (clients/customers).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional
from uuid import UUID, uuid4

import db.models.ews as ews_models
from db.models.ews.ews_enums import CrmAccountStatus
from advanced_alchemy.filters import LimitOffset, OrderBy, SearchFilter, StatementFilter
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, status
from foundation.http.response import PaginatedResponse, create_paginated_response
from sqlalchemy import select

from .._account_status import ACCOUNT_STATUS_COLORS, account_status, account_status_color
from ..repos import CrmAccountRepository, RepoFactory
from ..schemas import (
    CrmAccountCreateRequest,
    CrmAccountListItem,
    CrmAccountResponse,
    CrmAccountStatusOption,
    CrmAccountUpdateRequest,
    CrmContact,
)
from ..schemas._crm_account_api import _CrmBusinessInput

# CRM business fields kept in ``account_metadata`` (no dedicated columns yet).
_METADATA_FIELDS = ('arr', 'open_pipeline', 'health_score', 'renewal_date', 'primary_contact')
# Business fields that live elsewhere: tier → ``account_rank``, currency → ``currency_id``,
# country / city → the default address.
_BUSINESS_FIELDS = (*_METADATA_FIELDS, 'tier', 'currency', 'country', 'city')


def _to_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _slugify(name: str) -> str:
    """Build a unique, URL-safe slug from a name (SlugKey requires a non-null unique slug)."""
    base = re.sub(r'[^a-z0-9]+', '-', (name or 'account').lower()).strip('-') or 'account'
    return f'{base[:48]}-{uuid4().hex[:8]}'


def _metadata(a: ews_models.CrmAccount) -> dict[str, Any]:
    return a.account_metadata if isinstance(a.account_metadata, dict) else {}


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def _contact(value: Any) -> Optional[CrmContact]:
    if not isinstance(value, dict) or not any(value.get(k) for k in ('name', 'email', 'phone')):
        return None
    return CrmContact(name=value.get('name'), email=value.get('email'), phone=value.get('phone'))


def _fields(
    a: ews_models.CrmAccount, address: Optional[ews_models.CrmAccountAddress]
) -> dict[str, Any]:
    """Fields shared by the list item and the detail response."""
    meta = _metadata(a)
    status = account_status(a.status)
    renewal = meta.get('renewal_date')
    health = meta.get('health_score')
    return {
        'id': str(a.id),
        'name': a.name,
        'code': a.code,
        'display_name': a.display_name,
        'account_type': a.account_type,
        'email': a.email,
        'phone_office': a.phone_office,
        'website': a.website,
        # Legacy lowercase values are returned as their catalog status.
        'status': status.value if status else a.status,
        'status_color': account_status_color(a.status).value,
        'is_individual': a.is_individual,
        'starred': a.starred,
        'color': a.color,
        'avatar_url': a.avatar_url,
        'user_id': a.user_id,
        'description': a.description,
        'notes': a.notes,
        'created_at': getattr(a, 'created_at', None),
        'updated_at': getattr(a, 'updated_at', None),
        'last_activity_at': getattr(a, 'updated_at', None),
        'industry_id': a.industry_id,
        'tier': a.account_rank,
        'primary_contact': _contact(meta.get('primary_contact')),
        'arr': _number(meta.get('arr')),
        'open_pipeline': _number(meta.get('open_pipeline')),
        'currency': a.currency_id or 'USD',
        'health_score': int(health) if isinstance(health, (int, float)) else None,
        'renewal_date': date.fromisoformat(renewal) if isinstance(renewal, str) and renewal else None,
        'country': address.address_country_name if address else None,
        'city': address.address_city if address else None,
    }


def _to_list_item(
    a: ews_models.CrmAccount, address: Optional[ews_models.CrmAccountAddress] = None
) -> CrmAccountListItem:
    return CrmAccountListItem(**_fields(a, address))


def _to_response(
    a: ews_models.CrmAccount, address: Optional[ews_models.CrmAccountAddress] = None
) -> CrmAccountResponse:
    return CrmAccountResponse(
        **_fields(a, address),
        commercial_name=a.commercial_name,
        employees=a.employees,
        annual_revenue=a.annual_revenue,
        org_id=a.org_id,
        settings=a.settings,
        account_metadata=a.account_metadata,
    )


async def _addresses(
    session: DBAsyncScopedSession, account_ids: list[UUID]
) -> dict[UUID, ews_models.CrmAccountAddress]:
    """Each account's main address: the default one, else the first."""
    if not account_ids:
        return {}
    model = ews_models.CrmAccountAddress
    result = await session.execute(
        select(model)
        .where(model.account_id.in_(account_ids))
        .order_by(model.account_id, model.is_default.desc(), model.created_at)
    )
    main: dict[UUID, ews_models.CrmAccountAddress] = {}
    for address in result.scalars():
        main.setdefault(address.account_id, address)
    return main


async def _apply_business(
    session: DBAsyncScopedSession,
    a: ews_models.CrmAccount,
    data: _CrmBusinessInput,
    provided: set[str],
) -> None:
    """Write the business fields that were sent (``provided``) to their storage."""
    meta = dict(_metadata(a))
    for field in _METADATA_FIELDS:
        if field not in provided:
            continue
        value = getattr(data, field)
        if field == 'renewal_date':
            value = value.isoformat() if value else None
        elif field == 'primary_contact':
            value = (
                {k: getattr(value, k) for k in ('name', 'email', 'phone') if getattr(value, k)}
                if value
                else None
            )
        if value is None or value == {}:
            meta.pop(field, None)
        else:
            meta[field] = value
    a.account_metadata = meta
    if 'tier' in provided:
        a.account_rank = data.tier or None
    if 'currency' in provided:
        a.currency_id = data.currency or None
    if 'country' in provided or 'city' in provided:
        addresses = await _addresses(session, [a.id]) if a.id else {}
        address = addresses.get(a.id)
        if address is None:
            address = ews_models.CrmAccountAddress(
                account_id=a.id,
                is_default=True,
                address_type='office',
                slug=f'address-{uuid4().hex[:12]}',
            )
            session.add(address)
        if 'country' in provided:
            address.address_country_name = data.country or None
        if 'city' in provided:
            address.address_city = data.city or None


class CrmAccountController(BaseController):
    """CRM accounts: create, list, detail, update, delete."""

    api_prefix = '/api/v1/crm/accounts'
    tags = ('CRM Accounts',)

    @get('/')
    @db_context_session
    async def list_accounts(
        self,
        session: DBAsyncScopedSession,
        limit: int = 50,
        offset: int = 0,
        q: Optional[str] = None,
    ) -> PaginatedResponse[CrmAccountListItem]:
        """List accounts; ``q`` searches name, display name, code and email (case-insensitive)."""
        repo = RepoFactory.get_repo(CrmAccountRepository, session)
        filters: list[StatementFilter] = [
            LimitOffset(limit=limit, offset=offset),
            OrderBy(field_name='id', sort_order='desc'),
        ]
        if q and q.strip():
            filters.append(
                SearchFilter(
                    field_name={'name', 'display_name', 'code', 'email'},
                    value=q.strip(),
                    ignore_case=True,
                )
            )
        rows, total = await repo.list_and_count(*filters)
        addresses = await _addresses(session, [a.id for a in rows])
        return create_paginated_response(
            [_to_list_item(a, addresses.get(a.id)) for a in rows], total=total
        )

    @get('/statuses')
    async def list_account_statuses(self) -> list[CrmAccountStatusOption]:
        """The account status catalog: every status with its badge colour."""
        return [
            CrmAccountStatusOption(value=s.value, color=c.value) for s, c in ACCOUNT_STATUS_COLORS.items()
        ]

    @get('/{account_id}')
    @db_context_session
    async def get_account(
        self, account_id: str, session: DBAsyncScopedSession
    ) -> CrmAccountResponse:
        repo = RepoFactory.get_repo(CrmAccountRepository, session)
        a = await repo.get(_to_uuid(account_id))
        addresses = await _addresses(session, [a.id])
        return _to_response(a, addresses.get(a.id))

    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_account(
        self, data: CrmAccountCreateRequest, session: DBAsyncScopedSession
    ) -> CrmAccountResponse:
        repo = RepoFactory.get_repo(CrmAccountRepository, session)
        account = ews_models.CrmAccount(
            name=data.name,
            code=data.code,
            slug=_slugify(data.display_name or data.name),
            commercial_name=data.commercial_name,
            display_name=data.display_name or data.name,
            description=data.description,
            notes=data.notes,
            account_type=data.account_type,
            email=data.email,
            phone_office=data.phone_office,
            website=data.website,
            industry_id=data.industry_id,
            employees=data.employees,
            annual_revenue=data.annual_revenue,
            status=data.status or CrmAccountStatus.PROSPECT,
            is_individual=data.is_individual if data.is_individual is not None else False,
            color=data.color,
            avatar_url=data.avatar_url,
            org_id=data.org_id,
            user_id=data.user_id,
        )
        created = await repo.add(account)
        provided = {f for f in _BUSINESS_FIELDS if getattr(data, f) is not None}
        await _apply_business(session, created, data, provided)
        await session.flush()
        addresses = await _addresses(session, [created.id])
        return _to_response(created, addresses.get(created.id))

    @patch('/{account_id}')
    @db_context_session(auto_commit=True)
    async def update_account(
        self, account_id: str, data: CrmAccountUpdateRequest, session: DBAsyncScopedSession
    ) -> CrmAccountResponse:
        repo = RepoFactory.get_repo(CrmAccountRepository, session)
        a = await repo.get(_to_uuid(account_id))
        fields = data.as_dict()
        provided = {f for f in _BUSINESS_FIELDS if f in fields}
        for field, value in fields.items():
            if field not in _BUSINESS_FIELDS:
                setattr(a, field, value)
        await _apply_business(session, a, data, provided)
        updated = await repo.update(a)
        addresses = await _addresses(session, [updated.id])
        return _to_response(updated, addresses.get(updated.id))

    @delete('/{account_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_account(
        self, account_id: str, session: DBAsyncScopedSession
    ) -> None:
        repo = RepoFactory.get_repo(CrmAccountRepository, session)
        await repo.delete(_to_uuid(account_id))
