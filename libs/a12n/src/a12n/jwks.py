"""JWKS (private + public) management.

For v1 we load a JWKS document from disk; rotation is a manual operation
(swap files + reload). A future iteration can implement scheduled rotation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from authlib.jose import JsonWebKey, KeySet


class JWKSManager:
    def __init__(self, *, private_jwks_path: str):
        self._path = Path(private_jwks_path)
        self._private_keys: KeySet = self._load()

    def _load(self) -> KeySet:
        if not self._path.exists():
            raise FileNotFoundError(
                f'JWKS private key file not found at {self._path}. '
                'Generate one with `python -m iam_oauth.tools.gen_jwks`.'
            )
        data = json.loads(self._path.read_text())
        return JsonWebKey.import_key_set(data)

    @property
    def signing_key(self) -> Any:
        """Pick the first key whose ``use`` is ``sig``."""
        for key in self._private_keys.keys:
            if key.tokens.get('use', 'sig') == 'sig':
                return key
        return self._private_keys.keys[0]

    def public_jwks(self) -> dict:
        """Public JWKS document suitable for ``/.well-known/jwks.json``."""
        return {
            'keys': [k.as_dict(is_private=False) for k in self._private_keys.keys]
        }

    def reload(self) -> None:
        self._private_keys = self._load()
