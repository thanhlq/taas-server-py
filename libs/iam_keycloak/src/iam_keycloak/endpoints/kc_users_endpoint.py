from typing import Annotated, Any, Optional

from core.api.api_serializers import (
    PaginatedSuccessResponse,
    create_paginated_success_response,
)
from core.common.constants import PAGINATION_PARAM_KEY
from core.conf import get_app_settings
from core.domain.value_objects import ListResult
from core.fastapi.utils.dependency_injection import PagingOptDep
from core.iam.domain.entities import UserEntity
from core.iam.domain.entities.user import UserOut
from core.observability.log_factory import LogFactory
from core.utils.debug import debug_exception
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi_cache.decorator import cache

from ..db.kc_db_factory import KCDBFactory
from ..domains.schemas.api_schemas import UserFilterParams

settings = get_app_settings()

router = APIRouter(prefix='/users')

API_CACHE_EXPIRE = settings.API_CACHE_EXPIRE  # Default to 60 seconds if not set


@router.get(
    '',
    response_model=PaginatedSuccessResponse[UserOut],
)
# @cache(expire=settings.API_CACHE_EXPIRE)
async def list_users(
    req: Request, opts: PagingOptDep, filter: Annotated[dict, Depends(UserFilterParams)]
) -> Any:
    """
    API Endpoint to list users with non-sensitive information, can be used for user selection in various
    parts of the application as select for assigning tasks, projects, etc.
    """

    # params = locals().copy()
    # query_params = {
    #     attr: params[attr] for attr in [x for x in req.query_params if x in params]
    # }

    filter_dict = filter.to_filters()

    filter_dict[PAGINATION_PARAM_KEY] = opts

    print(f'list_users - query_params: {filter_dict}')

    # not to list the platform user
    filter_dict['email__isnull'] = False

    try:
        user_repo = KCDBFactory.get_instance().get_async(UserEntity)
        users = await user_repo.list(**filter_dict)
        count = await user_repo.count(**filter_dict)
        user_responses = [
            UserOut(
                **{
                    k: getattr(user, k)
                    for k in UserOut.model_fields.keys()
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
        LogFactory().get_logger().error(f'Error occurred while listing users: {str(e)}')
        raise HTTPException(status_code=500, detail='Internal Server Error')
