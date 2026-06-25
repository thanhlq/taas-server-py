from datetime import timedelta

from core.api.api_serializers import (
    ResponseStatus,
    SuccessResponse,
    create_success_response,
)
from core.common.types import ICacheService
from core.conf import get_app_settings
from core.fastapi.utils.request_utils import get_request_id, get_trace_id
from core.iam.auth.auth_helpers import check_user_signin_lockout
from core.iam.domain.entities import UserEntity
from core.iam.domain.schemas.auth import (
    AuthResponse,
    PasswordAuthRequest,
    UserEmailVerification,
    UserRegistrationForm,
    UserRegistrationOut,
)
from core.iam.factory import IamFactory
from core.iam.iam_constants import IamConstants
from core.iam.types import IIamService
from core.iam.utils.iam_utils import find_bearer_token
from core.observability.log_factory import LogFactory
from core.observability.trace_factory import TracingFactory
from core.utils.debug import debug_exception
from core.utils.id import generate_otp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi_cache.decorator import cache

from ..db.kc_db_factory import KCDBFactory

settings = get_app_settings()

router = APIRouter(prefix='/auth', tags=['Authentication'])

API_CACHE_EXPIRE = settings.API_CACHE_EXPIRE  # Default to 60 seconds if not set


def get_iam_service() -> IIamService:
    iamServiceFactory = IamFactory.get_instance().get_iam_service_factory()
    iam_service = iamServiceFactory.get_iam_service()
    return iam_service


def get_cache_service() -> ICacheService:
    iam_service = IamFactory.get_instance().get_cache_service()
    return iam_service


@router.post(
    '/signup/verification/email',
    response_model=SuccessResponse[UserRegistrationOut],
    #  response_model=UserRegistrationForm
)
@cache(expire=60)  # Cache for 60 seconds
async def signup_01_verify_email(
    req: Request, response: Response, signup_form: UserEmailVerification
):
    """
    The email verification endpoint for user registration.
    1. Verifies if the provided email is already registered.
    2. Returns a success response indicating the verification result.
        2.1 There is also an otp sent to the email for actual verification in the next step (02).
    """
    user_repo = KCDBFactory.get_instance().get_async(UserEntity)
    user = await user_repo.first(email=signup_form.email)

    if user is not None:
        return create_success_response(
            data={'email': signup_form.email, 'isRegistered': True},
            status=ResponseStatus.FAIL,
            request_id=get_request_id(req),
            trace_id=get_trace_id(req),
        )
    else:
        try:
            iam_service = get_iam_service()

            otp = generate_otp(6)

            # save this otp somewhere (e.g., in-memory cache, database) associated with the email
            # so that it can be verified in the next step of registration.
            cache_service = get_cache_service()
            await cache_service.set(
                f'{IamConstants.CACHE_SIGNUP_OTP_PREFIX}{signup_form.email}',
                f'{otp}:{signup_form.email}',
                timedelta(seconds=IamConstants.OTP_SIGNUP_EMAIL_VALIDITY_SECONDS),
            )  # OTP valid for 5 minutes
            await iam_service.signup_send_otp_to_email(
                signup_form.email,
                otp,
                title='Verify your email for registration',
                description='Use the following OTP during registration.',
            )

            # user_registration_response: UserRegistrationResponse = (
            #     await iam_service.register_user(signup_form)
            # )

            # if user_registration_response.status != 'OK':
            #     raise HTTPException(
            #         status_code=400, detail=user_registration_response.message
            #     )

            return create_success_response(
                data={'email': signup_form.email, 'isRegistered': False},
                request_id=get_request_id(req),
                trace_id=get_trace_id(req),
            )

        except Exception as exc:
            debug_exception(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    '/signup',
    response_model=SuccessResponse[UserRegistrationOut],
    #  response_model=UserRegistrationForm
)
async def signup_02_register(
    req: Request, response: Response, signup_form: UserRegistrationForm
):
    """User Registration Endpoint
    - Registers a new user with the provided signup form data.
    - Returns a success response with registration details upon successful registration.
    - An accompanied tenant will be created for the new user.
    """
    try:
        iam_service = get_iam_service()

        user_registration_response: UserRegistrationOut = (
            await iam_service.create_directory_user(signup_form)
        )

        if user_registration_response.status != 'OK':
            raise HTTPException(
                status_code=400, detail=user_registration_response.message
            )

        return create_success_response(
            data=user_registration_response,
            request_id=get_request_id(req),
            trace_id=get_trace_id(req),
        )

    except Exception as exc:
        debug_exception(exc)
        LogFactory().get_logger().error(
            'Error during user registration', error=str(exc), exc_info=True
        )
        headers = {'X-Request-ID': get_request_id(req)}
        if TracingFactory().get_tracing_manager() is not None:
            trace_id: str | None = (
                TracingFactory().get_tracing_manager().get_current_trace_id()
            )
            headers['X-Trace-ID'] = trace_id or 'N/A'
        raise HTTPException(
            status_code=500,
            detail=str(exc),
            headers=headers,
        ) from exc


@router.post('/login', response_model=AuthResponse)
async def login(request: Request, response: Response, login_form: PasswordAuthRequest):
    await check_user_signin_lockout(
        request, login_form
    )  # raise exception if locked out
    iam_service = get_iam_service()
    auth = await iam_service.authenticate_password(login_form)
    return auth


@router.post('/logout')
async def logout(request: Request):
    """The logout endpoint allows a user to terminate their current session by invalidating the access token provided in the request header."""

    # await authorization_service.delete_session(request=request)
    iam_service = get_iam_service()
    token = find_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail='Missing access token')

    result = await iam_service.logout_by_access_token(token)

    return dict(status='OK' if result else 'FAIL')
