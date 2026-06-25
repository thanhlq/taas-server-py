from typing import Optional

from core.domain.serializers.api_common import QueryParamObject


class UserFilterParams(QueryParamObject):
    _filter_translations = {
        'first_name': 'icontains',  # name -> name__icontains
        'last_name': 'icontains',  # name -> name__icontains
        'email': 'icontains',  # email -> email__icontains
        'status': 'in',  # status -> status__iexact
    }

    first_name: Optional[str] = None
    email: Optional[str] = None
