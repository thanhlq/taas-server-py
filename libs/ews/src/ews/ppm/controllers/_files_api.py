"""Files and web links of projects and items (Ppm-0840…0843): the File Manager source drive of the project
(uploads, previews, versions through ``/api/v1/files``) and the links stored by PPM."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, post, status

from ews.security import current_scope

from .. import _access as access
from .. import _files
from ..schemas._files_api import PpmFilesOut, PpmLinkCreate, PpmLinkOut


def _link_out(link) -> PpmLinkOut:  # noqa: ANN001
    return PpmLinkOut(
        id=str(link.id),
        url=link.url or '',
        title=link.title,
        added_by=link.added_by,
        created_at=link.created_at,
    )


class ProjectFilesController(BaseController):
    api_prefix = '/api/v1/projects'
    tags = ('Projects',)

    @get(
        '/{project_id}/files',
        summary="The project's drive in the File Manager (created on first use)",
    )
    @db_context_session(auto_commit=True)
    async def project_files(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> PpmFilesOut:
        scope = await current_scope()
        project = await access.load_project(session, scope, project_id)
        drive = await _files.project_drive(session, project)
        return PpmFilesOut(drive_id=str(drive.id))

    @get('/{project_id}/links')
    @db_context_session
    async def project_links(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> list[PpmLinkOut]:
        scope = await current_scope()
        project = await access.load_project(session, scope, project_id)
        return [
            _link_out(link) for link in await _files.links(session, project.id, None)
        ]

    @post('/{project_id}/links', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def add_project_link(
        self, project_id: str, data: PpmLinkCreate, session: DBAsyncScopedSession
    ) -> PpmLinkOut:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, access.PROJECT, 'update'
        )
        return _link_out(
            await _files.add_link(
                session, scope, project, None, url=data.url, title=data.title
            )
        )

    @delete('/{project_id}/links/{link_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def remove_project_link(
        self, project_id: str, link_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, access.PROJECT, 'update'
        )
        await _files.remove_link(session, scope, project, None, link_id)


class TaskFilesController(BaseController):
    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get(
        '/{task_id}/files',
        summary="Drive + folder of the item's attachments (created on first use)",
    )
    @db_context_session(auto_commit=True)
    async def task_files(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> PpmFilesOut:
        scope = await current_scope()
        task, project = await access.load_task(session, scope, task_id)
        drive, folder_id = await _files.task_folder(session, scope, project, task)
        return PpmFilesOut(drive_id=str(drive.id), folder_id=folder_id)

    @get('/{task_id}/links')
    @db_context_session
    async def task_links(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> list[PpmLinkOut]:
        scope = await current_scope()
        task, project = await access.load_task(session, scope, task_id)
        return [
            _link_out(link) for link in await _files.links(session, project.id, task.id)
        ]

    @post('/{task_id}/links', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def add_task_link(
        self, task_id: str, data: PpmLinkCreate, session: DBAsyncScopedSession
    ) -> PpmLinkOut:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, access.TASK, 'update'
        )
        return _link_out(
            await _files.add_link(
                session, scope, project, task, url=data.url, title=data.title
            )
        )

    @delete('/{task_id}/links/{link_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def remove_task_link(
        self, task_id: str, link_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, access.TASK, 'update'
        )
        await _files.remove_link(session, scope, project, task, link_id)
