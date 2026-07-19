"""
Keycloak Starlette Authentication Backend Middleware
 - Used to integrate Keycloak authentication with Starlette/FastAPI applications
 - Implements the AuthenticationBackend interface from Starlette
 - Authenticates requests using Keycloak tokens
 - Supports unauthenticated access for specific endpoints
 - Handles authentication errors gracefully
 - Logs detailed information for debugging authentication issues
 - Extracts tokens from Authorization headers or cookies
 - Validates tokens using Keycloak's userinfo endpoint
 - Returns authenticated user information as IamUser entity

"""
from foundation.logger import debug_exception
from typing import Optional

from fastapi.requests import HTTPConnection
from foundation.observability.log_factory import LogFactory
from foundation.state.endpoint import is_endpoint_allow_any
from foundation.utils.cookie_parser import parse_cookies
from keycloak.exceptions import KeycloakAuthenticationError, KeycloakGetError
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    BaseUser,
    UnauthenticatedUser,
)

from ..domains.entities import KeycloakAuthUser
from ..services.keycloak_init import get_keycloak_openid


class KeycloakOpenIDAuthBackend(AuthenticationBackend):
    async def authenticate(
        self, conn: HTTPConnection
    ) -> Optional[tuple[AuthCredentials, BaseUser]]:
        endpoint: str = conn.scope.get('path')

        logger = LogFactory().get_logger(__name__)

        # Always allow OPTIONS requests, so Nuxt Auth lib and FastAPI CORS middleware can handle CORS properly
        if conn.scope.get('method', None) == 'OPTIONS':
            return AuthCredentials(['unauthenticated']), UnauthenticatedUser()

        auth_header = conn.headers.get('Authorization')
        cookie_header = conn.headers.get(
            'Cookie'
        )  # websockets connections only have a cookie

        logger.debug(
            f'Authentication attempt for endpoint: {endpoint}, method: {conn.scope.get("method")}'
        )
        logger.debug(
            f'Auth header present: {bool(auth_header)}, Cookie header present: {bool(cookie_header)}'
        )

        if not auth_header:
            if is_endpoint_allow_any(endpoint):
                logger.debug(
                    f"Endpoint '{endpoint}' allows any access, returning unauthenticated user"
                )
                return AuthCredentials(['unauthenticated']), UnauthenticatedUser()

            if not cookie_header:
                logger.warning(
                    f"No authentication token found for endpoint '{endpoint}'"
                )
                raise AuthenticationError('Authentication token is missing')

        try:
            if auth_header:
                _, token = auth_header.split(' ')
            else:
                if not cookie_header:
                    logger.warning(f"No cookie header found for endpoint '{endpoint}'")
                    raise ValueError('No cookie header present')

                logger.debug(f'Extracting token from Cookie header: {cookie_header}')

                token = None
                auth = None

                # Split cookies properly - cookies can be separated by '; ' or ' '
                cookies = cookie_header.replace('; ', ' ').split(' ')

                cookies_dict = parse_cookies(cookie_header, 'authjs.session-token')
                for key, value in cookies_dict.items():
                    # print(f'Parsed cookie - {key}: {value}')
                    token = cookies_dict['authjs.session-token']

                # Password + optional OTP auth
                # auth = next(
                #     filter(lambda x: 'authjs.session-token' in x, cookies),
                #     None
                # )
                # print(f'auth._token.local found: {auth}')

                # # Check if we need to try passkey auth
                # if auth:
                #     try:
                #         cookie_parts = auth.rstrip(';').split('=', 1)
                #         if len(cookie_parts) == 2:
                #             _, value = cookie_parts
                #             logger.debug(f'Local token value: {value[:50]}...')
                #             if value != 'false' and '%20' in value:
                #                 _, token = value.split('%20', 1)
                #     except Exception as e:
                #         logger.warning(f'Failed to parse local token: {e}')
                #         auth = None

                # Passkey auth
                if not token:
                    auth = next(
                        filter(lambda x: 'auth._token.passkey' in x, cookies), None
                    )
                    logger.debug(f'auth._token.passkey found: {auth}')

                    if auth:
                        try:
                            cookie_parts = auth.rstrip(';').split('=', 1)
                            if len(cookie_parts) == 2:
                                _, value = cookie_parts
                                logger.debug(f'Passkey token value: {value[:50]}...')
                                if value != 'false' and '%20' in value:
                                    _, token = value.split('%20', 1)
                        except Exception as e:
                            logger.warning(f'Failed to parse passkey token: {e}')
                            auth = None

                # Used for Keycloak Impersonation
                if not token:
                    auth = next(
                        # auth._token.keycloak
                        filter(lambda x: 'authjs.session-token' in x, cookies),
                        None,
                    )
                    logger.debug(f'auth._token.keycloak found: {auth}')

                    if auth:
                        try:
                            cookie_parts = auth.rstrip(';').split('=', 1)
                            if len(cookie_parts) == 2:
                                _, value = cookie_parts
                                logger.debug(f'Keycloak token value: {value[:50]}...')
                                if value != 'false' and '%20' in value:
                                    _, token = value.split('%20', 1)
                        except Exception as e:
                            logger.warning(f'Failed to parse keycloak token: {e}')

                if not token:
                    logger.error(
                        f'No valid authentication token found in cookies. Full cookie header: {cookie_header}'
                    )
                    # Print debug all cookies values
                    for cookie in cookies:
                        print(f'[💎] Cookie: {cookie}')
                    raise ValueError('No valid authentication token found in cookies')
        # can't split auth token
        except (ValueError, StopIteration) as e:
            debug_exception(e)
            logger.warning(
                f"Failed to extract token from headers for endpoint '{endpoint}': "
                f'Error: {type(e).__name__} - {str(e)}, '
                f'Auth header: {auth_header[:50] if auth_header else "None"}..., '
                f'Cookie header: {cookie_header[:200] if cookie_header else "None"}...'
            )
            if is_endpoint_allow_any(endpoint):
                logger.debug(
                    f"Endpoint '{endpoint}' allows any access, returning unauthenticated user"
                )
                return AuthCredentials(['unauthenticated']), UnauthenticatedUser()

            raise AuthenticationError('� Authentication token is missing')

        try:
            keycloak_openid = get_keycloak_openid()
            logger.debug(f'Attempting to validate token for endpoint: {endpoint}')
            """
             HTTP/1.1 200 OK
            Content-Type: application/json

            {
            "sub": "248289761001",
            "name": "Jane Doe",
            "given_name": "Jane",
            "family_name": "Doe",
            "preferred_username": "j.doe",
            "email": "janedoe@example.com",
            "picture": "http://example.com/janedoe/me.jpg"
            }
            """
            user = keycloak_openid.userinfo(token)
            logger.debug(
                f'Successfully authenticated user: {user.get("preferred_username", "unknown")}'
            )
        except (KeycloakAuthenticationError, KeycloakGetError) as e:
            logger.error(
                f"Keycloak authentication failed for endpoint '{endpoint}': "
                f'Error type: {type(e).__name__}, '
                f'Status code: {getattr(e, "response_code", "N/A")}, '
                f'Response body: {getattr(e, "response_body", str(e))}, '
                f'Token prefix: {token[:20] if token else "N/A"}...'
            )
            if is_endpoint_allow_any(endpoint):
                logger.warning(
                    f"Endpoint '{endpoint}' allows unauthenticated access, continuing without auth"
                )
                return AuthCredentials(['unauthenticated']), UnauthenticatedUser()

            raise AuthenticationError(e.response_body)
        return AuthCredentials(['authenticated']), KeycloakAuthUser(**user)
