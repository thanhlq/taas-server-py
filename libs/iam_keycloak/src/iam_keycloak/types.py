"""
Contains types and domain models specific to Keycloak integration for IAM (Identity and Access Management).
"""
from enum import StrEnum
from typing import Optional

from foundation.serialization import BaseModel

# region KEYCLOAK NATIVE TYPES

# endregion


class KeycloakSupportedLocale(StrEnum):
    DE = 'de'
    NO = 'no'
    RU = 'ru'
    SV = 'sv'
    PT_BR = 'pt-BR'
    LT = 'lt'
    EN = 'en'
    IT = 'it'
    FR = 'fr'
    HU = 'hu'
    ZH = 'zh-CN'
    ES = 'es'
    CS = 'cs'
    JA = 'ja'
    SK = 'sk'
    PL = 'pl'
    DA = 'da'
    CA = 'ca'
    NL = 'nl'
    TR = 'tr'

    @staticmethod
    def as_list():
        return [c.value for c in KeycloakSupportedLocale]


class KeycloakRequiredActions(StrEnum):
    UPDATE_USER_LOCALE = 'update_user_locale'
    TERMS_AND_CONDITIONS = 'TERMS_AND_CONDITIONS'
    CONFIGURE_TOTP = 'CONFIGURE_TOTP'
    VERIFY_EMAIL = 'VERIFY_EMAIL'
    UPDATE_PASSWORD = 'UPDATE_PASSWORD'
    UPDATE_PROFILE = 'UPDATE_PROFILE'

class KeycloakDomain(BaseModel):
    name: str
    verified: bool = False

class KeycloakOrganization(BaseModel):
    id: str
    name: str
    enabled: str
    alias: Optional[str] = None
    parent_id: Optional[str] = None
    domains: list[KeycloakDomain] = []
