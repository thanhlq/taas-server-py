"""Page bodies are the **site document** ``{schemaVersion, sections}`` of the Site Builder (one block catalog, one
validator, one web editor with a Markdown mode — ``@taas/site-blocks``). This module is the knowledge side of
that contract: validation errors as 400, plain text for search."""

from __future__ import annotations

from typing import Any

from foundation.exceptions import ValidationException

from ews.sites._document import (
    SCHEMA_VERSION,
    empty_document,
    migrate_document,
    plain_text,
    validate_document,
)

__all__ = [
    'SCHEMA_VERSION',
    'check_document',
    'empty_document',
    'migrate_document',
    'search_text',
]


def check_document(doc: Any) -> dict[str, Any]:
    """The document when valid, else 400 with every issue in ``extra.issues``."""
    if issues := [str(i) for i in validate_document(doc)]:
        raise ValidationException(
            detail=f'invalid document: {issues[0]}', extra={'issues': issues}
        )
    return doc


def search_text(doc: dict[str, Any]) -> str:
    """Plain text of a published body (simple search, Kb-0104)."""
    return plain_text(doc, limit=100_000)
