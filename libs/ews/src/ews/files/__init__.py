"""File Manager (app ``files``, API ``/api/v1/files``): organization drives, shared drives, *My files*, a folder /
file tree with versions, uploads (through the API or direct to storage), signed downloads / previews, trash,
activity, stars, search — permission-trimmed per drive (``ews.access.ObjectAccess``, domain ``drive:<id>``).

Spec: taas-specs/files/ (roadmap.md for the status). Storage: kind ``document`` through the storage resolver.
"""

from foundation.http import BaseController

from ._nodes import purge_expired
from ._settings import FilesSettings, files_settings
from .controllers import FilesAppController, FilesDrivesController, FilesNodesController


def get_files_controllers() -> list[BaseController]:
    return [FilesAppController(), FilesDrivesController(), FilesNodesController()]


__all__ = ['FilesSettings', 'files_settings', 'get_files_controllers', 'purge_expired']
