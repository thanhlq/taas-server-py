"""
Contains types and domain models specific to Keycloak integration for IAM (Identity and Access Management).
"""

from enum import Enum

# region KEYCLOAK NATIVE TYPES

# endregion


class KeycloakSupportedLocale(str, Enum):
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


class KeycloakRequiredActions(str, Enum):
    UPDATE_USER_LOCALE = 'update_user_locale'
    TERMS_AND_CONDITIONS = 'TERMS_AND_CONDITIONS'
    CONFIGURE_TOTP = 'CONFIGURE_TOTP'
    VERIFY_EMAIL = 'VERIFY_EMAIL'
    UPDATE_PASSWORD = 'UPDATE_PASSWORD'
    UPDATE_PROFILE = 'UPDATE_PROFILE'
