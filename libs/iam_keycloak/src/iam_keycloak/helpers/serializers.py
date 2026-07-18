import json
from typing import Any, Optional

from dateutil import parser
from foundation.utils.str_utils import camel_to_snake
from iam.auth.schemas import SignupRequest
from iam.auth.types import DirectoryTenant, DirectoryUser
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


def user_registration_form_to_keycloak_data(
    registration_data: SignupRequest
) -> dict:
    """
    Convert UserRegistrationForm to keycloak user data dictionary for Keycloak API
    """
    kc_user_data = {
        # 'id': user_id,
        'email': registration_data.email,
        'username': registration_data.email,
        'firstName': registration_data.first_name,
        'lastName': registration_data.last_name,
        # 'displayName': f'{registration_data.first_name} {registration_data.last_name}',
        'password': registration_data.password,
        'emailVerified': False,
        'enabled': True,
    }
    return kc_user_data


def parse_keycloak_user_data(user: dict) -> 'DirectoryUser':
    _user = {camel_to_snake(key): value for key, value in user.items()}
    attributes = _user.pop('attributes', None)

    keycloak_user = DirectoryUser(**_user)

    if attributes:
        for key in attributes:
            attribute = attributes[key]
            if not attribute:
                continue

            _snake_case_key = camel_to_snake(key)
            if (
                attribute
                and isinstance(attribute, list)
                and len(attribute) == 1
                and key not in user_attributes_json_fields
            ):
                attribute = attribute[0]

            attribute_type = DirectoryUser.__annotations__.get(_snake_case_key)

            if attribute_type == 'datetime':
                attribute = parser.parse(attribute)
            elif (
                attribute_type == bool
                or attribute_type == Optional[bool]
                and not isinstance(attribute, bool)
            ):
                if isinstance(attribute, str):
                    attribute = attribute.lower() == 'true'
                else:
                    attribute = attribute == 'true'
            # elif key in user_attributes_json_fields:
            #     attribute = [TaxNumber(**json.loads(tax)) for tax in attribute]

            if hasattr(keycloak_user, _snake_case_key):
                setattr(keycloak_user, _snake_case_key, attribute)
            else:
                print(f'Unknown KeycloakUser attribute: {_snake_case_key}')
    return keycloak_user


def parse_keycloak_registered_user(kc_user: dict[str, Any]) -> DirectoryUser:
    """
    {
    "email": "ngocle1401@gmail.com",
    "username": "ngocle1401@gmail.com",
    "firstName": "Ngoc",
    "lastName": "Le",
    "emailVerified": True,
    "enabled": True,
    "attributes": {
        "origin": "taas",
        "tenant_id": "4282157c-26ff-457e-8c44-2f24703c3205",
        "is_root_account": True
    },
    "credentials": [
        {
        "value": "....",
        "type": "password"
        }
    ],
    "id": "f1308231-8316-40df-aa5b-1dab983ab245"
    }
    """
    user = DirectoryUser(
        id=kc_user['id'],
        email=kc_user['email'],
        username=kc_user['username'],
        first_name=kc_user['firstName'],
        last_name=kc_user['lastName'],
        email_verified=kc_user['emailVerified'],
        enabled=kc_user['enabled'],
        tenant_id=kc_user['attributes'].get('tenant_id', None),
        is_root_account=kc_user['attributes'].get('is_root_account', False),
    )
    return user


def parse_keycloak_registered_organization(kc_user: dict[str, Any]) -> DirectoryTenant:
    """
       {
    `       "name": "Ngoc Test Org 8227",
           "alias": "ngoc-test-org-8227",
           "domains": [
               "ngoc-test-org-8227.eworksuite.local"
           ],
           "id": "4282157c-26ff-457e-8c44-2f24703c3205"
           }`
    """
    tenant = DirectoryTenant(
        id=kc_user['id'],
        name=kc_user['name'],
        alias_id=kc_user['alias'],
        # domains=kc_user['domains'],
    )
    return tenant
