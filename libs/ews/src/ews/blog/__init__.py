"""Blog (app ``blog``): blogs per organization, posts whose body is the Site Builder document (revisions: draft
→ live), editorial workflow (submit → review → publish / schedule), categories, tags, author profiles, members
on ``blog:<id>``, public addresses + releases read by the site renderer. API ``/api/v1/blog/*`` and
``/api/v1/sites-internal/blog-*``, tables ``taas_blog_*``.

Specs: taas-specs/blog/ (blog-app-spec.md, blog-publishing-spec.md, blog-api.md, roadmap.md).
"""

from foundation.http import BaseController

from ews.sites import register_route_source

from ._access import BLOG
from ._release import blog_routes, rebuild_missing_releases
from ._workflow import publish_due
from .controllers import (
    BlogController,
    BlogInternalController,
    BlogPostsController,
    BlogTaxonomyController,
    BlogWorkflowController,
)


def get_blog_controllers() -> list[BaseController]:
    register_route_source(blog_routes)  # blog routes in the renderer's routing table
    return [
        BlogController(),
        BlogPostsController(),
        BlogWorkflowController(),
        BlogTaxonomyController(),
        BlogInternalController(),
    ]


__all__ = ['BLOG', 'get_blog_controllers', 'publish_due', 'rebuild_missing_releases']
