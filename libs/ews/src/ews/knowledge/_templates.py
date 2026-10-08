"""Built-in page templates (Kb-0301): one JSON file per template in ``data/templates`` — ``key``, ``order``,
``name``, ``description``, ``icon``, ``title`` (default page title) and ``doc`` (a site document). English texts;
the web translates by ``key``. Tenant templates: 🚧."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from foundation.exceptions import ClientException

_DIR = Path(__file__).parent / 'data' / 'templates'


@lru_cache(maxsize=1)
def templates() -> tuple[dict[str, Any], ...]:
    loaded = [json.loads(p.read_text(encoding='utf-8')) for p in _DIR.glob('*.json')]
    return tuple(sorted(loaded, key=lambda t: (t.get('order', 99), t['key'])))


def get_template(key: str) -> dict[str, Any]:
    """A deep copy of the template ``key`` (400 when unknown)."""
    for template in templates():
        if template['key'] == key:
            return copy.deepcopy(template)
    raise ClientException(detail=f'unknown template {key!r}')
