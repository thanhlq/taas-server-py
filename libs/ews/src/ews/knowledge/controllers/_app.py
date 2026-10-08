"""``/api/v1/knowledge`` — app gate, roles, templates, home, review, search and signed attachment URLs."""

from __future__ import annotations

from typing import Any

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, get, post
from foundation.http.context import Context

from ews.access import RoleOut, object_roles
from ews.security import current_scope, is_allowed
from ews.shared import parse_uuid, raw_response
from ews.sites._document import validate_document
from ews.sites.schemas import DocumentIn, ValidationOut

from .. import _attachments, _home
from .._access import KB_SPACES, SPACE
from .._templates import templates
from ..schemas import KbHomeOut, KnowledgeAccessOut, KbPageSummaryOut, KbTemplateOut


class KnowledgeController(BaseController):
    api_prefix = '/api/v1/knowledge'
    tags = ('Knowledge Center',)

    @get(
        '/access',
        summary='Can the caller open the Knowledge Center (and create spaces)?',
    )
    @db_context_session
    async def access(self, session: DBAsyncScopedSession) -> KnowledgeAccessOut:
        scope = await current_scope()
        return KnowledgeAccessOut(
            allowed=True,
            can_create_space=await is_allowed(scope, SPACE, 'create'),
            organization_slug=scope.organization.slug,
        )

    @get('/roles', summary='Roles that can be granted on a space')
    async def roles(self) -> list[RoleOut]:
        await current_scope()
        return object_roles(KB_SPACES)

    @get('/templates', summary='Built-in page templates (site documents, Kb-0301)')
    async def list_templates(self) -> list[KbTemplateOut]:
        await current_scope()
        return [
            KbTemplateOut(
                key=t['key'],
                name=t['name'],
                description=t['description'],
                icon=t['icon'],
                title=t['title'],
                doc=t['doc'],
            )
            for t in templates()
        ]

    @post(
        '/validate',
        summary='Validate a page body (site document) without saving (Markdown mode, imports)',
    )
    async def validate(self, data: DocumentIn) -> ValidationOut:
        await current_scope()
        issues = [str(i) for i in validate_document(data.doc)]
        return ValidationOut(valid=not issues, issues=issues)

    @get('/home', summary='Home: recent pages, my spaces, pages to review')
    @db_context_session
    async def home(self, session: DBAsyncScopedSession) -> KbHomeOut:
        return await _home.home(session, await current_scope())

    @get(
        '/review',
        summary='Pages the caller owns whose verification expired or ends within 14 days (Kb-0303)',
    )
    @db_context_session
    async def review(self, session: DBAsyncScopedSession) -> list[KbPageSummaryOut]:
        return await _home.review_pages(session, await current_scope())

    @get(
        '/search',
        summary='Published pages matching every term (title + text), permission-trimmed (Kb-0104)',
    )
    @db_context_session
    async def search(
        self,
        session: DBAsyncScopedSession,
        q: str | None = None,
        space_id: str | None = None,
        limit: int = 20,
    ) -> list[KbPageSummaryOut]:
        scope = await current_scope()
        sid = parse_uuid(space_id, 'space', not_found=False) if space_id else None
        return await _home.search(session, scope, q, sid, limit)

    @get(
        '/files/{token}',
        summary='Attachment bytes behind a signed URL (no session needed, 5 min)',
    )
    async def file(self, token: str, ctx: Context) -> Any:
        body, mime, headers = await _attachments.file_response_parts(token)
        return raw_response(body, media_type=mime, headers=headers, request=ctx.req)
