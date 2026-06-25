"""
A realm based user repository for Keycloak.
"""

import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from core.common.utils import parse_json
from core.conf.settings import get_app_settings
from core.db.engine import DBAsyncSession, Query, sql_aliased
from core.db.sa.raw_sql import select_by_sql
from core.db.types import IRepositoryFactory
from core.domain.serializers import GraphTimeFrames
from core.saas import is_saas_mode
from core.utils.debug import print_dict_pretty
from core.utils.string_utils import camel_to_snake, snake_to_camel
from dateutil.relativedelta import relativedelta
from iam_keycloak.db.kc_db import kc_db_session_async as db_session_async
from iam_keycloak.db.kc_models import (
    RealmOrm as KeycloakRealmOrm,
)
from iam_keycloak.db.kc_models import (
    RoleOrm as KeycloakRoleOrm,
)
from iam_keycloak.db.kc_models import (
    UserAttributeOrm as KeycloakUserAttributeOrm,
)
from iam_keycloak.db.kc_models import (
    UserOrm as KeycloakUserEntityOrm,
)
from iam_keycloak.db.repositories.kc_base_repo import KeycloakBaseRepository
from sqlalchemy import select

from ...constants import USER_ATTR_TRUE_VAL
from ...domains.entities import KeycloakUser


# @TracingFactory.instrument # type: ignore
# @instrument
class DirectoryUserRepository(
    KeycloakBaseRepository[KeycloakUserEntityOrm, KeycloakUser]
):
    """
    The implementation of a sepcific realm based user repository for Keycloak.
    """

    _realm_name: str | None = None
    _realm_id = None

    def __init__(self, factory: IRepositoryFactory = None, **kwargs):
        super().__init__(
            KeycloakUserEntityOrm,
            KeycloakUser,
            factory=factory,
            **kwargs,
            id_column='id',
            load_relations=['attributes', 'realm', 'roles'],
        )
        settings = get_app_settings()
        if not is_saas_mode():
            self._realm_name = settings.KEYCLOAK_REALM
        # self.realm_name = realm_name or settings.KEYCLOAK_REALM

    @property
    def realm_name(self) -> str:
        if self._realm_name is None:
            settings = get_app_settings()
            self._realm_name = settings.KEYCLOAK_REALM
            return self._realm_name
        else:
            return self._realm_name

    def set_realm(self, realm_id: str = None, realm_name: str | None = None):
        self._realm_id = realm_id
        self._realm_name = realm_name

    # @db_session_async
    # async def list(self, session: DBAsyncSession, **kwargs) -> list[KeycloakUser]:
    #     raw_db_results = await self.db_list(session, **kwargs)
    #     return super().from_orms(raw_db_results, **kwargs)

    def _filter(self, query, **kwargs):
        # context_data: RequestContextData = kwargs.pop(CONTEXT_DATA_PARAM)
        # realm_id = context_data.user.realm_id
        if self._realm_id:
            query = query.join(KeycloakUserEntityOrm.realm).where(
                KeycloakRealmOrm.id == self._realm_id
            )
        elif self.realm_name:
            query = query.join(KeycloakUserEntityOrm.realm).where(
                KeycloakRealmOrm.name == self.realm_name
            )
        else:
            raise ValueError(
                'realm_id or realm_name must be set before filtering users.'
            )
        query, _kwargs = kwargs_handler(query, kwargs)
        return super()._filter(query, **_kwargs)

    @db_session_async
    async def phone_number_exists(
        self, user_uuid: str, phone_number: str, session: DBAsyncSession
    ) -> bool:
        # IMPORTANT: This query is tailored to the current database structure of Keycloak as of version==21.1.2.
        # If Keycloak is updated and its database structure changes, this query MUST be revisited
        # and potentially adjusted to remain accurate and efficient.
        settings = get_app_settings()
        result = await select_by_sql(
            """
            SELECT u.id
            FROM user_entity AS u
            JOIN user_attribute AS a ON u.id = a.user_id
            JOIN realm AS r ON u.realm_id = r.id
            WHERE r.name = $realm
            AND a.name = 'phone1'
            AND CAST(a.value AS json)->>'number' = $phone_number
            AND u.id != $user_uuid
            LIMIT 1
        """,
            {
                'realm': settings.KEYCLOAK_REALM,
                'phone_number': phone_number,
                'user_uuid': user_uuid,
            },
            session=session,
        )

        return len(result) > 0

    @db_session_async
    async def list_between_dates(self, timeframe, session: DBAsyncSession, **kwargs):
        settings = get_app_settings()
        end_of_today = datetime.fromtimestamp(time.time()).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        timespan = GraphTimeFrames.get(timeframe, default=7)
        start_date = end_of_today - (
            timedelta(hours=timespan)
            if timeframe == '24h'
            else (
                relativedelta(months=timespan)
                if timeframe == '1y'
                else timedelta(days=timespan)
            )
        )

        result = []
        # created_timestamp is in microseconds
        if timeframe == '1y':
            result = await select_by_sql(
                """SELECT count(date_trunc('month', TO_TIMESTAMP(u.created_timestamp / 1000)::date)::date), date_trunc('month', TO_TIMESTAMP(u.created_timestamp / 1000)::date)::date
                                    FROM user_entity AS u
                                    JOIN realm AS r ON u.realm_id = r.id
                                    WHERE r.name = $realm AND TO_TIMESTAMP(u.created_timestamp / 1000)::date >= $start_date
                                    GROUP BY date_trunc('month', TO_TIMESTAMP(u.created_timestamp / 1000)::date)::date
                                    ORDER BY date_trunc('month', TO_TIMESTAMP(u.created_timestamp / 1000)::date)::date asc
                                    """,
                {'realm': settings.KEYCLOAK_REALM, 'start_date': start_date},
                session,
            )

        elif timeframe == '24h':
            result = await select_by_sql(
                """SELECT count(date_trunc('hour', TO_TIMESTAMP(u.created_timestamp / 1000)::timestamp )::timestamp ), date_trunc('hour', TO_TIMESTAMP(u.created_timestamp / 1000)::timestamp )::timestamp
                                    FROM user_entity AS u
                                    JOIN realm AS r ON u.realm_id = r.id
                                    WHERE r.name = $realm AND TO_TIMESTAMP(u.created_timestamp / 1000)::timestamp  >= $start_date
                                    GROUP BY date_trunc('hour', TO_TIMESTAMP(u.created_timestamp / 1000)::timestamp )::timestamp
                                    ORDER BY date_trunc('hour', TO_TIMESTAMP(u.created_timestamp / 1000)::timestamp )::timestamp  asc
                                    """,
                {'realm': settings.KEYCLOAK_REALM, 'start_date': start_date},
                session,
            )
        else:
            result = await select_by_sql(
                """SELECT count(TO_TIMESTAMP(u.created_timestamp / 1000)::date), TO_TIMESTAMP(u.created_timestamp / 1000)::date
                        FROM user_entity AS u
                        JOIN realm AS r ON u.realm_id = r.id
                        WHERE r.name = $realm AND TO_TIMESTAMP(u.created_timestamp / 1000)::date >= $start_date
                        GROUP BY TO_TIMESTAMP(u.created_timestamp / 1000)::date
                        ORDER BY TO_TIMESTAMP(u.created_timestamp / 1000)::date asc
                        """,
                {'realm': settings.KEYCLOAK_REALM, 'start_date': start_date},
                session,
            )

        counts = []
        for date in result:
            # date can be a tuple, list, or an object with attributes
            if isinstance(date, (tuple, list)) and len(date) >= 2:
                counts.append(
                    [
                        date[1].strftime(
                            f'%Y-%m-%d{" %H:%M:%S" if timeframe == "24h" else ""}'
                        ),
                        date[0],
                    ]
                )
            elif hasattr(date, '__len__') and len(date) >= 2:
                date_vals = (
                    list(date.values()) if hasattr(date, 'values') else list(date)
                )
                counts.append(
                    [
                        date_vals[1].strftime(
                            f'%Y-%m-%d{" %H:%M:%S" if timeframe == "24h" else ""}'
                        ),
                        date_vals[0],
                    ]
                )
            else:
                try:
                    date_val = (
                        date[1]
                        if hasattr(date, '__getitem__')
                        else getattr(
                            date,
                            list(date.keys())[1] if hasattr(date, 'keys') else 'date',
                        )
                    )
                    count_val = (
                        date[0]
                        if hasattr(date, '__getitem__')
                        else getattr(
                            date,
                            list(date.keys())[0] if hasattr(date, 'keys') else 'count',
                        )
                    )
                    counts.append(
                        [
                            date_val.strftime(
                                f'%Y-%m-%d{" %H:%M:%S" if timeframe == "24h" else ""}'
                            ),
                            count_val,
                        ]
                    )
                except (IndexError, KeyError, AttributeError) as e:
                    print(f'Error processing date record: {date}, error: {e}')
                    continue
        return counts

    def from_orm(self, obj: KeycloakUserEntityOrm, **kwargs) -> KeycloakUser:
        # related_objects = kwargs.get("related_objects", True)
        obj_dict = self.orm_to_dict(
            obj, exclude={'attributes', 'realm', 'roles', 'groups'}
        )
        parsed_attributes: Dict[str, Any] = {}
        userDefAttributes = KeycloakUser.__annotations__

        for attribute in obj.attributes:
            name = camel_to_snake(attribute.name)
            if userDefAttributes.get(name) is None:
                print(
                    f'Skipping attribute: {name} as it is not defined in KeycloakUser annotations.'
                )
                continue

            print(f'attribute: {name} = {attribute.value}')
            value = attribute.value

            if (
                KeycloakUser.__annotations__.get(name) == Optional[bool]
                or KeycloakUser.__annotations__.get(name) is bool
            ):
                value = attribute.value == USER_ATTR_TRUE_VAL
            parsed_attributes[name] = value

        # obj_dict = {k: v for k, v in _obj_dict.items() if k in KeycloakUser.__annotations__.keys()}
        phone1 = parsed_attributes.pop('phone1', None)
        phone2 = parsed_attributes.pop('phone2', None)
        parsed_attributes['phone1'] = parse_json(phone1) if phone1 is not None else None
        parsed_attributes['phone2'] = parse_json(phone2) if phone2 is not None else None

        roles = [role_mapping.name for role_mapping in obj.roles]

        # user: User = User(
        #     family_name=obj_dict.get('last_name', ''),
        #     given_name=obj_dict.get('first_name', ''),
        #     preferred_username=obj_dict.get('username', ''),
        #     sub=obj_dict.get('id', ''),
        #     roles=roles,
        #     **obj_dict,
        #     **parsed_attributes,
        # )

        # print_dict_pretty(obj_dict, 'User ORM dict')
        user: KeycloakUser = KeycloakUser(
            id=obj_dict.get('id', ''),
            last_name=obj_dict.get('last_name', ''),
            first_name=obj_dict.get('first_name', ''),
            username=obj_dict.get('username', ''),
            sub=obj_dict.get('id', ''),
            roles=roles,
            **obj_dict,
            **parsed_attributes,
        )
        return user


def kwargs_handler(query: Query, kwargs: dict) -> Tuple[Query, dict]:
    _kwargs = dict()
    for key, value in kwargs.items():
        if key.startswith('attribute__'):
            attr_key, *operator = key.replace('attribute__', '').split('__')
            operator = operator[0] if operator else None
            attr_key = snake_to_camel(attr_key)

            # Create alias for attributes table to avoid conflicts
            attr_alias = sql_aliased(KeycloakUserAttributeOrm)

            # Join with attributes and filter by attribute name
            query = query.join(
                attr_alias, KeycloakUserEntityOrm.id == attr_alias.user_id
            )
            query = query.where(attr_alias.name == attr_key)

            if operator:
                if operator == 'neq':
                    query = query.where(attr_alias.value != value)
                elif operator == 'gt':
                    query = query.where(attr_alias.value > value)
                elif operator == 'gte':
                    query = query.where(attr_alias.value >= value)
                elif operator == 'lt':
                    query = query.where(attr_alias.value < value)
                elif operator == 'lte':
                    query = query.where(attr_alias.value <= value)
                elif operator == 'nin':
                    query = query.where(~attr_alias.value.in_(value))
                elif operator == 'in':
                    query = query.where(attr_alias.value.in_(value))
                elif operator == 'ci':
                    query = query.where(attr_alias.value.ilike(value))
                elif operator == 'has':
                    query = query.where(attr_alias.value.ilike(f'%{value}%'))
            else:
                query = query.where(attr_alias.value == value)

        elif key.startswith('role'):
            operator = key.replace('role__', '') if re.search('__', key) else None

            # Create alias for roles relationship
            role_alias = sql_aliased(KeycloakRoleOrm)

            # Join with roles through the many-to-many relationship
            query = query.join(KeycloakUserEntityOrm.roles.of_type(role_alias))

            if operator:
                if operator == 'neq':
                    query = query.where(role_alias.name != value)
                elif operator == 'nin':
                    # For NOT IN, we need a subquery
                    subquery = (
                        select(KeycloakUserEntityOrm.id)
                        .join(KeycloakUserEntityOrm.roles.of_type(role_alias))
                        .where(role_alias.name.in_(value))
                    )
                    query = query.where(~KeycloakUserEntityOrm.id.in_(subquery))
                elif operator == 'in':
                    query = query.where(role_alias.name.in_(value))
                elif operator == 'ci':
                    query = query.where(role_alias.name.ilike(value))
                elif operator == 'has':
                    query = query.where(role_alias.name.ilike(f'%{value}%'))
            else:
                query = query.where(role_alias.name == value)
            query = query.distinct()

        elif key.startswith('search'):
            value_lower = value.lower()

            # Create subquery for attribute search
            attr_subquery = select(KeycloakUserAttributeOrm)
            attr_subquery = attr_subquery.where(
                (KeycloakUserAttributeOrm.user_id == KeycloakUserEntityOrm.id)
                & (KeycloakUserAttributeOrm.name == 'miniId')
                & (KeycloakUserAttributeOrm.value.ilike(f'%{value_lower}%'))
            ).exists()

            query = query.where(
                KeycloakUserEntityOrm.first_name.ilike(f'%{value_lower}%')
                | KeycloakUserEntityOrm.last_name.ilike(f'%{value_lower}%')
                | KeycloakUserEntityOrm.username.ilike(f'%{value_lower}%')
                | KeycloakUserEntityOrm.email.ilike(f'%{value_lower}%')
                | KeycloakUserEntityOrm.id.ilike(f'%{value_lower}%')
                | attr_subquery
            )
        elif key.startswith('account_status'):
            # FOR ANY CHANGES HERE, MAKE EQUAL CHANGES IN get_account_status() AND VICE-VERSA
            # from core.iam.domain import UserProfileKycInfoStatus

            value_lower = value.lower()

            if value_lower == UserSubscriptionPackage.PRO:
                # Convert complex Pony ORM logic to SQLAlchemy conditions
                condition1 = KeycloakUserEntityOrm.attributes_string.like(
                    '%kycStatus:partial%'
                ) & KeycloakUserEntityOrm.attributes_string.like('%userType:business%')

                condition2 = (
                    KeycloakUserEntityOrm.attributes_string.like('%kycStatus:partial%')
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoApplicantForm:verified%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoRegulatoryForm:verifying%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoFinishedVerification:verifying%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoProfOfResidence:verifying%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoIdDocument:verifying%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoLivnessCheck:verifying%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoRegulatoryForm:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoFinishedVerification:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoProfOfResidence:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoIdDocument:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoLivnessCheck:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoRejected:true%'
                    )
                )

                query = query.where(condition1 | condition2).distinct()

            elif value_lower == UserSubscriptionPackage.BUSINESS:
                query = query.where(
                    KeycloakUserEntityOrm.attributes_string.like('%kycStatus:partial%')
                    & (
                        KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoRegulatoryForm:verifying%'
                        )
                        | KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoFinishedVerification:verifying%'
                        )
                        | KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoProfOfResidence:verifying%'
                        )
                        | KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoIdDocument:verifying%'
                        )
                        | KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoLivnessCheck:verifying%'
                        )
                    )
                    & ~(
                        KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoRegulatoryForm:verifying%'
                        )
                        & KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoFinishedVerification:verifying%'
                        )
                        & KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoProfOfResidence:verifying%'
                        )
                        & KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoIdDocument:verifying%'
                        )
                        & KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoLivnessCheck:verifying%'
                        )
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoRegulatoryForm:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoFinishedVerification:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoProfOfResidence:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoIdDocument:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoLivnessCheck:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoRejected:true%'
                    )
                ).distinct()

            elif value_lower == UserSubscriptionPackage.BANNED:
                query = query.where(
                    KeycloakUserEntityOrm.attributes_string.like('%kycStatus:banned%')
                ).distinct()

            elif value_lower == UserSubscriptionPackage.REJECTED:
                condition1 = KeycloakUserEntityOrm.attributes_string.like(
                    '%kycInfoRejected:true%'
                )

                condition2 = (
                    KeycloakUserEntityOrm.attributes_string.like('%kycStatus:partial%')
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoStartVerification:verified%'
                    )
                    & (
                        KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoApplicantForm:rejected%'
                        )
                        | KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoRegulatoryForm:rejected%'
                        )
                        | KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoFinishedVerification:rejected%'
                        )
                        | KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoProfOfResidence:rejected%'
                        )
                        | KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoIdDocument:rejected%'
                        )
                        | KeycloakUserEntityOrm.attributes_string.like(
                            '%kycInfoLivnessCheck:rejected%'
                        )
                    )
                )

                query = query.where(condition1 | condition2).distinct()

            elif value_lower == UserSubscriptionPackage.FULLY_VERIFIED:
                condition1 = (
                    KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoFinishedVerification:verified%'
                    )
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycStatus:completed%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoRejected:true%'
                    )
                )

                condition2 = KeycloakUserEntityOrm.attributes_string.like(
                    '%kycStatus:completed%'
                ) & KeycloakUserEntityOrm.attributes_string.like('%userType:business%')

                query = query.where(condition1 | condition2).distinct()

            elif value_lower == UserSubscriptionPackage.FREE:
                condition1 = (
                    ~KeycloakUserEntityOrm.attributes_string.like('%kycStatus:partial%')
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoFinishedVerification:verified%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoFinishedVerification:verifying%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoFinishedVerification:rejected%'
                    )
                    & ~KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoRejected:true%'
                    )
                )

                condition2 = (
                    KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoApplicantForm:not_completed%'
                    )
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoRegulatoryForm:not_completed%'
                    )
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoFinishedVerification:not_completed%'
                    )
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoProfOfResidence:not_completed%'
                    )
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoIdDocument:not_completed%'
                    )
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoLivnessCheck:not_completed%'
                    )
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycInfoStartVerification:verified%'
                    )
                    & KeycloakUserEntityOrm.attributes_string.like(
                        '%kycStatus:partial%'
                    )
                )

                query = query.where(condition1 | condition2).distinct()
        else:
            _kwargs[key] = value
    return query, _kwargs
