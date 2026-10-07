"""Form submissions (Site-0701, Site-0635): visitors post through the renderer (``/_forms/…`` on the site
host), the renderer forwards here with its key; the form definition comes from the **live release** (a
draft form cannot receive data). Stored, rate limited per visitor, e-mailed to the notification address.
"""

from __future__ import annotations

import csv
import html
import io
import logging
import re
import uuid
from datetime import timedelta
from typing import Any
from uuid import UUID

from db.models.sites import Site, SiteFormSubmission, SitePage
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException, TooManyRequestsException
from sqlalchemy import func, select

from ews.shared import parse_uuid, utcnow

from ._document import iter_blocks
from ._publish import live_snapshot
from ._settings import sites_settings
from .schemas import SubmissionOut

logger = logging.getLogger(__name__)
_EMAIL = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$')
_PHONE = re.compile(r'^[+0-9 ().-]{5,30}$')
MAX_VALUE = 5000


def _find_form(snapshot: dict[str, Any], form_key: str, page_id: str | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for page in snapshot.get('pages') or []:
        if page_id and page['id'] != page_id:
            continue
        for block in iter_blocks(page.get('doc') or {}):
            if block.get('type') == 'form' and block.get('id') == form_key:
                return page, block
    return None


def clean_values(fields: list[dict[str, Any]], data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Keep the form's fields only, check required / e-mail / phone / select values."""
    values: dict[str, Any] = {}
    errors: list[str] = []
    for field in fields:
        name, ftype = field.get('name'), field.get('type') or 'text'
        raw = data.get(name)
        if ftype == 'checkbox':
            value: Any = raw in (True, 'true', 'on', '1', 1)
            if field.get('required') and not value:
                errors.append(f'{field.get("label") or name} must be checked')
            values[name] = value
            continue
        value = str(raw).strip() if raw is not None else ''
        if not value:
            if field.get('required'):
                errors.append(f'{field.get("label") or name} is required')
            continue
        if len(value) > MAX_VALUE:
            errors.append(f'{field.get("label") or name} is too long')
        elif ftype == 'email' and not _EMAIL.match(value):
            errors.append(f'{field.get("label") or name} must be an e-mail address')
        elif ftype == 'phone' and not _PHONE.match(value):
            errors.append(f'{field.get("label") or name} must be a phone number')
        elif ftype == 'select':
            options = [o.strip() for o in (field.get('options') or '').splitlines() if o.strip()]
            if options and value not in options:
                errors.append(f'{field.get("label") or name} has an unknown option')
        values[name] = value
    return values, errors


async def submit(
    session: DBAsyncScopedSession,
    site_id: object,
    form_key: str,
    data: dict[str, Any],
    *,
    page_id: str | None,
    ip_hash: str | None,
    honeypot: str | None,
) -> tuple[bool, str | None]:
    site = await session.scalar(select(Site).where(Site.id == parse_uuid(site_id, 'site'), Site.deleted_at.is_(None)))
    if site is None or site.status != 'published':
        raise NotFoundException(detail='form not found')
    snapshot = await live_snapshot(session, site)
    found = _find_form(snapshot or {}, form_key, page_id)
    if found is None:
        raise NotFoundException(detail='form not found')
    page, block = found
    props = block.get('props') or {}
    if honeypot:  # bots fill hidden fields: pretend success, store nothing
        return True, props.get('successMessage')
    if ip_hash:
        since = utcnow() - timedelta(minutes=1)
        recent = await session.scalar(
            select(func.count()).where(
                SiteFormSubmission.site_id == site.id, SiteFormSubmission.ip_hash == ip_hash, SiteFormSubmission.created_at >= since
            )
        )
        if (recent or 0) >= sites_settings().form_rate_per_minute:
            raise TooManyRequestsException(detail='too many submissions, try again in a minute')
    values, errors = clean_values(props.get('items') or [], data if isinstance(data, dict) else {})
    if errors:
        raise ClientException(detail='; '.join(errors), extra={'errors': errors})
    submission = SiteFormSubmission(
        id=uuid.uuid7(), tenant_id=site.tenant_id, site_id=site.id, page_id=UUID(page['id']), form_key=form_key,
        form_title=props.get('title'), data=values, ip_hash=(ip_hash or '')[:64] or None, created_at=utcnow(),
    )
    session.add(submission)
    await session.flush()
    recipient = props.get('notifyEmail') or (site.settings or {}).get('notify_email')
    if recipient:
        submission.notified = await _notify(recipient, site, page, props, values)
    return True, props.get('successMessage')


async def _notify(recipient: str, site: Site, page: dict[str, Any], props: dict[str, Any], values: dict[str, Any]) -> bool:
    try:
        from foundation.email.factory import EmailServiceFactory
        from foundation.email.types import EmailMultiAlternatives

        rows = ''.join(
            f'<tr><th align="left" style="padding:4px 12px 4px 0">{html.escape(str(k))}</th>'
            f'<td style="padding:4px 0;white-space:pre-wrap">{html.escape(str(v))}</td></tr>'
            for k, v in values.items()
        )
        title = props.get('title') or 'Form'
        body = (
            f'<p>New submission of <b>{html.escape(title)}</b> on <b>{html.escape(site.name)}</b> '
            f'({html.escape(page.get("path") or "/")}).</p><table>{rows}</table>'
        )
        text = '\n'.join(f'{k}: {v}' for k, v in values.items())
        reply_to = [v for k, v in values.items() if isinstance(v, str) and _EMAIL.match(v)][:1]
        service = EmailServiceFactory.get_email_service()
        await service.send_message(
            EmailMultiAlternatives(
                subject=f'[{site.name}] {title}', body=text, html_body=body, to=[recipient], reply_to=reply_to,
            )
        )
        return True
    except Exception as error:  # noqa: BLE001 - the submission is stored, e-mail is best effort
        logger.warning('form notification e-mail failed: %s', error)
        return False


async def list_submissions(
    session: DBAsyncScopedSession, site: Site, *, form_key: str | None = None, limit: int = 100, offset: int = 0
) -> tuple[list[SubmissionOut], int]:
    stmt = select(SiteFormSubmission).where(SiteFormSubmission.site_id == site.id)
    if form_key:
        stmt = stmt.where(SiteFormSubmission.form_key == form_key)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(await session.scalars(stmt.order_by(SiteFormSubmission.created_at.desc()).limit(min(limit, 500)).offset(offset)))
    titles = dict(
        (await session.execute(select(SitePage.id, SitePage.title).where(SitePage.id.in_([r.page_id for r in rows if r.page_id])))).all()
    )
    return [
        SubmissionOut(
            id=str(r.id), form_key=r.form_key, form_title=r.form_title, page_id=str(r.page_id) if r.page_id else None,
            page_title=titles.get(r.page_id), data=r.data, notified=r.notified, created_at=r.created_at,
        )
        for r in rows
    ], total


async def export_csv(session: DBAsyncScopedSession, site: Site, form_key: str | None) -> str:
    items, _ = await list_submissions(session, site, form_key=form_key, limit=500)
    columns: list[str] = []
    for item in items:
        for key in item.data:
            if key not in columns:
                columns.append(key)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['submitted_at', 'form', 'page', *columns])
    for item in items:
        row = [item.created_at.isoformat(), item.form_title or item.form_key, item.page_title or '', *(item.data.get(c, '') for c in columns)]
        # CSV injection: neutralize cells that a spreadsheet would run as a formula
        writer.writerow([f"'{v}" if isinstance(v, str) and v[:1] in ('=', '+', '-', '@') else v for v in row])
    return out.getvalue()


async def delete_submission(session: DBAsyncScopedSession, site: Site, submission_id: object) -> None:
    sid = parse_uuid(submission_id, 'submission')
    row = await session.scalar(select(SiteFormSubmission).where(SiteFormSubmission.id == sid, SiteFormSubmission.site_id == site.id))
    if row is None:
        raise NotFoundException(detail='submission not found')
    await session.delete(row)
    await session.flush()
