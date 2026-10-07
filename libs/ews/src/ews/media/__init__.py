"""Media library (app ``media``): images, videos and audio of an organization in the tenant bucket
(``media/<organization_id>/…``), folders, favorites, trash, usages by other apps (sites).

Spec: taas-specs/media/media-app-spec.md. Documents (PDF, office files) belong to the Documents app.
"""

from foundation.http import BaseController

from ._service import record_usages, use_storage
from ._settings import MediaSettings, media_settings
from .controllers import MediaAssetController, MediaFolderController


def get_media_controllers() -> list[BaseController]:
    return [MediaFolderController(), MediaAssetController()]


__all__ = [
    'MediaSettings',
    'get_media_controllers',
    'media_settings',
    'record_usages',
    'use_storage',
]
