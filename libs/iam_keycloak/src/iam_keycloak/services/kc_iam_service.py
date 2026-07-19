"""Centralized service to interact with Keycloak"""
import json
from typing import Any, Dict, List, Optional, Union, cast

from foundation.config.saas_settings import SaaSSettings
from foundation.db.types import DBAsyncSession
from foundation.iam.auth import TokenType
from foundation.utils.dt_utils import timestamp_to_datetime
from iam.auth.auth_events import UserDirectoryCreatedEvent, UserDirectoryEventPayload
from iam.auth.schemas import SignupRequest
from iam.auth.schemas._auth import SignupRequestOut
from iam.auth.services._auth import BaseAuthService
from iam.auth.types import (
    AuthResponse,
    DirectoryUser,
    IamDirectoryServiceT,
    SessionInfo,
)
from iam.iam_constants import IamTopics
from iam.types import IIamServiceFactory
from iam.utils.saas_utils import generate_saas_subdomain, get_keycloak_subdomain
from keycloak import (
    KeycloakAuthenticationError,
    KeycloakError,
    KeycloakOpenID,
    KeycloakOperationError,
)

from iam_keycloak.db.repositories.kc_user_repo import KeycloakUserRepository
from iam_keycloak.keycloak_settings import get_keycloak_settings

from ..db.kc_db import kc_db_session_async
from ..domains.entities import KeycloakUser
from ..helpers.kc_admin_client import keycloaiAdminClient
from ..helpers.report_kc_error import report_keycloak_error
from ..helpers.serializers import (
    parse_keycloak_registered_organization,
    parse_keycloak_registered_user,
    parse_keycloak_user_data,
    user_registration_form_to_keycloak_data,
)
from .keycloak_init import get_keycloak_openid


class KeycloakIamService(BaseAuthService, IamDirectoryServiceT):
    """
    Keycloak IAM service implementation. This service interacts with Keycloak server
    to perform user authentication, registration, and management operations.
    """

    _iam_service_factory: IIamServiceFactory
    _delegate: keycloaiAdminClient

    def __init__(
        self,
        iam_service_factory: IIamServiceFactory,
    ):
        """
        Initialize Keycloak IAM service.
        """
        super().__init__()

        self._iam_service_factory = iam_service_factory

        # Initialize Keycloak OpenID client for user operations
        self.keycloak_openid: KeycloakOpenID = get_keycloak_openid()

        # Initialize Keycloak Admin client for administrative operations
        # self.keycloak_admin: KeycloakAdmin | None = None

        # admin_username = admin_username or get_keycloak_settings().KEYCLOAK_ADMIN_USER
        # admin_password = admin_password or get_keycloak_settings().KEYCLOAK_ADMIN_SECRET

        # if admin_username and admin_password:
        #     try:
        #         self.keycloak_admin = get_keycloak_admin()
        #     except Exception as e:
        #         self.logger.warning(f'Failed to initialize admin client: {e}')
        # else:
        #     self.logger.warning(
        #         'Admin credentials not provided; admin operations will be unavailable.'
        #     )
        self._delegate = keycloaiAdminClient()

    def saas_settings(self) -> SaaSSettings:
        """
        Get SaaS settings for the Keycloak IAM service.
        """
        return SaaSSettings.get_settings()

    def _convert_keycloak_user_to_user_entity(self, kc_user: Dict[str, Any]) -> DirectoryUser:
        return parse_keycloak_user_data(kc_user)

    def _ensure_admin_client(self):
        """Ensure admin client is available for admin operations"""
        if not self._delegate:
            raise ValueError(
                'Admin operations require admin credentials to be configured'
            )

    # ================================
    # User Management
    # ================================

    async def create_directory_user(
        self, registration_data: SignupRequest, **kwargs
    ) -> SignupRequestOut:
        return await self._create_directory_user(registration_data, **kwargs)

    @kc_db_session_async(transaction=True)
    async def _create_directory_user(
        self, registration_data: SignupRequest, session: DBAsyncSession, **kwargs
    ) -> SignupRequestOut:
        """
        Register a new user in Keycloak. Here is the flow:
        - Check if user with the given email already exists.
        - If exists, return 'EXISTED' status.
        - If not, create a new user in Keycloak.
        - Create a new tenant for the user.
        - Add the user to the newly created tenant.
        - Publish a UserRegistered event.
        - Return registration response with user details.
        - ✅ Tested and works as expected.
        """
        self._ensure_admin_client()

        # Verify OPT for email ++ (rem this code to disable otp check)
        # saved_otp = await self.get_cache_service().get(
        #     f'{IamConstants.CACHE_SIGNUP_OTP_PREFIX}{registration_data.email}'
        # )
        # if not saved_otp or not isinstance(saved_otp, str):
        #     response = UserRegistrationResponse()
        #     response.status = 'FAILED'
        #     response.message = 'OTP code not found or expired.'
        #     return response

        # if registration_data.otp not in saved_otp:
        #     response = UserRegistrationResponse()
        #     response.status = 'FAILED'
        #     response.message = 'Invalid or expired OTP code.'
        #     return response

        # if registration_data.email not in saved_otp:
        #     response = UserRegistrationResponse()
        #     response.status = 'FAILED'
        #     response.message = f'Email {registration_data.email} not verified.'
        #     return response
        # Verify OPT for email --

        #
        # 1. Check if user existed
        #

        user_repo = cast(
            KeycloakUserRepository,
            self._iam_service_factory.get_repository_factory().get_async(KeycloakUser),
        )
        email: str = registration_data.email # type: ignore
        username = registration_data.username

        if username:
            existed_user = await user_repo.count_user_by_username(username, session)
        elif email:
            existed_user = await user_repo.count_user_by_email(email, session)
        else:
            raise ValueError('Either username or email must be provided for registration.')

        if existed_user > 0:
            self.logger.info(
                f'User with email {registration_data.email} or username {registration_data.username} already exists'
            )
            response = SignupRequestOut()
            response.status = 'EXISTED'
            return response


        response = SignupRequestOut()

        # user: User = User(
        #     email=registration_data.email,
        #     preferred_username=registration_data.email,
        #     given_name=registration_data.first_name,
        #     family_name=registration_data.last_name,
        #     # username=registration_data.email,
        #     email_verified=False,
        # )

        # Create user in Keycloak
        # user_id = generate_id()
        kc_user_data = user_registration_form_to_keycloak_data(registration_data)
        attributes: dict[str, Any] = kc_user_data.get('attributes', {})
        attributes['origin'] = 'signup'

        if registration_data.organization:
            tenant_dict = {
                'name': registration_data.organization,
                'alias': registration_data.organization.lower().replace(' ', '-'),
                'domains': [
                    get_keycloak_subdomain(
                        generate_saas_subdomain(registration_data.organization)
                    )
                ],
                # 'domains': ['eworksuite.com']
                # 'attributes': to_json({'origin': 'taas'})
            }
        else:
            tenant_dict = {
                'name': email.split('@')[0],
                'alias': email.split('@')[0].lower().replace(' ', '-'),
                'domains': [
                    get_keycloak_subdomain(
                        generate_saas_subdomain(email.split('@')[0])
                    )
                ],
            }
        try:
            created_tenant = await self._delegate.create_organization(tenant_dict)
            tenant_id = created_tenant['id']
            attributes['tenant_id'] = tenant_id
            attributes['is_root_account'] = True
            created_kc_user = await self._delegate.create_user(kc_user_data, True)
            user_id = created_kc_user['id']
            self.logger.info(f'Created user in Keycloak with ID {user_id}/{tenant_id}')

            # Add this user to the organization
            await self._delegate.add_user_to_organization(user_id, tenant_id)
            response.user = created_kc_user
            response.id = user_id

            # Important -> remove {password} field from logs
            """
            "credentials": [
                    {
                    "value": "xxxxxxxx",
                    "type": "password"
                    }
                ],
            """
            kc_user_data['attributes'] = attributes
            kc_user_data.pop('credentials', None)  # hide password in logs

            _directory_user = parse_keycloak_registered_user(created_kc_user)
            _directory_tenant = parse_keycloak_registered_organization(created_tenant)


            _payload = UserDirectoryEventPayload  (
                user=_directory_user,
                tenant=_directory_tenant,
            )
            e_user_directory_created = UserDirectoryCreatedEvent(
                user_id=user_id,
                email=_directory_user.email,
                username=_directory_user.username,
                realm_name=self.keycloak_openid.realm_name,
                tenant_id=tenant_id,
                # payload=parse_keycloak_registered_user(kc_user=created_kc_user).as_dict(),
                # tenant=parse_keycloak_registered_organization(created_tenant).as_dict(),
                # payload={
                #     'user': parse_keycloak_registered_user(kc_user=created_kc_user).as_dict(),
                #     'tenant': parse_keycloak_registered_organization(created_tenant).as_dict(),
                # }
            )
            e_user_directory_created.set_payload_object(_payload)

            try:
                await self.message_routing_service.publish_event(e_user_directory_created, IamTopics.IAM_USER_REGISTER)

                # await IamEventPublisher().publish_user_directory_created_event(e_user_directory_created)
            except Exception as publish_exc:
                # TODO: handle failed event publishing (e.g., retry, compensation)
                # Report error and rollback
                report_keycloak_error(
                    publish_exc,
                    title='IAM Event Publish Error',
                    extra_context={'payload': str(e_user_directory_created)},
                    logger=self.logger,
                )
        except KeycloakError as e:
            response.status = 'FAILED'
            error_message = report_keycloak_error(
                e, title='Keycloak User Registration Error', logger=self.logger
            )
            response.message = error_message
            # raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error)

        return response

    async def logout_by_refresh_token(
        self, refresh_token: str, realm: str | None = None
    ) -> bool:
        keycloak_openid = get_keycloak_openid(realm)
        # keycloak_openid.client_id = settings.KEYCLOAK_LOGIN_CLIENT_ID
        # keycloak_openid.client_secret_key = settings.KEYCLOAK_LOGIN_CLIENT_SECRET
        try:
            keycloak_openid.logout(refresh_token)
            return True
        except KeycloakAuthenticationError, KeycloakOperationError:
            return False

    async def logout_by_user_id(self, user_id, session_id=None):
        try:
            await self._delegate.loggout_user(user_id)
            return True
        except Exception as e:
            self.logger.warning(f'Failed to logout user {user_id} with session {session_id}, error: {e}')
            return False

    async def logout_by_access_token(self, access_token: str) -> bool:
        session_id = self.get_session_id_from_token(access_token)
        if not session_id:
            return False
        keycloak_admin = self._delegate.rest_admin.admin_delete_session(session_id)
        try:
            keycloak_admin.user_logout(user_id)
            return True
        except Exception:
            return False

    # ================================
    # REQ-AUTH-001: User Registration
    # ================================

    async def _send_email_verification(self, user_id: str) -> bool:
        """
        # TODO: to check this api
        Send email verification link to user.

        REQ-AUTH-001.3: Email verification workflow

        Args:
            user_id: Keycloak user ID

        Returns:
            bool: True if email sent successfully
        """
        self._ensure_admin_client()
        try:
            await self._delegate.keycloak_admin.a_send_verify_email(user_id=user_id)
            self.logger.info(f'Verification email sent to user {user_id}')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Send Verification Email Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return False

    async def verify_email(self, token: str) -> bool:
        """
        Verify email using verification token.

        REQ-AUTH-001.3: Email verification workflow

        Args:
            token: Email verification token

        Returns:
            bool: True if verification successful
        """
        self._ensure_admin_client()
        try:
            # Decode token to get user_id (token is JWT)
            decoded = jwt.decode(token, options={'verify_signature': False})
            user_id = decoded.get('sub')

            if not user_id:
                self.logger.warning('Invalid verification token')
                return False

            # Update user to mark email as verified
            await self._delegate.keycloak_admin.a_update_user(
                user_id=user_id, payload={'emailVerified': True}
            )
            self.logger.info(f'Email verified for user {user_id}')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Email Verification Error',
                logger=self.logger,
            )
            return False

    # ================================
    # REQ-AUTH-002: User Login
    # ================================

    async def authenticate_password(
        self,
        auth_request: PasswordAuthRequest,
        context: Optional[AuthContext] = None,
    ) -> AuthResponse:
        """
        Authenticate user with password.

        REQ-AUTH-002.1: Password-based authentication

        Args:
            username_or_email: Username or email address
            password: User password
            context: Optional authentication context

        Returns:
            AuthenticationResponse with tokens

        Raises:
            KeycloakAuthenticationError: If authentication fails
        """
        settings = get_keycloak_settings()
        keycloak_openid = get_keycloak_openid()
        keycloak_openid.client_id = settings.KEYCLOAK_LOGIN_CLIENT_ID

        try:
            scope = 'openid profile email organization'
            if auth_request.keep_signed_in:
                scope += ' offline_access'

            token = keycloak_openid.token(
                username=auth_request.username_or_email,
                password=auth_request.password,
                totp=auth_request.otp,
                client_secret=settings.KEYCLOAK_LOGIN_CLIENT_SECRET,
                scope=scope,
            )

            self.logger.debug(
                f'User {auth_request.username_or_email} authenticated successfully: {token}'
            )

            # Fire event for successful login
            # TODO: Implement event firing logic here

            return AuthResponse(
                access_token=token.get('access_token'),
                expires_in=token.get('expires_in'),
                refresh_token=token.get('refresh_token'),
                refresh_expires_in=token.get('refresh_expires_in'),
                token_type=token.get('token_type'),
                id_token=token.get('id_token'),
                not_before_policy=token.get('not_before_policy'),
                session_state=token.get('session_state'),
                keep_signed_in=auth_request.keep_signed_in,
                # scope=token.get('scope'),
            )
        except (KeycloakAuthenticationError, KeycloakOperationError) as error:
            err_message = json.loads(error.error_message)
            self.logger.warning(
                f'Authentication failed for {auth_request.username_or_email}: {err_message}'
            )
            raise

    def login(
        self,
        username: str,
        password: str,
        otp_code: str | None = None,
        keep_signed_in: bool = False,
    ) -> Union[AuthResponse, str]:
        settings = get_keycloak_settings()

        client_id: str
        if not settings.KEYCLOAK_LOGIN_CLIENT_ID:
            raise ValueError('KEYCLOAK_LOGIN_CLIENT_ID is not configured')
        else:
            client_id = settings.KEYCLOAK_LOGIN_CLIENT_ID

        keycloak_openid = get_keycloak_openid()
        keycloak_openid.client_id = client_id
        try:
            scope = f'openid profile email{" offline_access" if keep_signed_in else ""}'
            token = keycloak_openid.token(
                username=username,
                password=password,
                totp=otp_code,
                client_secret=settings.KEYCLOAK_LOGIN_CLIENT_SECRET,
                scope=scope,
            )
            return AuthResponse(
                access_token=token.get('access_token'),
                refresh_token=token.get('refresh_token'),
            )
        except (KeycloakAuthenticationError, KeycloakOperationError) as error:
            err_message = json.loads(error.error_message)
            print(f'[🔴] Keycloak login error: {err_message}')
            return err_message.get('error_description')

    async def authenticate_otp(
        self,
        username_or_email: str,
        otp_code: str,
        context: Optional[AuthContext] = None,
    ) -> AuthResponse:
        """
        Authenticate user with OTP only (passwordless).

        REQ-AUTH-002.2: OTP-based authentication (passwordless)

        Args:
            username_or_email: Username or email address
            otp_code: One-time password code
            context: Optional authentication context

        Returns:
            AuthenticationResponse with tokens

        Raises:
            KeycloakAuthenticationError: If authentication fails
        """
        settings = get_keycloak_settings()
        keycloak_openid = get_keycloak_openid()
        keycloak_openid.client_id = settings.KEYCLOAK_LOGIN_CLIENT_ID

        try:
            # Note: OTP-only authentication requires custom authenticator in Keycloak
            token = keycloak_openid.token(
                username=username_or_email,
                totp=otp_code,
                grant_type='password',
                client_secret=settings.KEYCLOAK_LOGIN_CLIENT_SECRET,
                scope='openid profile email',
            )

            self.logger.info(f'User {username_or_email} authenticated with OTP')
            return AuthResponse(
                access_token=token.get('access_token'),
                refresh_token=token.get('refresh_token'),
            )
        except (KeycloakAuthenticationError, KeycloakOperationError) as error:
            err_message = json.loads(error.error_message)
            self.logger.warning(
                f'OTP authentication failed for {username_or_email}: {err_message}'
            )
            raise

    async def authenticate_social(
        self,
        provider: SocialProvider,
        provider_token: str,
        context: Optional[AuthContext] = None,
    ) -> AuthResponse:
        """
        Authenticate user via social provider.

        REQ-AUTH-002.3: Social login (Google, Microsoft)

        Args:
            provider: Social provider (Google, Microsoft, etc.)
            provider_token: OAuth token from provider
            context: Optional authentication context

        Returns:
            AuthenticationResponse with tokens

        Note:
            This requires proper IdP configuration in Keycloak
        """
        # Social authentication is typically handled via redirect flow
        # This method is a placeholder for backend token exchange
        raise NotImplementedError(
            'Social authentication requires frontend redirect flow. '
            'Use get_social_login_url() for initiating social login.'
        )

    async def set_remember_me(self, user_id: str, remember: bool = True) -> bool:
        """
        Enable/disable remember me for user (controls offline_access scope).

        REQ-AUTH-002.4: Remember me functionality (persistent sessions)

        Args:
            user_id: User ID
            remember: Whether to enable persistent sessions

        Returns:
            bool: True if updated successfully

        Note:
            Remember me is handled at login time via offline_access scope.
            This method updates user preferences.
        """
        self._ensure_admin_client()
        try:
            await self._delegate.keycloak_admin.a_update_user(
                user_id=user_id,
                payload={'attributes': {'rememberMe': [str(remember).lower()]}},
            )
            self.logger.info(f'Remember me set to {remember} for user {user_id}')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Remember Me Error',
                extra_context={'user_id': user_id, 'remember': remember},
                logger=self.logger,
            )
            return False

    # ================================
    # REQ-AUTH-003: Two-Factor Authentication
    # ================================

    async def enable_totp(self, user_id: str) -> Dict[str, Any]:
        """
        Generate TOTP configuration for user.

        REQ-AUTH-003.1: TOTP-based (Time-based One-Time Password)
        REQ-AUTH-003.4: QR code generation for authenticator apps

        Args:
            user_id: Keycloak user ID

        Returns:
            Dict with totp_secret, totp_secret_encoded, and qr_code
        """
        self._ensure_admin_client()
        settings = get_keycloak_settings()

        try:
            url = f'{settings.KEYCLOAK_HOST}/admin/realms/{settings.KEYCLOAK_REALM}/totp/config/{user_id}/'
            response = await self._delegate.keycloak_admin.a_raw_get(url)
            data = response.json()

            self.logger.info(f'TOTP configuration generated for user {user_id}')
            return {
                'totp_secret': data.get('totpSecret'),
                'totp_secret_encoded': data.get('totpSecretEncoded'),
                'qr_code': data.get('qrCode'),
            }
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM TOTP Config Generation Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            raise

    async def verify_totp(self, user_id: str, totp_code: str) -> bool:
        """
        Verify and activate TOTP for user.

        REQ-AUTH-003.1: TOTP-based verification

        Args:
            user_id: Keycloak user ID
            totp_code: TOTP code to verify

        Returns:
            bool: True if TOTP verified and activated
        """
        self._ensure_admin_client()
        settings = get_keycloak_settings()

        try:
            # Get TOTP secret first
            totp_config = await self.enable_totp(user_id)
            totp_secret = totp_config.get('totp_secret')

            # Activate TOTP with verification code
            data = {
                'deviceName': 'Authenticator App',
                'totpSecret': totp_secret,
                'initialCode': totp_code,
            }

            url = f'{settings.KEYCLOAK_HOST}/admin/realms/{settings.KEYCLOAK_REALM}/totp/activate/{user_id}/'
            response = await self._delegate.keycloak_admin.a_raw_post(
                url, data=json.dumps(data)
            )

            if response.status_code == 204:
                self.logger.info(f'TOTP activated for user {user_id}')
                return True
            else:
                error = response.json().get('error', 'Unknown error')
                report_keycloak_error(
                    error,
                    title='IAM TOTP Activation Error',
                    extra_context={'user_id': user_id},
                    logger=self.logger,
                )
                return False
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM TOTP Verification Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return False

    async def disable_totp(self, user_id: str) -> bool:
        """
        Remove TOTP configuration from user.

        REQ-AUTH-003: Two-Factor Authentication

        Args:
            user_id: Keycloak user ID

        Returns:
            bool: True if TOTP disabled successfully
        """
        self._ensure_admin_client()
        settings = get_keycloak_settings()

        try:
            # Get user credentials
            credentials = await self._delegate.keycloak_admin.a_get_credentials(user_id)

            # Find OTP credential
            otp_credential = next((c for c in credentials if c['type'] == 'otp'), None)

            if not otp_credential:
                self.logger.info(f'No TOTP credential found for user {user_id}')
                return True

            credential_id = otp_credential['id']
            url = f'{settings.KEYCLOAK_HOST}/admin/realms/{settings.KEYCLOAK_REALM}/users/{user_id}/credentials/{credential_id}/'
            response = await self._delegate.keycloak_admin.a_raw_delete(url)

            success = response.status_code == 204
            if success:
                self.logger.info(f'TOTP disabled for user {user_id}')
            return success
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM TOTP Disable Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return False

    async def get_totp_backup_codes(self, user_id: str) -> List[str]:
        """
        Get backup codes for TOTP (if configured in Keycloak).

        REQ-AUTH-003: Two-Factor Authentication

        Args:
            user_id: Keycloak user ID

        Returns:
            List of backup codes

        Note:
            Backup codes require custom configuration in Keycloak.
            This is a placeholder implementation.
        """
        # Backup codes are not natively supported in Keycloak
        # Would require custom authenticator implementation
        self.logger.warning('TOTP backup codes require custom Keycloak authenticator')
        return []

    # ================================
    # REQ-AUTH-004: Password Management
    # ================================

    async def send_password_reset_email(self, email: str) -> bool:
        """
        Send password reset email to user.

        REQ-AUTH-004.1: Email-based password reset
        REQ-AUTH-004.2: Forgot password workflow
        REQ-AUTH-004.3: Secure token generation with expiration

        Args:
            email: User email address

        Returns:
            bool: True if email sent (or user not found - security)
        """
        self._ensure_admin_client()

        try:
            # Get user by email
            users = await self._delegate.keycloak_admin.a_get_users({'email': email})

            if not users:
                # Don't reveal if user exists (security best practice)
                self.logger.info(
                    'Password reset requested for non-existent email (no-op for security)'
                )
                return True

            user_id = users[0]['id']

            # Send password reset email via update account action
            await self._delegate.keycloak_admin.a_send_update_account(
                user_id=user_id, payload=['UPDATE_PASSWORD']
            )

            self.logger.info(f'Password reset email sent to {email}')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Password Reset Email Error',
                extra_context={'email': email},
                logger=self.logger,
            )
            return False

    async def verify_password_reset_token(self, token: str) -> Optional[str]:
        """
        Verify password reset token and return user ID.

        REQ-AUTH-004.3: Secure token generation with expiration

        Args:
            token: Password reset token (JWT)

        Returns:
            Optional[str]: User ID if valid, None otherwise
        """
        try:
            # Decode JWT token (Keycloak uses signed JWTs)
            decoded = jwt.decode(token, options={'verify_signature': False})
            user_id = decoded.get('sub')

            # Check expiration
            exp = decoded.get('exp')
            if exp and exp < jwt.datetime.datetime.now().timestamp():
                self.logger.warning('Password reset token expired')
                return None

            self.logger.info(f'Password reset token verified for user {user_id}')
            return user_id
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Password Reset Token Verification Error',
                logger=self.logger,
            )
            return None

    async def complete_password_reset(self, token: str, new_password: str) -> bool:
        """
        Complete password reset with new password.

        REQ-AUTH-004.1: Email-based password reset
        REQ-AUTH-004.4: Password policy enforcement

        Args:
            token: Password reset token
            new_password: New password

        Returns:
            bool: True if password reset successful
        """
        self._ensure_admin_client()

        user_id = await self.verify_password_reset_token(token)
        if not user_id:
            return False

        try:
            await self._delegate.keycloak_admin.a_set_user_password(
                user_id=user_id, password=new_password, temporary=False
            )
            self.logger.info(f'Password reset completed for user {user_id}')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Complete Password Reset Error',
                logger=self.logger,
            )
            return False

    async def change_password(
        self, user_id: str, current_password: str, new_password: str
    ) -> bool:
        """
        Change user password (requires current password verification).

        REQ-AUTH-004.4: Password policy enforcement

        Args:
            user_id: User ID
            current_password: Current password for verification
            new_password: New password

        Returns:
            bool: True if password changed successfully
        """
        self._ensure_admin_client()

        try:
            # Verify current password by attempting authentication
            user = await self._delegate.keycloak_admin.a_get_user(user_id)
            username = user.get('username')

            settings = get_keycloak_settings()
            keycloak_openid = get_keycloak_openid()
            keycloak_openid.client_id = settings.KEYCLOAK_LOGIN_CLIENT_ID

            try:
                keycloak_openid.token(
                    username=username,
                    password=current_password,
                    client_secret=settings.KEYCLOAK_LOGIN_CLIENT_SECRET,
                )
            except KeycloakAuthenticationError:
                self.logger.warning(
                    f'Current password verification failed for user {user_id}'
                )
                return False

            # Set new password
            await self._delegate.keycloak_admin.a_set_user_password(
                user_id=user_id, password=new_password, temporary=False
            )

            self.logger.info(f'Password changed for user {user_id}')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Change Password Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return False

    async def get_password_policy(self) -> PasswordPolicy:
        """
        Get current password policy configuration.

        REQ-AUTH-004.4: Password policy enforcement

        Returns:
            PasswordPolicy with current policy settings
        """
        self._ensure_admin_client()
        settings = get_keycloak_settings()

        try:
            realm = await self._delegate.keycloak_admin.a_get_realm(
                settings.KEYCLOAK_REALM
            )
            policy_string = realm.get('passwordPolicy', '')

            # Parse policy string (format: "policy1(value1) and policy2(value2)")
            policies = {}
            if policy_string:
                for policy in policy_string.split(' and '):
                    if '(' in policy:
                        name, value = policy.split('(')
                        policies[name] = value.rstrip(')')
                    else:
                        policies[policy] = True

            return PasswordPolicy(
                minimum_length=int(policies.get('length', 8)),
                require_digits='digits' in policies,
                require_lowercase='lowerCase' in policies,
                require_uppercase='upperCase' in policies,
                require_special_chars='specialChars' in policies,
                password_history=int(policies.get('passwordHistory', 0)),
            )
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Get Password Policy Error',
                logger=self.logger,
            )
            # Return default policy
            return PasswordPolicy(
                minimum_length=8,
                require_digits=True,
                require_lowercase=True,
                require_uppercase=True,
                require_special_chars=True,
            )

    # ================================
    # REQ-TOKEN-001: Token Refresh
    # ================================

    async def refresh_token(self, refresh_token: str) -> AuthResponse:
        """
        Refresh access token using refresh token.

        REQ-TOKEN-001.1: Automatic token refresh (web and mobile)
        REQ-TOKEN-001.2: Refresh token rotation
        REQ-TOKEN-001.3: Single-use refresh tokens

        Args:
            refresh_token: Current refresh token

        Returns:
            AuthenticationResponse with new tokens

        Raises:
            KeycloakAuthenticationError: If refresh fails
        """
        settings = get_keycloak_settings()

        try:
            # Decode refresh token to get client ID
            decoded = jwt.decode(refresh_token, options={'verify_signature': False})
            keycloak_client_id = decoded.get('azp')

            # Handle impersonation token refresh
            if keycloak_client_id == settings.KEYCLOAK_BUSINESS_IMPERSONATE_CLIENT_ID:
                keycloak_openid = KeycloakOpenID(
                    server_url=settings.KEYCLOAK_HOST,
                    client_id=settings.KEYCLOAK_BUSINESS_IMPERSONATE_CLIENT_ID,
                    client_secret_key=settings.KEYCLOAK_BUSINESS_IMPERSONATE_CLIENT_SECRET,
                    realm_name=settings.KEYCLOAK_REALM,
                    verify=True,
                )
            else:
                keycloak_openid = get_keycloak_openid()
                keycloak_openid.client_id = settings.KEYCLOAK_LOGIN_CLIENT_ID
                keycloak_openid.client_secret_key = (
                    settings.KEYCLOAK_LOGIN_CLIENT_SECRET
                )

            token = keycloak_openid.refresh_token(refresh_token)

            self.logger.info('Token refreshed successfully')
            return AuthResponse(
                access_token=token.get('access_token'),
                refresh_token=token.get('refresh_token'),  # New rotated token
            )
        except (KeycloakAuthenticationError, KeycloakOperationError) as error:
            err_message = json.loads(error.error_message)
            self.logger.warning(f'Token refresh failed: {err_message}')
            raise

    async def validate_token(
        self, token: str, token_type: TokenType = TokenType.ACCESS_TOKEN
    ) -> bool:
        """
        Validate token (checks signature and expiration).

        REQ-TOKEN-001: Token management

        Args:
            token: Token to validate
            token_type: Type of token (access or refresh)

        Returns:
            bool: True if token is valid
        """
        keycloak_openid = get_keycloak_openid()

        try:
            # Introspect token (validates signature and expiration)
            token_info = keycloak_openid.introspect(token)
            is_active = token_info.get('active', False)

            if is_active:
                self.logger.debug(
                    f'Token validated successfully for user {token_info.get("sub")}'
                )
            else:
                self.logger.debug('Token is not active')

            return is_active
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Token Validation Error',
                extra_context={
                    'token': token[:20] + '...' if len(token) > 20 else token
                },
                logger=self.logger,
            )
            return False

    async def revoke_token(
        self, token: str, token_type: TokenType = TokenType.REFRESH_TOKEN
    ) -> bool:
        """
        Revoke token (logout).

        REQ-TOKEN-001: Token management

        Args:
            token: Token to revoke (typically refresh token)
            token_type: Type of token

        Returns:
            bool: True if revoked successfully
        """
        if token_type == TokenType.REFRESH_TOKEN:
            return await self.logout_by_refresh_token(token)
        else:
            # Access tokens cannot be revoked directly (they expire naturally)
            self.logger.warning(
                'Access tokens cannot be revoked directly, they expire naturally'
            )
            return False

    # ================================
    # REQ-TOKEN-002: Single Sign-On (SSO)
    # ================================

    async def get_sso_session(self, user_id: str) -> Optional[SessionInfo]:
        """
        Get current SSO session for user.

        REQ-TOKEN-002.1: Cross-application SSO

        Args:
            user_id: Keycloak user ID

        Returns:
            Optional[SessionInfo]: Session information if active
        """
        self._ensure_admin_client()

        try:
            sessions = await self._delegate.keycloak_admin.a_get_sessions(user_id)

            if not sessions:
                return None

            # Return the most recent session
            latest_session = sessions[0]
            return SessionInfo(
                session_id=latest_session.get('id'),
                user_id=user_id,
                ip_address=latest_session.get('ipAddress'),
                start_time=latest_session.get('start'),
                last_access=latest_session.get('lastAccess'),
                clients=list(latest_session.get('clients', {}).keys()),
            )
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Get SSO Session Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return None

    async def logout(self, user_id: str, session_id: Optional[str] = None) -> bool:
        """
        Logout user from specific session or all sessions.

        REQ-TOKEN-002.4: Centralized logout

        Args:
            user_id: User ID
            session_id: Optional specific session ID to logout

        Returns:
            bool: True if logout successful
        """
        return await self.logout_by_user_id(user_id, session_id)

    async def logout_all_sessions(self, user_id: str) -> bool:
        """
        Logout user from all active sessions.

        REQ-TOKEN-002.4: Centralized logout

        Args:
            user_id: User ID

        Returns:
            bool: True if logout successful
        """
        return await self.logout_by_user_id(user_id)

    async def get_directory_user_sessions(self, user_id: str) -> List[SessionInfo]:
        """
        Get all active sessions for user.

        REQ-TOKEN-002.2: SSO session management

        Args:
            user_id: User ID

        Returns:
            List of SessionInfo for all active sessions
        """
        self._ensure_admin_client()

        try:
            sessions = await self._delegate.keycloak_admin.a_get_sessions(user_id)

            self.logger.info(f'Fetched {len(sessions)} sessions for user {user_id}')
            print(sessions)

            _session_infos: List[SessionInfo] = []
            for session in sessions:
                # start_time is Long and normally in milliseconds, convert to datetime (from 1970-01-01)
                start_time = session.get('start')
                if start_time is not None and isinstance(start_time, int):
                    created_at = timestamp_to_datetime(start_time / 1000)
                else:
                    created_at = None

                lastAccess = session.get('lastAccess')
                if lastAccess is not None and isinstance(lastAccess, int):
                    last_activity = timestamp_to_datetime(lastAccess / 1000)
                else:
                    last_activity = None
                _session_info = SessionInfo(
                    session_id=session.get('id'),
                    user_id=user_id,
                    username=session.get('username'),
                    ip_address=session.get('ipAddress'),
                    # start_time=session.get('start'),
                    created_at=created_at,
                    last_activity=last_activity,
                    clients=session.get('clients', {}).keys(),
                    transient_user=session.get('transientUser', False),
                )
                _session_infos.append(_session_info)

            return _session_infos
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Get User Sessions Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return []

    # ================================
    # REQ-ADMIN-001: Admin Impersonation
    # ================================

    async def impersonate_user(
        self, admin_user_id: str, target_user_id: str
    ) -> AuthResponse:
        """
        Admin impersonate user via token exchange.

        REQ-ADMIN-001.1: Secure impersonation via token exchange
        REQ-ADMIN-001.2: Audit trail of impersonation events
        REQ-ADMIN-001.3: Limited to authorized admin roles
        REQ-ADMIN-001.4: Time-limited impersonation sessions

        Args:
            admin_user_id: Admin user ID (unused, kept for interface compatibility)
            target_user_id: Target user ID or username to impersonate

        Returns:
            AuthenticationResponse with impersonation tokens

        Raises:
            KeycloakAuthenticationError: If impersonation fails
        """
        settings = get_keycloak_settings()

        try:
            # Get target user
            user = await self._delegate.keycloak_admin.a_get_user(target_user_id)
            target_username = user.get('username')

            keycloak_openid = KeycloakOpenID(
                server_url=settings.KEYCLOAK_API,
                client_id=settings.KEYCLOAK_BUSINESS_IMPERSONATE_CLIENT_ID,
                client_secret_key=settings.KEYCLOAK_BUSINESS_IMPERSONATE_CLIENT_SECRET,
                realm_name=settings.KEYCLOAK_REALM,
                verify=True,
            )

            # First, get service account token
            client_token = keycloak_openid.token(grant_type='client_credentials')
            client_access_token = client_token.get('access_token')

            # Exchange for user token (impersonation)
            impersonated_token = keycloak_openid.token(
                grant_type='urn:ietf:params:oauth:grant-type:token-exchange',
                scope='openid profile email',
                requested_subject=target_username,
                subject_token=client_access_token,
            )

            self.logger.info(f'Admin impersonating user {target_username}')
            return AuthResponse(
                access_token=impersonated_token.get('access_token'),
                refresh_token=impersonated_token.get('refresh_token'),
            )
        except (KeycloakAuthenticationError, KeycloakOperationError) as error:
            err_message = json.loads(error.error_message)
            report_keycloak_error(
                error,
                title='IAM Impersonation Error',
                extra_context={
                    'admin_user_id': admin_user_id,
                    'target_user_id': target_user_id,
                    'error_message': err_message,
                },
                logger=self.logger,
            )
            raise

    async def end_impersonation(self, impersonation_token: str) -> bool:
        """
        End impersonation session.

        REQ-ADMIN-001: Admin Impersonation

        Args:
            impersonation_token: Impersonation refresh token

        Returns:
            bool: True if ended successfully
        """
        return await self.logout_by_refresh_token(impersonation_token)

    async def get_impersonation_history(
        self,
        admin_user_id: Optional[str] = None,
        target_user_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get audit trail of impersonation events.

        REQ-ADMIN-001.2: Audit trail of impersonation events

        Args:
            admin_user_id: Filter by admin user
            target_user_id: Filter by target user
            limit: Maximum number of events

        Returns:
            List of impersonation events
        """
        self._ensure_admin_client()

        try:
            # Get admin events (impersonation is logged as admin event)
            events = await self._delegate.keycloak_admin.a_get_events(
                event_type='IMPERSONATE', max_events=limit
            )

            result = []
            for event in events:
                event_data = {
                    'timestamp': event.get('time'),
                    'admin_user_id': event.get('userId'),
                    'target_user_id': event.get('details', {}).get(
                        'impersonated_user_id'
                    ),
                    'ip_address': event.get('ipAddress'),
                    'event_type': event.get('type'),
                }

                # Apply filters
                if admin_user_id and event_data['admin_user_id'] != admin_user_id:
                    continue
                if target_user_id and event_data['target_user_id'] != target_user_id:
                    continue

                result.append(event_data)

            return result
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Get Impersonation History Error',
                extra_context={
                    'admin_user_id': admin_user_id,
                    'target_user_id': target_user_id,
                },
                logger=self.logger,
            )
            return []

    # ================================
    # REQ-ADMIN-002: Service Account Authentication
    # ================================

    async def create_service_account(
        self,
        name: str,
        description: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create service account (client) for M2M authentication.

        REQ-ADMIN-002.1: Client credentials flow (OAuth2)
        REQ-ADMIN-002.2: Service account roles and permissions

        Args:
            name: Name of the service account
            description: Optional description
            roles: List of roles to assign

        Returns:
            Dict with client_id, client_secret, and service_user_id
        """
        self._ensure_admin_client()

        client_data = {
            'clientId': name,
            'name': name,
            'description': description or f'Service account for {name}',
            'enabled': True,
            'serviceAccountsEnabled': True,
            'clientAuthenticatorType': 'client-secret',
            'standardFlowEnabled': False,
            'directAccessGrantsEnabled': False,
            'publicClient': False,
        }

        try:
            # Create client
            client_id = await self._delegate.keycloak_admin.a_create_client(client_data)

            # Get client secret
            client_secret = await self._delegate.keycloak_admin.a_get_client_secrets(
                client_id
            )

            # Get service account user
            service_user_id = (
                await self._delegate.keycloak_admin.a_get_client_service_account_user(
                    client_id
                )
            )

            # Assign roles if provided
            if roles:
                for role in roles:
                    try:
                        role_obj = await self._delegate.keycloak_admin.a_get_realm_role(
                            role
                        )
                        await self._delegate.keycloak_admin.a_assign_realm_roles(
                            user_id=service_user_id, roles=[role_obj]
                        )
                    except Exception as e:
                        self.logger.warning(f'Failed to assign role {role}: {e}')

            self.logger.info(f'Service account created: {name}')
            return {
                'client_id': name,
                'client_secret': client_secret.get('value'),
                'service_user_id': service_user_id,
            }
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Create Service Account Error',
                extra_context={'name': name, 'description': description},
                logger=self.logger,
            )
            raise

    async def authenticate_service_account(
        self, client_id: str, client_secret: str
    ) -> AuthResponse:
        """
        Authenticate service account using client credentials.

        REQ-ADMIN-002.3: API-to-API authentication
        REQ-ADMIN-002.4: Machine-to-machine communication

        Args:
            client_id: Service account client ID
            client_secret: Service account client secret

        Returns:
            AuthenticationResponse with access token

        Raises:
            KeycloakAuthenticationError: If authentication fails
        """
        settings = get_keycloak_settings()

        keycloak_openid = KeycloakOpenID(
            server_url=settings.KEYCLOAK_HOST,
            client_id=client_id,
            client_secret_key=client_secret,
            realm_name=settings.KEYCLOAK_REALM,
            verify=True,
        )

        try:
            token = keycloak_openid.token(grant_type='client_credentials')

            self.logger.info(f'Service account {client_id} authenticated successfully')
            return AuthResponse(
                access_token=token.get('access_token'),
                refresh_token=None,  # Client credentials flow doesn't issue refresh tokens
            )
        except (KeycloakAuthenticationError, KeycloakOperationError) as error:
            err_message = json.loads(error.error_message)
            report_keycloak_error(
                error,
                title='IAM Service Account Authentication Error',
                extra_context={'client_id': client_id, 'error_message': err_message},
                logger=self.logger,
            )
            raise

    async def rotate_service_account_secret(self, client_id: str) -> Dict[str, str]:
        """
        Rotate service account client secret.

        REQ-ADMIN-002: Service Account Authentication

        Args:
            client_id: Client UUID (not clientId string)

        Returns:
            Dict with new client_secret
        """
        self._ensure_admin_client()

        try:
            # Generate new secret
            new_secret = await self._delegate.keycloak_admin.a_generate_client_secrets(
                client_id
            )

            self.logger.info(f'Service account secret rotated for client {client_id}')
            return {'client_secret': new_secret.get('value'), 'rotated_at': 'now'}
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Rotate Service Account Secret Error',
                extra_context={'client_id': client_id},
                logger=self.logger,
            )
            raise

    # ================================
    # User Management Operations
    # ================================

    async def directory_get_user_by_id(self, user_id: str) -> Optional[UserEntity]:
        """
        Get user by Keycloak user ID.

        Args:
            user_id: Keycloak user ID

        Returns:
            Optional[User]: User entity if found
        """
        self._ensure_admin_client()

        try:
            kc_user = await self._delegate.keycloak_admin.a_get_user(user_id)
            return self._convert_keycloak_user_to_user_entity(kc_user)
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Get User by ID Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            raise e

    async def directory_get_user_by_email(self, email: str) -> Optional[UserEntity]:
        """
        Get user by email address.

        Args:
            email: User email address

        Returns:
            Optional[User]: User entity if found
        """
        self._ensure_admin_client()

        try:
            users = await self._delegate.keycloak_admin.a_get_users({'email': email})
            if users:
                return self._convert_keycloak_user_to_user_entity(users[0])
            return None
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Get User by Email Error',
                extra_context={'email': email},
                logger=self.logger,
            )
            return None

    async def directory_get_user_by_username(self, username: str) -> Optional[UserEntity]:
        """
        Get user by username.

        Args:
            username: Username

        Returns:
            Optional[User]: User entity if found
        """
        self._ensure_admin_client()

        try:
            users = await self._delegate.keycloak_admin.a_get_users(
                {'username': username}
            )
            if users:
                return self._convert_keycloak_user_to_user_entity(users[0])
            return None
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Get User by Username Error',
                extra_context={'username': username},
                logger=self.logger,
            )
            return None

    async def directory_update_user(
        self, user_id: str, updates: Dict[str, Any]
    ) -> UserEntity:
        """
        Update user information.

        Args:
            user_id: User ID
            updates: Dict of fields to update (Keycloak format)

        Returns:
            User: Updated user entity

        Raises:
            Exception: If update fails
        """
        self._ensure_admin_client()

        try:
            await self._delegate.keycloak_admin.a_update_user(user_id, updates)
            self.logger.info(f'User {user_id} updated successfully')

            # Fetch and return updated user
            updated_user = await self._delegate.keycloak_admin.a_get_user(user_id)
            return self._convert_keycloak_user_to_user_entity(updated_user)
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Update User Error',
                extra_context={'user_id': user_id, 'updates': updates},
                logger=self.logger,
            )
            raise

    async def directory_delete_user(self, user_id: str) -> bool:
        """
        Delete user account (soft delete recommended in production).

        Args:
            user_id: User ID

        Returns:
            bool: True if deleted successfully

        Warning:
            This permanently deletes the user. Consider soft delete instead.
        """
        self._ensure_admin_client()

        try:
            await self._delegate.keycloak_admin.a_delete_user(user_id)
            self.logger.info(f'User {user_id} deleted')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Delete User Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return False

    async def directory_enable_user(self, user_id: str) -> bool:
        """
        Enable user account.

        Args:
            user_id: User ID

        Returns:
            bool: True if enabled successfully
        """
        self._ensure_admin_client()

        try:
            await self._delegate.keycloak_admin.a_update_user(
                user_id=user_id, payload={'enabled': True}
            )
            self.logger.info(f'User {user_id} enabled')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Enable User Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return False

    async def directory_disable_user(self, user_id: str) -> bool:
        """
        Disable user account (soft delete alternative).

        Args:
            user_id: User ID

        Returns:
            bool: True if disabled successfully
        """
        self._ensure_admin_client()

        try:
            await self._delegate.keycloak_admin.a_update_user(
                user_id=user_id, payload={'enabled': False}
            )
            self.logger.info(f'User {user_id} disabled')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Disable User Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return False

    async def directory_search_users(
        self,
        query: Optional[str] = None,
        email: Optional[str] = None,
        username: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[UserEntity]:
        """
        Search users with filters.

        Args:
            query: General search query
            email: Filter by email
            username: Filter by username
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List[User]: List of matching users
        """
        self._ensure_admin_client()

        search_params = {}
        if query:
            search_params['search'] = query
        if email:
            search_params['email'] = email
        if username:
            search_params['username'] = username

        search_params['max'] = limit
        search_params['first'] = offset

        try:
            users = await self._delegate.keycloak_admin.a_get_users(search_params)
            return [self._convert_keycloak_user_to_user_entity(user) for user in users]
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Search Users Error',
                extra_context={
                    'query': query,
                    'email': email,
                    'username': username,
                    'limit': limit,
                    'offset': offset,
                },
                logger=self.logger,
            )
            return []

    # ================================
    # Roles and Permissions
    # ================================

    async def assign_role_to_user(self, user_id: str, role: str) -> bool:
        """
        Assign realm role to user.

        Args:
            user_id: User ID
            role: Role name

        Returns:
            bool: True if assigned successfully
        """
        self._ensure_admin_client()

        try:
            role_obj = await self._delegate.keycloak_admin.a_get_realm_role(role)
            await self._delegate.keycloak_admin.a_assign_realm_roles(
                user_id=user_id, roles=[role_obj]
            )
            self.logger.info(f'Role {role} assigned to user {user_id}')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Assign Role Error',
                extra_context={'user_id': user_id, 'role': role},
                logger=self.logger,
            )
            return False

    async def remove_role_from_user(self, user_id: str, role: str) -> bool:
        """
        Remove realm role from user.

        Args:
            user_id: User ID
            role: Role name

        Returns:
            bool: True if removed successfully
        """
        self._ensure_admin_client()

        try:
            role_obj = await self._delegate.keycloak_admin.a_get_realm_role(role)
            await self._delegate.keycloak_admin.a_delete_realm_roles_of_user(
                user_id=user_id, roles=[role_obj]
            )
            self.logger.info(f'Role {role} removed from user {user_id}')
            return True
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Remove Role Error',
                extra_context={'user_id': user_id, 'role': role},
                logger=self.logger,
            )
            return False

    async def get_user_roles(self, user_id: str) -> List[str]:
        """
        Get all realm roles assigned to user.

        Args:
            user_id: User ID

        Returns:
            List[str]: List of role names
        """
        self._ensure_admin_client()

        try:
            roles = await self._delegate.keycloak_admin.a_get_realm_roles_of_user(
                user_id
            )
            return [role['name'] for role in roles]
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Get User Roles Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return []

    async def get_user_permissions(self, user_id: str) -> List[str]:
        """
        Get effective permissions for user (from roles).

        Args:
            user_id: User ID

        Returns:
            List[str]: List of permission names

        Note:
            Permissions are extracted from role attributes.
            Requires custom role configuration in Keycloak.
        """
        self._ensure_admin_client()

        try:
            # Get composite roles (includes inherited roles)
            roles = (
                await self._delegate.keycloak_admin.a_get_composite_realm_roles_of_user(
                    user_id
                )
            )
            permissions = []

            for role in roles:
                # Extract permissions from role attributes
                role_details = await self._delegate.keycloak_admin.a_get_realm_role(
                    role['name']
                )
                if 'attributes' in role_details:
                    perms = role_details['attributes'].get('permissions', [])
                    permissions.extend(perms)

            # Remove duplicates
            return list(set(permissions))
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Get User Permissions Error',
                extra_context={'user_id': user_id},
                logger=self.logger,
            )
            return []

    # ================================
    # Health and Status
    # ================================

    async def health_check(self) -> Dict[str, Any]:
        """
        Check IAM service health.

        Returns:
            Dict with health status and service information
        """
        settings = get_keycloak_settings()

        try:
            # Try to get realm information as health check
            realm = await self._delegate.keycloak_admin.a_get_realm(
                settings.KEYCLOAK_REALM
            )

            return {
                'status': 'healthy',
                'service': 'keycloak',
                'keycloak_url': settings.KEYCLOAK_HOST,
                'realm': settings.KEYCLOAK_REALM,
                'realm_enabled': realm.get('enabled', False),
                'message': 'Keycloak service is operational',
            }
        except Exception as e:
            report_keycloak_error(
                e,
                title='IAM Health Check Error',
                extra_context={'service': 'keycloak', 'realm': settings.KEYCLOAK_REALM},
                logger=self.logger,
            )
            return {
                'status': 'unhealthy',
                'service': 'keycloak',
                'error': str(e),
                'message': 'Keycloak service is not responding',
            }

    def get_session_id_from_token(self, access_token: str) -> Optional[str]:
        openid_connect = self._delegate.keycloak_openid_connect(
            self.keycloak.realm, self.keycloak.client_id
        )
        key = (
            '-----BEGIN PUBLIC KEY-----\n'
            + openid_connect.public_key()
            + '\n-----END PUBLIC KEY-----'
        )
        try:
            return openid_connect.decode_token(token=access_token, key=key).get('sid')
        except JWTClaimsError:
            # Indicating an Impersonation via Keycloak login strategy
            pass

        return None
