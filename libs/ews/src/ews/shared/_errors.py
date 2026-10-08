"""HTTP errors the business modules share beyond ``foundation.exceptions``."""

from __future__ import annotations

from foundation.exceptions import ClientException


class ConflictException(ClientException):
    """409: the request clashes with the current state (slug taken, locked, invalid status transition, …);
    ``extra={'code': …}`` names the case for the UI."""

    status_code = 409
