from foundation.http.rest_client import CommonRestClient
from foundation.utils.singleton import singleton
from iam_keycloak.keycloak_settings import KeycloakSettings, get_keycloak_settings
from iam_keycloak.services.keycloak_init import get_keycloak_admin
from keycloak import KeycloakAdmin


@singleton
class KeycloakAdminRestClient(CommonRestClient):
    """
    A subclass of KeycloakAdmin that adds a method to get the access token.
    """

    _kc_admin: KeycloakAdmin

    def __init__(self):

        super().__init__(self.settings.KEYCLOAK_HOST)

    @property
    def settings(self) -> KeycloakSettings:
        """
        Get the Keycloak settings.

        Returns:
            KeycloakSettings: The Keycloak settings.
        """
        return get_keycloak_settings()

    @property
    def realm(self) -> str:
        """
        Get the Keycloak realm.

        Returns:
            str: The Keycloak realm.
        """
        return self.settings.KEYCLOAK_REALM


    def build_realm_url(self, sub_url: str | None = None) -> str:
        _url = self.build_url(f'/admin/realms/{self.keycloak.realm}')
        if sub_url:
            return self.join_url(_url, sub_url)
        return _url


    @property
    def keycloak(self) -> KeycloakAdmin:
        if not self._kc_admin:
            self._kc_admin = get_keycloak_admin()
        return self._kc_admin

    def admin_delete_session(self, session_id: str) -> dict:
        self.keycloak.raw_delete(path=self.build_realm_url(f'/sessions/{session_id}'))

    def admin_delete_all_session(self, user_id: str) -> dict:
        self.keycloak.raw_post(
            path=self.build_realm_url(f'/users/{user_id}/logout'), data={}
        )

    async def a_user_logout(self, user_id: str) -> dict:
        """
        Log out a user by their user ID.

        Args:
            user_id (str): The ID of the user to log out.

        Returns:
            dict: The response from the Keycloak server.
        """
        return await self.keycloak.a_user_logout(user_id)
