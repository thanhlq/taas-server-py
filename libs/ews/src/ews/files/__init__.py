"""File Manager (app ``files``, API ``/api/v1/files``): organization drives, shared drives, *My files*, a folder /
file tree with versions, uploads (through the API or direct to storage), signed downloads / previews (cached view
URLs, revocable), the processing pipeline (checksum, thumbnails, previews, local full-text index), trash, activity,
stars, search by name and content — permission-trimmed per drive (``ews.access.ObjectAccess``, domain ``drive:<id>``).

Spec: taas-specs/files/ (roadmap.md for the status). Storage: kinds ``document`` and ``derived`` through the storage
resolver. Background work: ``start_pipeline('api' | 'worker')`` (``FILES_PIPELINE``), or ``run_pipeline`` /
``run_retention`` from any scheduler.
"""

from foundation.http import BaseController

from ._nodes import purge_expired
from ._pipeline import drain, run_pipeline, run_retention, start_pipeline, stop_pipeline
from ._settings import FilesSettings, files_settings
from ._sources import ensure_source_drive, ensure_source_folder, register_source
from .controllers import FilesAppController, FilesDrivesController, FilesNodesController


def get_files_controllers() -> list[BaseController]:
    return [FilesAppController(), FilesDrivesController(), FilesNodesController()]


__all__ = [
    'FilesSettings',
    'drain',
    'ensure_source_drive',
    'ensure_source_folder',
    'files_settings',
    'get_files_controllers',
    'purge_expired',
    'register_source',
    'run_pipeline',
    'run_retention',
    'start_pipeline',
    'stop_pipeline',
]
