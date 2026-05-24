from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Final, Literal, Sequence

from fastapi.openapi.models import Server

if TYPE_CHECKING:
    from platform_core.openapi.spec.license import License
    from platform_core.openapi.spec.security_requirement import SecurityRequirement

__all__ = ('OpenAPIConfig',)

_enabled_plugin_map = {
    'oauth2-redirect.html': None,
}

_DEFAULT_SCHEMA_SITE: Final = 'redoc'


@dataclass
class OpenAPIConfig:
    """Configuration for OpenAPI.

    To enable OpenAPI schema generation and serving, pass an instance of this class to the
    :class:`Litestar <.app.Litestar>` constructor using the ``openapi_config`` kwargs.
    """

    title: str
    """Title of API documentation."""
    version: str
    """API version, e.g. '1.0.0'."""

    create_examples: bool = field(default=False)
    """Generate examples using the polyfactory library."""
    random_seed: int = 10
    """The random seed used when creating the examples to ensure deterministic generation of examples."""
    """API contact information, should be an :class:`Contact <litestar.openapi.spec.contact.Contact>` instance."""
    description: str | None = field(default=None)
    """API description."""
    """Links to external documentation.

    Should be an instance of :class:`ExternalDocumentation <litestar.openapi.spec.external_documentation.ExternalDocumentation>`.
    """
    license: License | None = field(default=None)
    """API Licensing information.

    Should be an instance of :class:`License <litestar.openapi.spec.license.License>`.
    """
    security: list[SecurityRequirement] | None = field(default=None)
    """API Security requirements information.

    Should be an instance of
        :data:`SecurityRequirement <.openapi.spec.SecurityRequirement>`.

    Should be an instance of :class:`Components <litestar.openapi.spec.components.Components>` or a list thereof.
    """
    servers: list[Server] = field(default_factory=lambda: [Server(url='/')])
    """A list of :class:`Server <litestar.openapi.spec.server.Server>` instances."""
    summary: str | None = field(default=None)
    """A summary text."""
