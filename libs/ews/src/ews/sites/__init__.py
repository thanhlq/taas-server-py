"""Site builder (app ``sites``): sites per organization, page tree with revisions, block documents
(visual + Markdown modes share one JSON document), themes, menus, redirects, releases and rollback,
preview links, form submissions, AI assist, and the internal read API of the public site renderer.

Specs: taas-specs/site-builder/ (roadmap.md for the status). Media come from ``ews.media``.
"""

from foundation.http import BaseController

from ._document import block_catalog, validate_document
from ._settings import SitesSettings, sites_settings
from .controllers import SitePagesController, SitePublishingController, SitesController, SitesInternalController


def get_sites_controllers() -> list[BaseController]:
    return [SitesController(), SitePagesController(), SitePublishingController(), SitesInternalController()]


__all__ = ['SitesSettings', 'block_catalog', 'get_sites_controllers', 'sites_settings', 'validate_document']
