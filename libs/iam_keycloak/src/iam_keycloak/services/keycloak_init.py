from core.conf import get_app_settings
from core.conf.settings import AppSetting
from core.observability.log_factory import LogFactory
from keycloak import KeycloakAdmin, KeycloakOpenID

"""
def get_keycloak_openid() -> KeycloakOpenID:
    settings: AppSetting = get_app_settings()
    print(
        f"keycloak: {settings.KEYCLOAK_API}/{settings.KEYCLOAK_REALM}/{settings.KEYCLOAK_CLIENT_ID}"
    )
    return KeycloakOpenID(
        server_url=settings.KEYCLOAK_API,
        client_id=settings.KEYCLOAK_CLIENT_ID,
        client_secret_key=settings.KEYCLOAK_LOGIN_CLIENT_SECRET,
        realm_name=settings.KEYCLOAK_REALM,
        verify=settings.KEYCLOAK_SSL_VERIFY,
    )

"""


def get_keycloak_openid(realm: str = None) -> KeycloakOpenID:
    settings: AppSetting = get_app_settings()
    logger = LogFactory().get_logger(__name__)

    # if settings.SAAS_MODE:
    #     if not realm:
    #         raise ValueError('In SAAS mode, realm must be provided.')

    if not realm:
        if not settings.KEYCLOAK_REALM:
            raise ValueError(
                'Keycloak realm [KEYCLOAK_REALM] is not set in settings or provided as argument.'
            )
        else:
            realm = settings.KEYCLOAK_REALM  # type: ignore

    logger.debug(
        f'Initializing Keycloak OpenID: '
        f'server_url={settings.KEYCLOAK_API}, '
        f'realm={realm}, '
        f'client_id={settings.KEYCLOAK_CLIENT_ID}, '
        f'ssl_verify={settings.KEYCLOAK_SSL_VERIFY}'
    )

    return KeycloakOpenID(
        # realm_name='realm',
        server_url=settings.KEYCLOAK_API,
        client_id=settings.KEYCLOAK_CLIENT_ID,
        client_secret_key=settings.KEYCLOAK_LOGIN_CLIENT_SECRET,
        realm_name=realm,
        verify=settings.KEYCLOAK_SSL_VERIFY,
    )


def get_keycloak_admin(realm: str | None = None) -> KeycloakAdmin:
    settings = get_app_settings()
    logger = LogFactory().get_logger(__name__)

    if not realm:
        realm = settings.KEYCLOAK_REALM

    logger.debug(
        f'Initializing Keycloak Admin: '
        # f'realm_name: master, '
        f'user_realm_name: {realm}, '
        f'server_url={settings.KEYCLOAK_API}, '
        f'username={settings.KEYCLOAK_ADMIN_USER}, '
        f'ssl_verify={settings.KEYCLOAK_SSL_VERIFY}'
    )

    keycloak_admin = KeycloakAdmin(
        # realm_name='master',
        # user_realm_name='master',
        realm_name=realm,
        server_url=settings.KEYCLOAK_API,
        username=settings.KEYCLOAK_ADMIN_USER,
        password=settings.KEYCLOAK_ADMIN_SECRET,
        verify=settings.KEYCLOAK_SSL_VERIFY,
    )
    return keycloak_admin
