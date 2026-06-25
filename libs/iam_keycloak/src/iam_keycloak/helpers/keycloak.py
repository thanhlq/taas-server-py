from core.common.utils import join_urls
from core.conf import get_app_settings
from core.iam.domain.entities import UserEntity
from core.observability.log_factory import LogFactory
from keycloak import KeycloakAdmin, KeycloakOpenID

from ..services.keycloak_init import get_keycloak_admin
from .serializers import convert_user_to_keycloak_user_data


class KeycloakConfig:
    """
    The Keycloak configuration manager - to manage everything at config level.
    """

    settings = get_app_settings()

    @property
    def realm(self) -> str:
        return self.settings.KEYCLOAK_REALM

    @property
    def ssl_verify(self) -> str:
        return self.settings.KEYCLOAK_SSL_VERIFY

    @property
    def host(self) -> str:
        return self.settings.KEYCLOAK_API


class KeycloakRestAdmin(KeycloakConfig):
    _keycloak: KeycloakAdmin
    _realm_base_path: str

    def __init__(self, keycloak: KeycloakAdmin):
        settings = get_app_settings()
        self._keycloak = keycloak
        self._realm_base_path = join_urls(
            settings.KEYCLOAK_API, f'/admin/realms/{self._keycloak.realm}'
        )

    @property
    def keycloak_admin(self) -> KeycloakAdmin:
        return self._keycloak

    def build_realm_url(self, path: str) -> str:
        return join_urls(self._realm_base_path, path)

    def admin_delete_session(self, session_id: str) -> dict:
        self._keycloak.raw_delete(path=self.build_realm_url(f'/sessions/{session_id}'))

    def admin_delete_all_session(self, user_id: str) -> dict:
        self._keycloak.raw_post(
            path=self.build_realm_url(f'/users/{user_id}/logout'), data={}
        )


class KeycloakServerAdmin(KeycloakConfig):
    """
    The Keycloak server admin manager - to manage everything at server level.
    """

    _client = None
    _keycloak: KeycloakAdmin
    _rest_admin: KeycloakRestAdmin

    logger = LogFactory().get_logger('FastAPICache')

    def __init__(self):
        self.settings = get_app_settings()
        self._keycloak = get_keycloak_admin()
        # self._rest_admin = KeycloakRestAdmin(self._keycloak)

    @property
    def keycloak_admin(self) -> KeycloakAdmin:
        if not self._keycloak:
            self._keycloak = get_keycloak_admin()

        return self._keycloak

    @property
    def rest_admin(self) -> KeycloakRestAdmin:
        if not self._rest_admin:
            self._rest_admin = KeycloakRestAdmin(self._keycloak)
        return self._rest_admin

    @property
    def client_id(self) -> str:
        return self.settings.KEYCLOAK_LOGIN_CLIENT_ID

    @property
    def keycloak_openid_connect(self, realm: str, client_id: str) -> KeycloakOpenID:
        realm = realm or self.realm
        client_id = client_id or self.client_id

        openid = KeycloakOpenID(
            server_url=self.host,
            client_id=client_id,
            realm_name=realm,
            verify=self.ssl_verify,
        )
        return openid

    async def create_organization(self, org_data: dict) -> dict:
        """
        see https://www.keycloak.org/docs-api/latest/rest-api/index.html#OrganizationRepresentation
        """
        self.logger.debug(
            f'Creating organization in Keycloak under realm {self.realm} with data: {org_data}'
        )
        id = await self.keycloak_admin.a_create_organization(org_data)
        org_data['id'] = id
        return org_data

    async def create_user(
        self, user_data: dict, verified_email: bool | None = False
    ) -> dict:
        self.logger.debug(
            f'Creating user in Keycloak under realm {self.realm} with data: {user_data}'
        )
        password = user_data.pop('password', None)
        # user = User(**user_data)

        user_data['credentials'] = [
            {
                'value': password,
                'type': 'password',
            }
        ]
        if verified_email:
            user_data['emailVerified'] = True
        else:
            user_data['emailVerified'] = False

        id = await self.keycloak_admin.a_create_user(user_data, exist_ok=False)
        user_data['id'] = id
        return user_data

    async def add_user_to_organization(self, user_id: str, org_id: str) -> dict:
        self.logger.debug(f'Adding user {user_id} to organization {org_id} in Keycloak')
        kc_resp = await self.keycloak_admin.a_organization_user_add(user_id, org_id)
        return kc_resp

    # async def get_client(self) -> dict:
    #     return self.keycloak.client()

    # @property
    # async def client_id(self) -> str:
    #     client = await self.client
    #     return client.get('id')
