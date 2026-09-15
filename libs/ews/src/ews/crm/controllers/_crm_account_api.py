"""CRM Account HTTP controller (EWS CRM).

Thin controller over :class:`CrmAccountRepository`. Provides create, list,
detail, update and delete for accounts (clients/customers).
"""

from __future__ import annotations

import re
from typing import Optional
from uuid import UUID, uuid4

import db.models.ews as ews_models
from advanced_alchemy.filters import LimitOffset, OrderBy
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, status
from foundation.http.response import PaginatedResponse, create_paginated_response

from ..repos import CrmAccountRepository, RepoFactory
from ..schemas import (
    CrmAccountCreateRequest,
    CrmAccountListItem,
    CrmAccountResponse,
    CrmAccountUpdateRequest,
)


def _to_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _slugify(name: str) -> str:
    """Build a unique, URL-safe slug from a name (SlugKey requires a non-null unique slug)."""
    base = re.sub(r'[^a-z0-9]+', '-', (name or 'account').lower()).strip('-') or 'account'
    return f'{base[:48]}-{uuid4().hex[:8]}'


def _to_list_item(a: ews_models.CrmAccount) -> CrmAccountListItem:
    return CrmAccountListItem(
        id=str(a.id),
        name=a.name,
        code=a.code,
        display_name=a.display_name,
        account_type=a.account_type,
        email=a.email,
        phone_office=a.phone_office,
        website=a.website,
        status=a.status,
        is_individual=a.is_individual,
        starred=a.starred,
        color=a.color,
        avatar_url=a.avatar_url,
        created_at=getattr(a, 'created_at', None),
        updated_at=getattr(a, 'updated_at', None),
    )


def _to_response(a: ews_models.CrmAccount) -> CrmAccountResponse:
    return CrmAccountResponse(
        id=str(a.id),
        name=a.name,
        code=a.code,
        display_name=a.display_name,
        account_type=a.account_type,
        email=a.email,
        phone_office=a.phone_office,
        website=a.website,
        status=a.status,
        is_individual=a.is_individual,
        starred=a.starred,
        color=a.color,
        avatar_url=a.avatar_url,
        created_at=getattr(a, 'created_at', None),
        updated_at=getattr(a, 'updated_at', None),
        commercial_name=a.commercial_name,
        description=a.description,
        notes=a.notes,
        industry_id=a.industry_id,
        employees=a.employees,
        annual_revenue=a.annual_revenue,
        org_id=a.org_id,
        settings=a.settings,
        account_metadata=a.account_metadata,
    )


class CrmAccountController(BaseController):
    """CRM accounts: create, list, detail, update, delete."""

    api_prefix = '/api/v1/crm/accounts'
    tags = ('CRM Accounts',)

    @get('/')
    @db_context_session
    async def list_accounts(
        self, session: DBAsyncScopedSession, limit: int = 50, offset: int = 0
    ) -> PaginatedResponse[CrmAccountListItem]:
        repo = RepoFactory.get_repo(CrmAccountRepository, session)
        rows, total = await repo.list_and_count(
            LimitOffset(limit=limit, offset=offset),
            OrderBy(field_name='id', sort_order='desc'),
        )
        return create_paginated_response(
            [_to_list_item(a) for a in rows], total=total
        )

    @get('/{account_id}')
    @db_context_session
    async def get_account(
        self, account_id: str, session: DBAsyncScopedSession
    ) -> CrmAccountResponse:
        repo = RepoFactory.get_repo(CrmAccountRepository, session)
        a = await repo.get(_to_uuid(account_id))
        return _to_response(a)

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
            status=data.status or 'active',
            is_individual=data.is_individual if data.is_individual is not None else False,
            color=data.color,
            avatar_url=data.avatar_url,
            org_id=data.org_id,
        )
        created = await repo.add(account)
        return _to_response(created)

    @patch('/{account_id}')
    @db_context_session(auto_commit=True)
    async def update_account(
        self, account_id: str, data: CrmAccountUpdateRequest, session: DBAsyncScopedSession
    ) -> CrmAccountResponse:
        repo = RepoFactory.get_repo(CrmAccountRepository, session)
        a = await repo.get(_to_uuid(account_id))
        for field, value in data.as_dict().items():
            setattr(a, field, value)
        updated = await repo.update(a)
        return _to_response(updated)

    @delete('/{account_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_account(
        self, account_id: str, session: DBAsyncScopedSession
    ) -> None:
        repo = RepoFactory.get_repo(CrmAccountRepository, session)
        await repo.delete(_to_uuid(account_id))
