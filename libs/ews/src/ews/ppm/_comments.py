"""Comments on work items and projects (taas-specs/ppm/collaboration/collaboration-spec.md, Ppm-0501…0512).

- One table (``taas_projects_comments``): ``object_type`` = ``task`` · ``project``, ``object_id``; the author is the
  session user (Ppm-0502); rich text is sanitized HTML + its plain text (Ppm-0503).
- Edit own (``edited_at``), soft delete own — or any with ``ppm.task_activity:delete`` (Ppm-0504).
- Mentions (``<span data-type="mention" data-id>``) are stored in ``taas_ppm_mentions``; a user who cannot read the
  subject is not notified and is returned in ``unreachable`` (Ppm-1708). Editing adds new mentions only.
- Events: ``ppm.comment.created`` · ``updated`` · ``deleted`` and ``ppm.task.mentioned`` per new mention; their subject
  is the commented item / project (Activity tabs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import db.models.ews as ews_models
from db.models.ppm import PpmMention
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)
from sqlalchemy import select

from ews.security import RequestScope
from ews.shared import html_to_text, mentioned_users, parse_uuid, sanitize_html

from . import _access as access
from . import _events as events
from ._members import readers as member_readers

MAX_TEXT = 20_000
Comment = ews_models.ProjectComment


@dataclass(slots=True)
class Saved:
    comment: Comment
    mentions: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)


def _content(text: str | None, html: str | None) -> tuple[str, str | None]:
    """``(plain text, sanitized html | None)`` of a request; 400 when empty or too long."""
    clean = sanitize_html(html) if html else None
    plain = html_to_text(clean) if clean else (text or '').strip()
    if not plain:
        raise ClientException(detail='a comment needs some text')
    if len(plain) > MAX_TEXT:
        raise ClientException(detail=f'a comment holds at most {MAX_TEXT} characters')
    return plain, clean


async def _record_mentions(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    subject_type: str,
    subject_id: str,
    comment: Comment | None,
    refs: list[str],
    *,
    title: str,
) -> tuple[list[str], list[str]]:
    """Store + announce the mentions not stored yet for this comment / description; ``(mentioned, unreachable)``."""
    if not refs:
        return [], []
    same_source = (
        PpmMention.comment_id == comment.id
        if comment
        else PpmMention.comment_id.is_(None)
    )
    existing = set(
        (
            await session.scalars(
                select(PpmMention.user_ref).where(
                    PpmMention.subject_type == subject_type,
                    PpmMention.subject_id == subject_id,
                    same_source,
                )
            )
        ).all()
    )
    readers = await member_readers(session, scope, project)
    mentioned, unreachable = [], []
    me = {str(scope.user_id).lower(), (scope.email or '').lower()}
    for ref in refs:
        if ref in existing or ref.lower() in me:
            continue
        if readers is not None and ref.lower() not in readers:
            unreachable.append(ref)
            continue
        session.add(
            PpmMention(
                tenant_id=scope.tenant_id,
                project_id=project.id,
                subject_type=subject_type,
                subject_id=subject_id,
                comment_id=comment.id if comment else None,
                user_ref=ref,
                created_by=access.author(scope),
            )
        )
        mentioned.append(ref)
    await session.flush()
    for ref in mentioned:
        await events.emit(
            session,
            scope,
            'ppm.task.mentioned' if subject_type == 'task' else 'ppm.project.mentioned',
            subject_type,
            subject_id,
            project_id=project.id,
            data={
                'user': ref,
                'comment_id': str(comment.id) if comment else None,
                'title': title,
                'excerpt': (comment.comment_text or '')[:200] if comment else None,
            },
        )
    return mentioned, unreachable


def _title(project: ews_models.Project, task: ews_models.Task | None) -> str:
    return (
        f'{task.code} {task.name}'.strip() if task is not None else (project.name or '')
    )


async def create(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    task: ews_models.Task | None,
    *,
    text: str | None,
    html: str | None,
) -> Saved:
    plain, clean = _content(text, html)
    subject_type, subject_id = (
        ('task', str(task.id)) if task is not None else ('project', str(project.id))
    )
    comment = Comment(
        user_id=access.author(scope),
        comment_text=plain,
        html_text=clean,
        content_type='html' if clean else 'text',
        project_id=str(project.id),
        object_id=subject_id,
        object_type=subject_type,
        tenant_id=scope.tenant_id,
    )
    session.add(comment)
    await session.flush()
    refs = mentioned_users(clean)
    mentioned, unreachable = await _record_mentions(
        session,
        scope,
        project,
        subject_type,
        subject_id,
        comment,
        refs,
        title=_title(project, task),
    )
    await events.emit(
        session,
        scope,
        'ppm.comment.created',
        subject_type,
        subject_id,
        project_id=project.id,
        data={
            'comment_id': str(comment.id),
            'excerpt': plain[:200],
            'mentioned_user_ids': mentioned,
            'title': _title(project, task),
        },
    )
    return Saved(comment, mentioned, unreachable)


async def get(
    session: DBAsyncScopedSession, subject_type: str, subject_id: str, comment_id: str
) -> Comment:
    comment = await session.scalar(
        select(Comment).where(
            Comment.id == parse_uuid(comment_id, 'comment'),
            Comment.object_type == subject_type,
            Comment.object_id == subject_id,
            Comment.deleted_at.is_(None),
        )
    )
    if comment is None:
        raise NotFoundException(detail='comment not found')
    return comment


async def edit(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    task: ews_models.Task | None,
    comment: Comment,
    *,
    text: str | None,
    html: str | None,
) -> Saved:
    if comment.user_id != access.author(scope):
        raise PermissionDeniedException(detail='only the author can edit a comment')
    plain, clean = _content(text, html)
    before = comment.comment_text
    comment.comment_text = plain
    comment.html_text = clean
    comment.content_type = 'html' if clean else 'text'
    comment.edited_at = datetime.now(UTC)
    await session.flush()
    mentioned, unreachable = await _record_mentions(
        session,
        scope,
        project,
        comment.object_type or 'task',
        comment.object_id or '',
        comment,
        mentioned_users(clean),
        title=_title(project, task),
    )
    await events.emit(
        session,
        scope,
        'ppm.comment.updated',
        comment.object_type or 'task',
        comment.object_id or '',
        project_id=project.id,
        changes={'text': {'from': (before or '')[:200], 'to': plain[:200]}},
        data={'comment_id': str(comment.id), 'title': _title(project, task)},
    )
    return Saved(comment, mentioned, unreachable)


async def can_delete(
    scope: RequestScope, project: ews_models.Project, comment: Comment
) -> bool:
    if comment.user_id and comment.user_id == access.author(scope):
        return True
    return await access.is_allowed(
        scope, access.TASK_ACTIVITY, 'delete', access.project_domains(scope, project.id)
    )


async def remove(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    task: ews_models.Task | None,
    comment: Comment,
) -> None:
    if not await can_delete(scope, project, comment):
        raise PermissionDeniedException(
            detail=f'missing permission {access.TASK_ACTIVITY}:delete'
        )
    comment.deleted_at = datetime.now(UTC)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.comment.deleted',
        comment.object_type or 'task',
        comment.object_id or '',
        project_id=project.id,
        data={'comment_id': str(comment.id), 'title': _title(project, task)},
    )


async def listing(
    session: DBAsyncScopedSession, subject_type: str, subject_id: str
) -> list[Comment]:
    """Newest first, deleted ones included (the UI shows a placeholder, Ppm-0504)."""
    rows = await session.scalars(
        select(Comment)
        .where(Comment.object_type == subject_type, Comment.object_id == subject_id)
        .order_by(Comment.id.desc())
        .limit(500)
    )
    return list(rows.all())


async def description_mentions(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    task: ews_models.Task,
    html: str | None,
) -> tuple[list[str], list[str]]:
    """Mentions in an item description (Ppm-0510): new ones are stored and announced."""
    return await _record_mentions(
        session,
        scope,
        project,
        'task',
        str(task.id),
        None,
        mentioned_users(html),
        title=_title(project, task),
    )
