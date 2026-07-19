"""A utility to manage endpoints that allow any access (no authentication required)"""

import re

__auth_allow_any_endpoints = set()


def is_endpoint_allow_any(endpoint: str) -> bool:
    """
    Can anyone access this endpoint?
    """
    global __auth_allow_any_endpoints
    for _endpoint in __auth_allow_any_endpoints:
        if re.match(_endpoint, endpoint):
            return True
    return False


def mark_endpoint_as_allow_any(endpoint: str):
    global __auth_allow_any_endpoints
    __auth_allow_any_endpoints.add(endpoint)
