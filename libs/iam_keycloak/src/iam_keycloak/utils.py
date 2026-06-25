import json
from datetime import datetime
from typing import Optional

from core.iam.domain.entities.user import TaxNumber
from core.utils.string_utils import camel_to_snake, snake_to_camel
from dateutil import parser
from keycloak import KeycloakError


def parse_keycloak_error(e: KeycloakError) -> str:
    error = e.error_message.decode('utf-8')
    error_message = json.loads(error)
    error = error_message.get('errorMessage', None)
    if error is None:
        error = error_message.get('error_description', None)
        if error is None:
            error = error_message.get('error', None)
    return error


user_attributes_json_fields = ['taxNumbers']
