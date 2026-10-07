from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

type AuthMode = Literal['iam', 'dev']


@dataclass(frozen=True, slots=True)
class EwsAuthSettings:
    """Request authentication of the EWS business apps (``.env`` §EWS authentication).

    - ``iam``: the caller's IAM session cookie / bearer token is verified by the TaaS IAM
      (``GET {IAM_INTERNAL_URL}/api/v1/auth/session``), then the user, tenant and organization come
      from the shared directory tables and permissions from ``taas_casbin_rule``.
    - ``dev``: development sign-in of the web apps (readable ``taas_dev_session`` cookie): every
      permission is granted. Never in production.
    """

    mode: AuthMode = 'iam'
    iam_url: str = 'http://localhost:8301'
    cache_seconds: int = 30
    dev_organization_id: str | None = None

    @staticmethod
    def from_env() -> EwsAuthSettings:
        mode = (os.environ.get('EWS_AUTH_MODE') or 'iam').strip().lower()
        if mode not in ('iam', 'dev'):
            raise ValueError(f'EWS_AUTH_MODE must be iam or dev, got {mode!r}')
        return EwsAuthSettings(
            mode=mode,  # type: ignore[arg-type]
            iam_url=(os.environ.get('IAM_INTERNAL_URL') or 'http://localhost:8301').rstrip('/'),
            cache_seconds=int(os.environ.get('EWS_AUTH_CACHE_SECONDS') or 30),
            dev_organization_id=os.environ.get('EWS_DEV_ORGANIZATION_ID') or None,
        )


@lru_cache(maxsize=1)
def auth_settings() -> EwsAuthSettings:
    return EwsAuthSettings.from_env()
