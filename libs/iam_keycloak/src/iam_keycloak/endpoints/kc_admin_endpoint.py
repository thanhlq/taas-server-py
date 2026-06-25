from typing import Annotated, Any, Optional, cast

from core.api.api_serializers import (
    PaginatedSuccessResponse,
    SuccessResponse,
    create_paginated_success_response,
    create_success_response,
)
from core.common.constants import PAGINATION_PARAM_KEY
from core.conf import get_app_settings
from core.domain.api import RequestContextData
from core.domain.value_objects import ListResult
from core.fastapi.utils.dependency_injection import PagingOptDep
from core.fastapi.utils.request_utils import (
    build_request_context,
    get_request_id,
    get_trace_id,
)
from core.iam.domain.entities import UserEntity
from core.iam.domain.entities.user import UserAdminOut
from core.iam.factory import IamFactory
from core.iam.types import IIamService
from core.observability.log_factory import LogFactory
from core.utils.debug import debug_exception
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi_cache.decorator import cache

from ..db.kc_db_factory import KCDBFactory
from ..db.repositories.kc_directory_user_repo import DirectoryUserRepository
from ..domains.schemas.api_schemas import UserFilterParams

settings = get_app_settings()

router = APIRouter(prefix='/admin')

API_CACHE_EXPIRE = settings.API_CACHE_EXPIRE  # Default to 60 seconds if not set


@router.get(
    '/users',
    response_model=PaginatedSuccessResponse[UserAdminOut],
)
# @cache(expire=settings.API_CACHE_EXPIRE)
async def admin_list_users(
    req: Request, opts: PagingOptDep, filter: Annotated[dict, Depends(UserFilterParams)]
) -> Any:
    """
    The endpoint to list users with sensitive information for administration purposes.
    """
    logger = LogFactory().get_logger(__name__)

    filter_dict = filter.to_filters()
    filter_dict[PAGINATION_PARAM_KEY] = opts
    # not to list the platform user
    filter_dict['email__isnull'] = False

    print(f'filter dict: {filter_dict}')

    try:
        context_data: RequestContextData = build_request_context(req)
        logger.debug('Admin List Users - context_data Params: %s', context_data)
        user_repo: DirectoryUserRepository = cast(
            DirectoryUserRepository, KCDBFactory.get_instance().get_async(UserEntity)
        )
        # user_repo.set_realm(realm_id=context_data.user.realm_id)
        # user_repo.set_realm(realm_name='emtrack')
        users = await user_repo.list(**filter_dict)
        count = 0  # await user_repo.count(**filter_dict)
        user_responses = [
            UserAdminOut(
                **{
                    k: getattr(user, k)
                    for k in UserAdminOut.model_fields.keys()
                    if hasattr(user, k)
                }
            )
            for user in users
        ]
        return create_paginated_success_response(
            result=ListResult(
                data=user_responses,
                total_count=count,
            ),
            req=req,
            opts=opts,
        )
    except Exception as e:
        debug_exception(e)
        raise HTTPException(status_code=500, detail='Internal Server Error')


@router.get(
    '/users/:user_id',
    response_model=SuccessResponse[UserEntity],
)
# @cache(expire=settings.API_CACHE_EXPIRE)
async def admin_get_user(
    req: Request,
    user_id: str,
    opts: PagingOptDep,
    filter: Annotated[dict, Depends(UserFilterParams)],
) -> Any:
    """
    The endpoint to list users with sensitive information for administration purposes.
    """
    logger = LogFactory().get_logger(__name__)

    filter_dict = filter.to_filters()
    filter_dict[PAGINATION_PARAM_KEY] = opts
    # not to list the platform user
    filter_dict['email__isnull'] = False

    print(f'filter dict: {filter_dict}')

    try:
        context_data: RequestContextData = build_request_context(req)
        logger.debug('Admin Get Users - context_data Params: %s', context_data)

        iam_service: IIamService = (
            IamFactory.get_instance().get_iam_service_factory().get_iam_service()
        )
        iam_user_detail: UserEntity = await iam_service.directory_get_user_by_id(user_id)

        print(f'iam user detail: {iam_user_detail}')

        return create_success_response(
            data=iam_user_detail,
            request_id=get_request_id(req),
            trace_id=get_trace_id(req),
        )
    except Exception as e:
        debug_exception(e)
        raise HTTPException(status_code=500, detail='Internal Server Error')
