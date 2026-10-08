"""Media library (app ``media``): images, videos and audio of an organization in the tenant bucket
(``media/<organization_id>/…``), folders, favorites, trash, usages by other apps (sites, blog), and the public
CDN copies of published media shared by every publishing app (``_publishing``: ``asset_map``, ``publish_assets``,
``remove_public_scope``).

Spec: taas-specs/media/media-app-spec.md. Documents (PDF, office files) belong to the Documents app.
"""

from foundation.http import BaseController

from ews.shared import use_storage  # the shared private-storage override (kept here for compatibility)

from ._publishing import (
    asset_map,
    public_store,
    publish_assets,
    remove_public_scope,
    use_public_store,
)
from ._service import record_usages
from ._settings import MediaSettings, media_settings
from .controllers import MediaAssetController, MediaFolderController


def get_media_controllers() -> list[BaseController]:
    return [MediaFolderController(), MediaAssetController()]


__all__ = [
    'MediaSettings',
    'asset_map',
    'get_media_controllers',
    'media_settings',
    'public_store',
    'publish_assets',
    'record_usages',
    'remove_public_scope',
    'use_public_store',
    'use_storage',
]
