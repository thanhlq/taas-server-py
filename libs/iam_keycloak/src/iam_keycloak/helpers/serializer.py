import json
from datetime import datetime
from typing import Optional

from core.iam.domain.entities import UserEntity
from core.iam.domain.entities.user import TaxNumber
from core.iam.domain.schemas.auth import UserRegistrationForm
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


def user_registration_form_to_keycloak_data(
    registration_data: UserRegistrationForm,
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
        'attributes': {'origin': 'taas'},
    }
    return kc_user_data


def parse_keycloak_data(user: dict) -> 'UserEntity':
    _user = {camel_to_snake(key): value for key, value in user.items()}
    attributes = _user.pop('attributes', None)

    if 'preferred_username' not in _user and 'username' in _user:
        _user['preferred_username'] = _user.get('username', None)

    print(f'_user after username set: {_user}')

    keycloak_user = UserEntity(**_user)

    if attributes:
        for key in attributes:
            attribute = attributes[key]
            if not attribute:
                continue

            snake_case_key = camel_to_snake(key)
            if (
                attribute
                and isinstance(attribute, list)
                and len(attribute) == 1
                and key not in user_attributes_json_fields
            ):
                attribute = attribute[0]

            attribute_type = UserEntity.__annotations__.get(snake_case_key)

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
            elif key in user_attributes_json_fields:
                attribute = [TaxNumber(**json.loads(tax)) for tax in attribute]

            if hasattr(keycloak_user, snake_case_key):
                setattr(keycloak_user, snake_case_key, attribute)
            else:
                print(f'Unknown KeycloakUser attribute: {snake_case_key}')
    return keycloak_user


def convert_user_to_keycloak_user_data(user: UserEntity) -> 'dict':
    """
    Convert User to keycloak user data dictionary for Keycloak API
    """
    ignore_attributes = [
        # OpenID attributes
        'sub',
        'preferred_username',
        'given_name',
        'family_name',
        'name',
        # properties used by Authentication Middleware
        'is_authenticated',
        'display_name',
        'identity',
        # other Keycloak attributes that should be read-only
        'created_timestamp',
        'not_before',
        'totp',
        'disableable_credential_types',
        'access',
        'created_on',
        'full_name',
        'set_attributes',
        'attributes',
        'address',
        'json',
        'dict',
        'phone1_formated',
        'phone2_formated',
        'custom_tags_formated',
        'date_of_birth_formated',
        'created_on_formated',
        'address_country_formated',
    ]

    # Keycloak User Representation for JSON fields:
    # https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation
    # Use this attributes to identify custom attributes that we added to KeycloakUser model
    keycloak_user_representation_attrs = [
        'access',
        'attributes',
        'clientConsents',
        'clientRoles',
        'createdTimestamp',
        'credentials',
        'disableableCredentialTypes',
        'email',
        'emailVerified',
        'enabled',
        'federatedIdentities',
        'federationLink',
        'firstName',
        'groups',
        'id',
        'lastName',
        'notBefore',
        'origin',
        'realmRoles',
        'requiredActions',
        'self',
        'serviceAccountClientId',
        'username',
    ]

    user_dict = {}
    user_class_properties = dir(user)
    user_class_properties = [
        cp
        for cp in user_class_properties
        if cp not in ignore_attributes and not cp.startswith('__') and not callable(cp)
    ]
    for cp in user_class_properties:
        attr = getattr(user, cp)
        if isinstance(attr, datetime):
            attr = str(attr)
        camel_case_attr = snake_to_camel(cp)
        if camel_case_attr in keycloak_user_representation_attrs:
            user_dict[camel_case_attr] = attr
        else:
            if camel_case_attr == 'taxNumbers' and attr is not None:
                user_dict['attributes'][camel_case_attr] = [tax.json() for tax in attr]
            else:
                user_dict['attributes'][camel_case_attr] = attr
    return user_dict
