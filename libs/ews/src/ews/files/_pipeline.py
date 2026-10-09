"""Processing pipeline of file versions (File-0600 … File-0605, decisions ADR-10 / ADR-11).

**The queue is the table**: a new version row is ``pipeline_status = 'pending'`` in the same transaction as the
upload (transactional, like an outbox — no broker needed). ``run_pipeline`` claims a batch with
``FOR UPDATE SKIP LOCKED`` (several processes never take the same version), then per version, **outside** a
transaction:

1. read the object (versions > ``FILES_PIPELINE_MAX_MB`` are skipped: ``none``);
2. checksum (SHA-256 when missing — direct uploads), type sniffed from the content, ``_derive.derive`` in a thread;
3. variants written to ``derived/files/{node}/{version}/{variant}.webp`` (immutable keys);
4. one short transaction saves ``taas_file_previews`` rows, the text of the **current** version in
   ``taas_file_contents`` (local full-text index; older versions' text removed) and the statuses / ``meta``.

Failures retry with a back-off (``attempts × 30 s``), ``failed`` after ``MAX_ATTEMPTS``; a ``running`` claim older
than ``STALE_AFTER`` (crashed process) is taken again. Newest versions first (interactive uploads before backfills).

Runners (``FILES_PIPELINE``): ``api`` = a background task of each API process (``start_pipeline('api')`` in the
lifespan, woken up right after uploads by ``kick()``); ``worker`` = ``ews_worker``; ``off`` = nobody (tests call
``run_pipeline``). The same loop runs the trash retention (``purge_expired``) every hour.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from db.models.files import FileContent, FileNode, FilePreview, FileVersion
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import delete, select, text, update

from ews.shared import utcnow

from . import _storage as storage
from ._derive import Derived, derive
from ._settings import FilesSettings, PipelineRunner, files_settings

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=10)
RETRY_SECONDS = 30
RETENTION_EVERY_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class _Job:
    tenant_id: UUID
    node_id: UUID
    version_id: UUID
    key: str
    mime: str
    size: int
    checksum: str | None
    current: bool


# --- queue ----------------------------------------------------------------------------------------

_CLAIM = text(
    """
    UPDATE taas_file_versions SET pipeline_status = 'running', pipeline_at = now(),
           pipeline_attempts = pipeline_attempts + 1
     WHERE id IN (
        SELECT v.id FROM taas_file_versions v JOIN taas_file_nodes n ON n.id = v.node_id
         WHERE n.deleted_at IS NULL AND v.pipeline_attempts < :max_attempts
           AND ((v.pipeline_status = 'pending'
                 AND (v.pipeline_attempts = 0
                      OR v.pipeline_at < now() - make_interval(secs => :retry * v.pipeline_attempts)))
             OR (v.pipeline_status = 'running' AND v.pipeline_at < now() - make_interval(secs => :stale)))
           AND (CAST(:tenant AS uuid) IS NULL OR v.tenant_id = CAST(:tenant AS uuid))
         ORDER BY v.created_at DESC
         LIMIT :limit
         FOR UPDATE OF v SKIP LOCKED)
    RETURNING id
    """
)
_GIVE_UP = text(
    """
    UPDATE taas_file_versions
       SET pipeline_status = 'failed', pipeline_at = now(),
           preview_status = CASE WHEN preview_status = 'pending' THEN 'failed' ELSE preview_status END,
           index_status = CASE WHEN index_status = 'pending' THEN 'failed' ELSE index_status END,
           pipeline_error = coalesce(pipeline_error, 'stopped after too many attempts')
     WHERE pipeline_status IN ('pending', 'running') AND pipeline_attempts >= :max_attempts
       AND (pipeline_status = 'pending' OR pipeline_at < now() - make_interval(secs => :stale))
       AND (CAST(:tenant AS uuid) IS NULL OR tenant_id = CAST(:tenant AS uuid))
    """
)


@db_context_session(auto_commit=True)
async def _claim(
    limit: int, tenant_id: UUID | None, *, session: DBAsyncScopedSession | None = None
) -> list[UUID]:
    assert session is not None
    params = {
        'max_attempts': MAX_ATTEMPTS,
        'stale': int(STALE_AFTER.total_seconds()),
        'tenant': str(tenant_id) if tenant_id else None,
    }
    await session.execute(_GIVE_UP, params)
    rows = await session.execute(
        _CLAIM, {**params, 'retry': RETRY_SECONDS, 'limit': limit}
    )
    return [r.id for r in rows]


@db_context_session
async def _load(
    version_id: UUID, *, session: DBAsyncScopedSession | None = None
) -> _Job | None:
    assert session is not None
    row = (
        await session.execute(
            select(FileVersion, FileNode.current_version_id)
            .join(FileNode, FileNode.id == FileVersion.node_id)
            .where(FileVersion.id == version_id, FileNode.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        return None
    version, current_id = row
    return _Job(
        tenant_id=version.tenant_id,
        node_id=version.node_id,
        version_id=version.id,
        key=version.key,
        mime=version.mime,
        size=version.size,
        checksum=version.checksum,
        current=current_id == version.id,
    )


@db_context_session(auto_commit=True)
async def _save(
    job: _Job,
    derived: Derived,
    checksum: str | None,
    keys: dict[str, str],
    *,
    session: DBAsyncScopedSession | None = None,
) -> bool:
    """Store the results; ``False`` when the item was purged meanwhile (the caller removes ``keys``)."""
    assert session is not None
    version = await session.scalar(
        select(FileVersion).where(FileVersion.id == job.version_id).with_for_update()
    )
    node = await session.scalar(select(FileNode).where(FileNode.id == job.node_id))
    if version is None or node is None or node.deleted_at is not None:
        return False
    now = utcnow()
    await session.execute(
        delete(FilePreview).where(FilePreview.version_id == job.version_id)
    )
    for image in derived.images:
        session.add(
            FilePreview(
                id=uuid.uuid7(),
                tenant_id=job.tenant_id,
                node_id=job.node_id,
                version_id=job.version_id,
                variant=image.variant,
                key=keys[image.variant],
                mime=image.mime,
                width=image.width,
                height=image.height,
                size=len(image.body),
                placeholder=derived.placeholder if image.variant == 'thumb' else None,
                created_at=now,
            )
        )
    current = node.current_version_id == job.version_id
    await session.execute(
        delete(FileContent).where(FileContent.version_id == job.version_id)
    )
    if current:
        # Only the current version is searchable: the text of older versions goes.
        await session.execute(
            delete(FileContent).where(FileContent.node_id == job.node_id)
        )
    index = derived.index
    if derived.text and current:
        session.add(
            FileContent(
                id=uuid.uuid7(),
                tenant_id=job.tenant_id,
                node_id=job.node_id,
                version_id=job.version_id,
                text=derived.text,
                chars=len(derived.text),
                truncated=derived.truncated,
                created_at=now,
            )
        )
    elif index == 'ready':
        index = 'none'  # an older version: text not kept
    version.pipeline_status = 'done'
    version.pipeline_at = now
    version.pipeline_error = derived.error
    version.preview_status = (
        'ready'
        if derived.images
        else ('none' if derived.preview == 'ready' else derived.preview)
    )
    version.index_status = index
    version.meta = {k: v for k, v in derived.meta.items() if v is not None}
    if checksum and not version.checksum:
        version.checksum = checksum
    await session.flush()
    return True


@db_context_session(auto_commit=True)
async def _retry_later(
    version_id: UUID, error: str, *, session: DBAsyncScopedSession | None = None
) -> None:
    """Back to ``pending`` (back-off from ``pipeline_at``), ``failed`` after the last attempt."""
    assert session is not None
    version = await session.scalar(
        select(FileVersion).where(FileVersion.id == version_id)
    )
    if version is None:
        return
    last = version.pipeline_attempts >= MAX_ATTEMPTS
    version.pipeline_status = 'failed' if last else 'pending'
    version.pipeline_at = utcnow()
    version.pipeline_error = error[:500]
    if last:
        version.preview_status = (
            'failed' if version.preview_status == 'pending' else version.preview_status
        )
        version.index_status = (
            'failed' if version.index_status == 'pending' else version.index_status
        )


# --- processing -----------------------------------------------------------------------------------


async def process_version(
    version_id: UUID, settings: FilesSettings | None = None
) -> str:
    """Process one claimed version; returns the outcome (``done`` · ``gone`` · ``skipped`` · ``missing``)."""
    settings = settings or files_settings()
    job = await _load(version_id)
    if job is None:
        return 'gone'
    if job.size > settings.pipeline_max_bytes:
        await _save(
            job,
            Derived(preview='none', index='none', error='too large to process'),
            None,
            {},
        )
        return 'skipped'
    blob = await (await storage.store_for(job.tenant_id)).get(job.key)
    if blob is None:
        await _save(
            job,
            Derived(preview='none', index='none', error='object missing in storage'),
            None,
            {},
        )
        return 'missing'
    checksum = job.checksum or await asyncio.to_thread(
        lambda: hashlib.sha256(blob.body).hexdigest()
    )
    derived = await asyncio.to_thread(
        derive, blob.body, job.mime, max_chars=settings.index_max_chars
    )
    keys: dict[str, str] = {}
    try:
        for image in derived.images:
            key = storage.preview_key(job.node_id, job.version_id, image.variant)
            await storage.put_bytes(
                job.tenant_id,
                key,
                image.body,
                image.mime,
                cache_control=storage.IMMUTABLE_PRIVATE,
            )
            keys[image.variant] = key
        if not await _save(job, derived, checksum, keys):
            await storage.delete_keys(job.tenant_id, list(keys.values()))
            return 'gone'
    except Exception:
        await storage.delete_keys(job.tenant_id, list(keys.values()))
        raise
    return 'done'


async def run_pipeline(
    *, limit: int | None = None, tenant_id: UUID | None = None
) -> int:
    """One pass: claim up to ``limit`` versions (``FILES_PIPELINE_BATCH``) and process them. Returns how many were
    claimed (``0`` = the queue is empty)."""
    settings = files_settings()
    ids = await _claim(limit or settings.pipeline_batch, tenant_id)
    for version_id in ids:
        try:
            outcome = await process_version(version_id, settings)
            logger.debug(
                'files.pipeline.%s', outcome, extra={'version_id': str(version_id)}
            )
        except Exception as error:  # noqa: BLE001 — one broken file must not stop the batch
            logger.warning(
                'files.pipeline.failed',
                extra={'version_id': str(version_id), 'error': repr(error)[:300]},
            )
            await _retry_later(version_id, f'{type(error).__name__}: {error}')
    return len(ids)


async def drain(*, tenant_id: UUID | None = None, rounds: int = 20) -> int:
    """Run passes until the queue is empty (tests, one-off backfills)."""
    total = 0
    for _ in range(rounds):
        claimed = await run_pipeline(tenant_id=tenant_id)
        total += claimed
        if not claimed:
            break
    return total


@db_context_session(auto_commit=True)
async def run_retention(*, session: DBAsyncScopedSession | None = None) -> int:
    """Trash retention (File-0306): purge what is older than ``FILES_TRASH_DAYS``."""
    from ._nodes import purge_expired

    assert session is not None
    return await purge_expired(session)


@db_context_session(auto_commit=True)
async def reprocess(
    node: FileNode, *, session: DBAsyncScopedSession | None = None
) -> None:
    """Queue the current version again (*Rebuild preview*: failed previews, a new extractor)."""
    assert session is not None
    if node.current_version_id is None:
        return
    await session.execute(
        update(FileVersion)
        .where(FileVersion.id == node.current_version_id)
        .values(
            pipeline_status='pending',
            pipeline_attempts=0,
            pipeline_at=None,
            pipeline_error=None,
            preview_status='pending',
            index_status='pending',
        )
    )


# --- background runner ----------------------------------------------------------------------------


@dataclass(slots=True)
class _Runner:
    task: asyncio.Task[None]
    stop: asyncio.Event
    wake: asyncio.Event


_RUNNER: list[_Runner] = []


def kick(delay: float = 0.5) -> None:
    """Wake the in-process runner up shortly after the current request commits (thumbnails within a second)."""
    if not _RUNNER:
        return
    runner = _RUNNER[0]
    with contextlib.suppress(RuntimeError):
        asyncio.get_running_loop().call_later(delay, runner.wake.set)


async def _loop(stop: asyncio.Event, wake: asyncio.Event) -> None:
    settings = files_settings()
    next_retention = time.monotonic() + 60
    logger.info('files.pipeline.started', extra={'runner': settings.pipeline})
    while not stop.is_set():
        claimed = 0
        try:
            claimed = await run_pipeline(limit=settings.pipeline_batch)
        except Exception as error:  # noqa: BLE001 — database briefly unavailable, …
            logger.warning(
                'files.pipeline.poll_failed', extra={'error': repr(error)[:300]}
            )
        if time.monotonic() >= next_retention:
            next_retention = time.monotonic() + RETENTION_EVERY_SECONDS
            try:
                purged = await run_retention()
                if purged:
                    logger.info('files.retention.purged', extra={'items': purged})
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    'files.retention.failed', extra={'error': repr(error)[:300]}
                )
        if claimed >= settings.pipeline_batch:
            continue  # more work waiting
        wake.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                _first(stop, wake), timeout=settings.pipeline_interval_seconds
            )


async def _first(*events: asyncio.Event) -> None:
    waiters = [asyncio.ensure_future(e.wait()) for e in events]
    try:
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()


def start_pipeline(runner: PipelineRunner) -> asyncio.Task[None] | None:
    """Start the background loop when ``FILES_PIPELINE`` names this ``runner`` (``api`` / ``worker``)."""
    if files_settings().pipeline != runner or _RUNNER:
        return None
    stop, wake = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(_loop(stop, wake), name='files-pipeline')
    _RUNNER.append(_Runner(task, stop, wake))
    return task


async def stop_pipeline(timeout: float = 10.0) -> None:
    if not _RUNNER:
        return
    runner = _RUNNER.pop()
    runner.stop.set()
    try:
        await asyncio.wait_for(runner.task, timeout=timeout)
    except TimeoutError, asyncio.CancelledError:
        runner.task.cancel()
