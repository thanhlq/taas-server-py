from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _int(key: str, default: int) -> int:
    value = os.environ.get(key)
    return int(value) if value not in (None, '') else default


@dataclass(frozen=True, slots=True)
class SitesSettings:
    """Site builder settings (``.env`` §Site builder); decisions: taas-specs/site-builder/decisions.md."""

    domain: str = 'sites.localhost'
    """``SITES_DOMAIN``: registrable domain of the public sites, never the app domain (Site-0600)."""
    scheme: str = 'http'
    port: int | None = 7300
    """Public port of the renderer in development (``None`` / empty = default port)."""
    renderer_key: str | None = None
    """Shared secret of the site renderer (``X-Sites-Renderer-Key``) for ``/api/v1/sites-internal``."""
    preview_max_days: int = 7
    max_sites: int = 20
    """Plan limit per tenant (Site-0004); 0 = unlimited."""
    max_pages: int = 300
    """Plan limit per site; 0 = unlimited."""
    form_rate_per_minute: int = 5
    """Form submissions per visitor (IP hash) and site per minute (Site-0635)."""

    def org_host(self, org_slug: str) -> str:
        return f'{org_slug}.{self.domain}'

    def public_url(self, org_slug: str, path: str = '/') -> str:
        port = f':{self.port}' if self.port and self.port not in (80, 443) else ''
        return f'{self.scheme}://{self.org_host(org_slug)}{port}{path}'

    @staticmethod
    def from_env() -> SitesSettings:
        port = os.environ.get('SITES_PUBLIC_PORT')
        return SitesSettings(
            domain=(os.environ.get('SITES_DOMAIN') or 'sites.localhost').strip().lower(),
            scheme=(os.environ.get('SITES_PUBLIC_SCHEME') or 'http').strip().lower(),
            port=int(port) if port and port.strip() else (None if port is not None else 7300),
            renderer_key=os.environ.get('SITES_RENDERER_KEY') or None,
            preview_max_days=min(_int('SITES_PREVIEW_MAX_DAYS', 7), 7),
            max_sites=_int('SITES_MAX_SITES', 20),
            max_pages=_int('SITES_MAX_PAGES', 300),
            form_rate_per_minute=_int('SITES_FORM_RATE_PER_MINUTE', 5),
        )


@lru_cache(maxsize=1)
def sites_settings() -> SitesSettings:
    return SitesSettings.from_env()
