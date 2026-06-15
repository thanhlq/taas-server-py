"""Specific database types"""

import json
from typing import Any, Dict, Optional

from sqlalchemy import JSON, TypeDecorator


class JSONText(TypeDecorator):
    """A custom type that stores dict as JSON text and loads it back as dict"""

    impl = JSON
    cache_ok = True

    def process_result_value(
        self, value: Optional[Any], dialect
    ) -> Dict[Any, Any] | None:
        """
        Ensure we always return a dict
        """

        # For NoneType
        if value is None:
            return None

        # Seems child object have type dict already
        if isinstance(value, dict):
            return value

        # For type TEXT, ie. address balances
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError, TypeError:
                return {}

        return {}
