"""Client and contacts of a project (taas-specs/ppm/project/project-create-client-contacts.md, Ppm-0113…0117): the
client is a CRM account of the organization (``taas_projects.client_id``), the contacts are CRM contacts linked in
``taas_ppm_project_contacts`` with one default. Writes replace the whole set; deleted contacts are left out of reads."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import PpmProjectContact
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import delete, select

from ews.crm import _contacts as crm_contacts
from ews.security import RequestScope

from . import _access as access
from . import _events as events


async def check_client(
    session: DBAsyncScopedSession, scope: RequestScope, client_id: str | None
) -> str | None:
    """A CRM account of the organization (400 ``invalid_account``); ``""`` / ``None`` = no client."""
    if not client_id:
        return None
    return str((await crm_contacts.account_in_scope(session, scope, client_id)).id)


async def set_contacts(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    contact_ids: list[str],
    default_id: str | None,
) -> None:
    """Replace the project's contacts; the default must be one of them (else the first is)."""
    # one writer per project at a time: two quick saves must not both replace the set (unique pair index)
    await session.execute(
        select(ews_models.Project.id)
        .where(ews_models.Project.id == project.id)
        .with_for_update()
    )
    found = await crm_contacts.contacts_in_scope(session, scope, list(contact_ids))
    ids = [c.id for c in found]
    default = next(
        (c.id for c in found if default_id and str(c.id) == str(default_id)), None
    )
    if default_id and default is None:
        raise ClientException(
            detail='the default contact must be one of the contacts',
            extra={'code': 'invalid_contact'},
        )
    default = default or (ids[0] if ids else None)
    before = await _ids(session, project.id)
    await session.execute(
        delete(PpmProjectContact).where(PpmProjectContact.project_id == project.id)
    )
    await session.flush()
    for cid in ids:
        session.add(
            PpmProjectContact(
                tenant_id=project.tenant_id,
                project_id=project.id,
                contact_id=cid,
                is_default=cid == default,
                created_by=access.author(scope),
            )
        )
    await session.flush()
    after = (sorted(map(str, ids)), str(default) if default else None)
    if before != after:
        await events.emit(
            session,
            scope,
            'ppm.project.contacts_changed',
            'project',
            project.id,
            project_id=project.id,
            changes={
                'contacts': {'from': before[0], 'to': after[0]},
                'default_contact': {'from': before[1], 'to': after[1]},
            },
        )


async def _ids(
    session: DBAsyncScopedSession, project_id: UUID
) -> tuple[list[str], str | None]:
    rows = list(
        await session.scalars(
            select(PpmProjectContact).where(PpmProjectContact.project_id == project_id)
        )
    )
    return sorted(str(r.contact_id) for r in rows), next(
        (str(r.contact_id) for r in rows if r.is_default), None
    )


async def contacts_of(
    session: DBAsyncScopedSession, project_id: UUID
) -> list[dict[str, Any]]:
    """Ppm-0116: ``[{id, name, email, phone, job_title, account_id, is_default}]``, default first, live contacts only."""
    links = list(
        await session.scalars(
            select(PpmProjectContact).where(PpmProjectContact.project_id == project_id)
        )
    )
    found = await crm_contacts.summaries(session, {link.contact_id for link in links})
    out = []
    for link in sorted(links, key=lambda x: (not x.is_default, x.created_at)):
        c = found.get(link.contact_id)
        if c is None:
            continue
        out.append(
            {
                'id': str(c.id),
                'name': c.name,
                'email': c.email,
                'phone': c.phone,
                'job_title': c.job_title,
                'account_id': str(c.account_id) if c.account_id else None,
                'is_default': link.is_default,
            }
        )
    return out


async def projects_of(
    session: DBAsyncScopedSession, scope: RequestScope, contact_id: object
) -> list[dict[str, Any]]:
    """Ppm-0117: readable projects that list the contact (CRM contact *Projects* tab)."""
    contact = await crm_contacts.load(session, scope, contact_id)
    P = ews_models.Project
    rows = await session.execute(
        select(P.id, P.name, P.code, P.status, PpmProjectContact.is_default)
        .join(PpmProjectContact, PpmProjectContact.project_id == P.id)
        .where(
            PpmProjectContact.contact_id == contact.id,
            await access.readable_projects(scope),
        )
        .order_by(P.name)
    )
    return [
        {
            'id': str(r.id),
            'name': r.name,
            'code': r.code,
            'status': r.status,
            'is_default': r.is_default,
        }
        for r in rows
    ]
