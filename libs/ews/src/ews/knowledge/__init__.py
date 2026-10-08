"""Knowledge Center (app ``knowledge``, API ``/api/v1/knowledge``): spaces with a visibility (tenant ·
organization ± sub-organizations · restricted) and space roles, a page tree per space, drafts / versions of site
documents, soft lock, owners + verification, templates, private attachments, home data and simple search.

Specs: taas-specs/knowledge/ (roadmap.md for the status). Access rules: ``_access``; guide: ``CLAUDE.md``.
"""

from foundation.http import BaseController

from ._access import KB_SPACES
from .controllers import (
    KnowledgeController,
    KnowledgePagesController,
    KnowledgeSpacesController,
)


def get_knowledge_controllers() -> list[BaseController]:
    return [
        KnowledgeController(),
        KnowledgeSpacesController(),
        KnowledgePagesController(),
    ]


__all__ = ['KB_SPACES', 'get_knowledge_controllers']
