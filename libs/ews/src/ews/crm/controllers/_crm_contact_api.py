"""CRM contact routes (taas-specs/crm/crm-api.md › Contacts): list (search, account, owner), lead source catalog,
detail, create (duplicate guard), change, soft delete. Rules in ``ews.crm._contacts``."""

from __future__ import annotations

from typing import Optional

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, status
from foundation.http.response import PaginatedResponse, create_paginated_response

from .. import _contacts as contacts
from ..schemas._crm_contact_api import (
    CrmContactIn,
    CrmContactListItem,
    CrmContactOut,
    CrmContactPatch,
    CrmLeadSourceOut,
)


class CrmContactController(BaseController):
    """CRM contacts: list, lead sources, detail, create, change, delete."""

    api_prefix = '/api/v1/crm/contacts'
    tags = ('CRM Contacts',)

    @get('/', summary='Contacts (q, account_id, owner), newest first')
    @db_context_session
    async def list_contacts(
        self,
        session: DBAsyncScopedSession,
        q: Optional[str] = None,
        account_id: Optional[str] = None,
        owner: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaginatedResponse[CrmContactListItem]:
        scope = await contacts.scope_for('read')
        rows, total = await contacts.listing(
            session,
            scope,
            q=q,
            account_id=account_id,
            owner=owner,
            limit=limit,
            offset=offset,
        )
        return create_paginated_response(
            [CrmContactListItem(**r) for r in await contacts.outs(session, rows)],
            total=total,
        )

    @get('/lead-sources', summary='Lead source catalog (labels in the web)')
    async def lead_sources(self) -> list[CrmLeadSourceOut]:
        await contacts.scope_for('read')
        return [CrmLeadSourceOut(value=v) for v in contacts.LEAD_SOURCES]

    @get('/{contact_id}', summary='A contact')
    @db_context_session
    async def get_contact(
        self, contact_id: str, session: DBAsyncScopedSession
    ) -> CrmContactOut:
        scope = await contacts.scope_for('read')
        return CrmContactOut(
            **await contacts.out(
                session, await contacts.load(session, scope, contact_id)
            )
        )

    @post(
        '/',
        summary='Create a contact (409 contact_exists)',
        status_code=status.HTTP_201_CREATED,
    )
    @db_context_session(auto_commit=True)
    async def create_contact(
        self, data: CrmContactIn, session: DBAsyncScopedSession
    ) -> CrmContactOut:
        scope = await contacts.scope_for('create')
        return CrmContactOut(
            **await contacts.out(
                session, await contacts.create(session, scope, data.as_dict())
            )
        )

    @patch('/{contact_id}', summary='Change a contact (only the sent fields)')
    @db_context_session(auto_commit=True)
    async def update_contact(
        self, contact_id: str, data: CrmContactPatch, session: DBAsyncScopedSession
    ) -> CrmContactOut:
        scope = await contacts.scope_for('update')
        contact = await contacts.load(session, scope, contact_id)
        return CrmContactOut(
            **await contacts.out(
                session, await contacts.update(session, scope, contact, data.as_dict())
            )
        )

    @delete(
        '/{contact_id}',
        summary='Delete a contact (soft)',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    @db_context_session(auto_commit=True)
    async def delete_contact(
        self, contact_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await contacts.scope_for('delete')
        await contacts.delete(
            session, scope, await contacts.load(session, scope, contact_id)
        )
