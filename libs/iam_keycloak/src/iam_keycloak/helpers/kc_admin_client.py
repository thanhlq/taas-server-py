from typing import Any

from foundation.cli import cli
from foundation.observability.log_factory import LogFactory
from keycloak import KeycloakAdmin, KeycloakOpenID

from .kc_admin_rest_client import KeycloakAdminRestClient


class keycloaiAdminClient:
    """
    The Keycloak server admin manager - to manage everything at server level.
    """

    _rest_admin: KeycloakAdminRestClient | None = None
    _realm_id: str | None = None
    """ Normally querying from keycloak admin service from realm name """

    logger = LogFactory().get_logger('FastAPICache')

    async def get_realm_info(self, realm_name: str) -> dict[str, Any]:
        """
        Get information about a specific realm in Keycloak.

        Args:
            realm_name (str): The name of the realm to retrieve information for.
        Returns:
            dict: Information about the specified realm.
        """
        _r = await self.keycloak_admin.a_get_realm(realm_name)
        # print_dict_pretty(_r, f'Keycloak realm info for {realm_name}')
        cli.info_table('Keycloak realm info', _r)
        return _r

    @property
    def realm_id(self) -> str | None:
        """
        Get the ID of the realm currently being managed by the Keycloak admin client.

        Returns:
            str | None: The ID of the realm, or None if no realm is set.
        """
        return self._realm_id

    async def get_realm_id(self, realm_name: str) -> str:
        if self._realm_id:
            return self._realm_id
        realm_info = await self.get_realm_info(realm_name)
        self._realm_id = realm_info.get('id')
        return self._realm_id

    @property
    def rest_admin(self) -> KeycloakAdminRestClient:
        if not self._rest_admin:
            self._rest_admin = KeycloakAdminRestClient()
        return self._rest_admin

    @property
    def keycloak_admin(self) -> KeycloakAdmin:
        return self.rest_admin.keycloak

    @property
    def client_id(self) -> str:
        return self.rest_admin.settings.KEYCLOAK_LOGIN_CLIENT_ID

    @property
    def host(self) -> str:
        return self.rest_admin.settings.KEYCLOAK_HOST

    @property
    def ssl_verify(self) -> bool:
        return self.rest_admin.settings.KEYCLOAK_SSL_VERIFY

    @property
    def realm(self) -> str:
        return self.rest_admin.realm

    def keycloak_openid_connect(
        self, realm: str | None = None, client_id: str | None = None
    ) -> KeycloakOpenID:
        realm = realm or self.realm
        client_id = client_id or self.client_id

        openid = KeycloakOpenID(
            server_url=self.host,
            verify=self.ssl_verify,
            client_id=client_id,
            realm_name=realm,
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

    async def loggout_user(self, user_id: str) -> dict:
        """
        Log out a user by their user ID.

        Args:
            user_id (str): The ID of the user to log out.

        Returns:
            dict: The response from the Keycloak server.
        """
        return await self.keycloak_admin.a_user_logout(user_id)

    async def add_user_to_organization(self, user_id: str, org_id: str) -> Any:
        self.logger.debug(f'Adding user {user_id} to organization {org_id} in Keycloak')
        kc_resp = await self.keycloak_admin.a_organization_user_add(user_id, org_id)
