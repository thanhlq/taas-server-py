"""``/api/v1/sites/{site_id}`` publishing (changes, publish, releases, rollback, preview links), form
submissions and AI assist."""

from __future__ import annotations

from typing import Any

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, post, status
from foundation.http.context import Context

from ews.authz import EwsResources
from ews.security import current_scope
from ews.shared import raw_response

from .. import _access as access
from .. import _ai as ai
from .. import _forms as forms
from .. import _publish as pub
from .. import _service as svc
from ..schemas import (
    AiAltOut,
    AiAltRequest,
    AiFeedback,
    AiSectionOut,
    AiSectionRequest,
    AiSeoOut,
    AiSeoRequest,
    AiTextOut,
    AiTextRequest,
    AiUsageOut,
    ChangesOut,
    PreviewLinkOut,
    PreviewLinkRequest,
    PublishRequest,
    ReleaseOut,
    SubmissionPage,
)

R = EwsResources


class SitePublishingController(BaseController):
    api_prefix = '/api/v1/sites/{site_id}'
    tags = ('Site Builder',)

    @get('/changes', summary='Unpublished changes + accessibility report (Site-0501, Site-0206)')
    @db_context_session
    async def changes(self, site_id: str, session: DBAsyncScopedSession) -> ChangesOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        changes = await pub.pending_changes(session, site)
        issues = await pub.check_accessibility(session, site, await pub.draft_pages(session, site))
        return ChangesOut(changes=changes, issues=issues)

    @post('/publish', summary='Publish the site (all drafts, or page_ids only)')
    @db_context_session(auto_commit=True)
    async def publish(self, site_id: str, data: PublishRequest, session: DBAsyncScopedSession) -> ReleaseOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'publish', include_archived=False)
        release = await pub.publish(
            session, scope, site, page_ids=data.page_ids, note=data.note, ignore_accessibility=data.ignore_accessibility
        )
        return (await pub.release_out(session, site, [release]))[0]

    @post('/unpublish', status_code=status.HTTP_204_NO_CONTENT, summary='Take the site offline (releases are kept)')
    @db_context_session(auto_commit=True)
    async def unpublish(self, site_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'publish')
        await pub.unpublish(session, scope, site)

    @get('/releases')
    @db_context_session
    async def releases(self, site_id: str, session: DBAsyncScopedSession) -> list[ReleaseOut]:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        return await pub.list_releases(session, site)

    @post('/releases/{release_id}/rollback', summary='Make an older release live again (Site-0502)')
    @db_context_session(auto_commit=True)
    async def rollback(self, site_id: str, release_id: str, session: DBAsyncScopedSession) -> ReleaseOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'publish', include_archived=False)
        release = await pub.rollback(session, scope, site, release_id)
        return (await pub.release_out(session, site, [release]))[0]

    @post('/preview-links', summary='Signed preview link of the drafts (≤ 7 days, noindex)')
    @db_context_session(auto_commit=True)
    async def preview_link(self, site_id: str, data: PreviewLinkRequest, session: DBAsyncScopedSession) -> PreviewLinkOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        url, expires = await pub.create_preview_link(session, scope, site, page_id=data.page_id, days=data.days)
        return PreviewLinkOut(url=url, expires_at=expires)

    @delete('/preview-links', status_code=status.HTTP_204_NO_CONTENT, summary='Revoke every preview link')
    @db_context_session(auto_commit=True)
    async def revoke_previews(self, site_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'publish')
        await pub.revoke_preview_links(session, scope, site)

    # --- form submissions -------------------------------------------------------------------------

    @get('/submissions')
    @db_context_session
    async def submissions(
        self, site_id: str, session: DBAsyncScopedSession, form_key: str | None = None, limit: int = 100, offset: int = 0
    ) -> SubmissionPage:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_SUBMISSION.value, 'read')
        items, total = await forms.list_submissions(session, site, form_key=form_key, limit=limit, offset=offset)
        return SubmissionPage(items=items, total=total)

    @get('/submissions/export', summary='CSV export of the submissions')
    @db_context_session
    async def export_submissions(self, site_id: str, ctx: Context, session: DBAsyncScopedSession, form_key: str | None = None) -> Any:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_SUBMISSION.value, 'export')
        body = await forms.export_csv(session, site, form_key)
        return raw_response(
            '﻿' + body, media_type='text/csv; charset=utf-8', request=ctx.req,
            headers={'content-disposition': f'attachment; filename="{site.slug}-submissions.csv"', 'cache-control': 'no-store'},
        )

    @delete('/submissions/{submission_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_submission(self, site_id: str, submission_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_SUBMISSION.value, 'delete')
        await forms.delete_submission(session, site, submission_id)

    # --- AI assist --------------------------------------------------------------------------------

    @get('/ai/usage', summary='AI switch, provider and monthly credits')
    @db_context_session
    async def ai_usage(self, site_id: str, session: DBAsyncScopedSession) -> AiUsageOut:
        from ews.ai import ai_settings

        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_PAGE.value, 'read')
        used = await ai.usage(session, scope.tenant_id)
        provider = ai_settings().provider
        return AiUsageOut(
            enabled=provider != 'none' and ai._site_enabled(site) and R.SITE_AI.value + ':use' in await access.permissions_on(scope, site.id),
            provider=provider, period=ai._period(), used=(used.tokens_in + used.tokens_out) if used else 0, limit=ai.credits_limit(),
        )

    @post('/ai/text', summary='Rewrite / shorten / expand / fix / tone / translate a selection')
    @db_context_session(auto_commit=True)
    async def ai_text(self, site_id: str, data: AiTextRequest, session: DBAsyncScopedSession) -> AiTextOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_AI.value, 'use')
        request_id, text, model = await ai.text_action(session, scope, site, data.action, data.text, tone=data.tone, language=data.language)
        return AiTextOut(request_id=request_id, text=text, model=model)

    @post('/ai/section', summary='Generate a section (validated blocks, to review before inserting)')
    @db_context_session(auto_commit=True)
    async def ai_section(self, site_id: str, data: AiSectionRequest, session: DBAsyncScopedSession) -> AiSectionOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_AI.value, 'use')
        doc = None
        if data.page_id:
            doc = (await svc.page_detail(session, site, await svc.get_page(session, site, data.page_id))).doc
        request_id, blocks, model = await ai.generate_section(session, scope, site, data.prompt, doc)
        return AiSectionOut(request_id=request_id, blocks=blocks, model=model)

    @post('/ai/seo', summary='Suggest the SEO title and description of a page')
    @db_context_session(auto_commit=True)
    async def ai_seo(self, site_id: str, data: AiSeoRequest, session: DBAsyncScopedSession) -> AiSeoOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_AI.value, 'use')
        detail = await svc.page_detail(session, site, await svc.get_page(session, site, data.page_id))
        request_id, title, description, model = await ai.seo_meta(session, scope, site, detail.title, data.doc or detail.doc)
        return AiSeoOut(request_id=request_id, title=title, description=description, model=model)

    @post('/ai/alt-text', summary='Suggest the alt text of an image (vision)')
    @db_context_session(auto_commit=True)
    async def ai_alt(self, site_id: str, data: AiAltRequest, session: DBAsyncScopedSession) -> AiAltOut:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_AI.value, 'use')
        request_id, alt, model = await ai.alt_text(session, scope, site, data.asset_id)
        return AiAltOut(request_id=request_id, alt=alt, model=model)

    @post('/ai/feedback', status_code=status.HTTP_204_NO_CONTENT, summary='Accepted or discarded (audit, Site-0815)')
    @db_context_session(auto_commit=True)
    async def ai_feedback(self, site_id: str, data: AiFeedback, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        site = await access.load_site(session, scope, site_id, R.SITE_AI.value, 'use')
        await ai.feedback(session, scope, site, data.request_id, data.accepted)
