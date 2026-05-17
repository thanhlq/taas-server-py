"""Generate an initial RS256 JWKS file for the IdP.

    uv run python -m iam_oauth.tools.gen_jwks > config/secrets/oauth_jwks_private.json
"""

from __future__ import annotations

import json
import sys
import uuid

from authlib.jose import JsonWebKey


def main() -> int:
    key = JsonWebKey.generate_key('RSA', 2048, options={'kid': uuid.uuid4().hex, 'use': 'sig', 'alg': 'RS256'}, is_private=True)
    jwks = {'keys': [key.as_dict(is_private=True)]}
    json.dump(jwks, sys.stdout, indent=2)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
