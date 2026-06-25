from typing import Optional

from keycloak import KeycloakAdmin, KeycloakOpenID


class KeycloakRealmAdmin(KeycloakAdmin):
    _client = None

    def __init__(self, realm: str, config: dict):
        self.realm = realm
        self.config = config
        super().__init__(
            server_url=self.host,
            realm_name=self.realm,
            password=self.admin_password,
            username=self.admin_username,
            verify=config.get('SSL_VERIFY', ''),
            # auto_refresh_token=['get', 'post', 'put', 'delete'],
        )

    @property
    def admin_username(self) -> str:
        return self.config['ADMIN_USER']

    @property
    def admin_password(self) -> str:
        return self.config['ADMIN_SECRET']

    @property
    def client(self) -> dict:
        if not self._client:
            client_id = self.get_client_id(self.config.get('CLIENT_ID'))
            self._client = self.get_client(client_id)

        return self._client

    @property
    def host(self) -> str:
        return self.config['HOST']

    def connect(self, realm: str, client_id: str) -> KeycloakOpenID:
        keycloak_openid = KeycloakOpenID(
            server_url=self.host,
            client_id=client_id,
            realm_name=self.config.get('REALM_PREFIX', '') + realm,
            verify=self.config.get('SSL_VERIFY', ''),
        )
        return keycloak_openid

    def get_user_id(self, search: str) -> Optional[str]:
        lower_search_prompt = search.lower()
        users = self.get_users(
            query={'search': lower_search_prompt, 'max': 1, 'exact': True}
        )
        return users[0]['id'] if len(users) == 1 else None
