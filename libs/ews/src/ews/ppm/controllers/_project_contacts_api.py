"""Projects of a CRM contact (taas-specs/ppm/project/project-create-client-contacts.md, Ppm-0117): the readable
projects that list the contact — the *Projects* tab of the CRM contact page. Client and contacts of a project are
written through the project routes (``contact_ids``, ``default_contact_id``)."""

from __future__ import annotations

from typing import Optional

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, get
from foundation.serialization import ApiResponse

from ews.crm import _contacts as crm_contacts

from .. import _project_contacts as project_contacts


class PpmContactProjectOut(ApiResponse):
    id: str
    name: str
    is_default: bool = False
    code: Optional[str] = None
    status: Optional[str] = None


class PpmContactProjectsController(BaseController):
    api_prefix = '/api/v1/ppm/contacts'
    tags = ('PPM projects',)

    @get('/{contact_id}/projects', summary='Readable projects that list a CRM contact')
    @db_context_session
    async def contact_projects(
        self, contact_id: str, session: DBAsyncScopedSession
    ) -> list[PpmContactProjectOut]:
        scope = await crm_contacts.scope_for('read')
        return [
            PpmContactProjectOut(**r)
            for r in await project_contacts.projects_of(session, scope, contact_id)
        ]
