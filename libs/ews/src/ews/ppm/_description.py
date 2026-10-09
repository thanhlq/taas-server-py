"""Item descriptions as **site documents** (ADR-35): the same document, validator and editor (Visual · Markdown) as
Knowledge pages and Blog posts (``ews.sites._document``). The document is the source; ``description`` = its plain
text (search, My Work, e-mails), ``html_text`` = the rich text the client renders for older readers."""

from __future__ import annotations

from typing import Any

from foundation.exceptions import ValidationException

from ews.sites._document import plain_text, validate_document

MAX_TEXT = 100_000


def check_description(doc: Any) -> dict[str, Any]:
    """The document when valid, else 400 with every issue in ``extra.issues``."""
    if issues := [str(i) for i in validate_document(doc)]:
        raise ValidationException(
            detail=f'invalid description: {issues[0]}', extra={'issues': issues}
        )
    return doc


def description_text(doc: dict[str, Any]) -> str:
    return plain_text(doc, limit=MAX_TEXT)
