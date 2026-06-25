from typing import Optional, Any
from core.observability.error_reporter import report_error
from keycloak import KeycloakError

from ..utils import parse_keycloak_error


def report_keycloak_error(e: KeycloakError | Exception, title, logger, extra_context: Optional[Any] = None) -> str:
    error_msg = None
    if isinstance(e, KeycloakError):
        error_msg = parse_keycloak_error(e)
    else:
        error_msg = str(e)

    extra_context = extra_context or {'keycloak_error': error_msg }

    report_error(
        e, title=title, extra_context=extra_context, logger=logger
    )
    return error_msg
