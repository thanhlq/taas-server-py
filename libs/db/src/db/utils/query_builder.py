from datetime import datetime
from typing import Any, List, Optional, TypeVar, Union

from foundation.serialization import PagingQueryParam
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from db.models.base import BaseDBModel

OrmModelT = TypeVar('OrmModelT', bound=BaseDBModel)


class QueryBuilder:
    """
    A utility class to build SQLAlchemy queries with filtering, ordering, and pagination.

    Supports flexible AND/OR operations:
    - Regular filters: Implicitly combined with AND
    - OR filters: Use 'or_' prefix for cross-field OR operations
    - Complex queries: Use build_filters_advanced() for explicit AND/OR control

    Examples:
        # Simple AND (implicit)
        filters = {'first_name': 'John', 'age__gte': 18}
        query = QueryBuilder.build_filters(User, None, **filters)

        # OR across multiple fields
        or_filters = {'first_name': 'John', 'last_name': 'Doe'}
        query = QueryBuilder.build_or_filters(User, None, **or_filters)

        # Complex AND/OR combinations
        query = QueryBuilder.build_filters_advanced(
            User, None,
            and_filters={'age__gte': 18, 'is_active': True},
            or_filters={'first_name': 'John', 'email__contains': '@test.com'}
        )
    """

    @staticmethod
    def _build_single_condition(
        model_class: type[OrmModelT], field_name: str, operator: str, value: Any
    ) -> Optional[ColumnElement]:
        """
        Build a single filter condition.

        Args:
            model_class: The DB model class
            field_name: The field name
            operator: The filter operator (eq, gt, icontains, etc.)
            value: The filter value

        Returns:
            SQLAlchemy BinaryExpression or None if field doesn't exist
        """
        # Get the model attribute
        if not hasattr(model_class, field_name):
            return None

        field = getattr(model_class, field_name)

        # Build condition based on operator
        if operator == 'eq':
            if isinstance(value, (list, tuple)):
                return field.in_(value)
            else:
                return field == value
        elif operator == 'neq':
            return field != value
        elif operator == 'icontains':
            return field.ilike(f'%{value}%')
        elif operator == 'contains':
            return field.like(f'%{value}%')
        elif operator == 'gt':
            return field > value
        elif operator == 'gte':
            return field >= value
        elif operator == 'lt':
            return field < value
        elif operator == 'lte':
            return field <= value
        elif operator == 'in':
            if isinstance(value, (list, tuple)):
                return field.in_(value)
            else:
                return field.in_([value])
        elif operator == 'nin':
            if isinstance(value, (list, tuple)):
                return ~field.in_(value)
            else:
                return ~field.in_([value])
        elif operator == 'isnull':
            if value:
                return field.is_(None)
            else:
                return field.is_not(None)
        elif operator == 'startswith':
            return field.like(f'{value}%')
        elif operator == 'istartswith':
            return field.ilike(f'{value}%')
        elif operator == 'endswith':
            return field.like(f'%{value}')
        elif operator == 'iendswith':
            return field.ilike(f'%{value}')
        elif operator == 'ci':
            return field.ilike(f'{value}')
        elif operator == 'iexact':
            return field.ilike(f'{value}')
        elif operator == 'date':
            if isinstance(value, str):
                try:
                    date_value = datetime.strptime(value, '%Y-%m-%d').date()
                except ValueError:
                    raise ValueError(
                        f"Invalid date format for field '{field_name}': {value}"
                    )
            else:
                date_value = value
            return func.date(field) == date_value
        else:
            # Unknown operator, skip
            return None

    @staticmethod
    def build_filters(
        model_class: type[OrmModelT], stm: Optional[Select], **kwargs
    ) -> Select:
        """
        Build SQLAlchemy filter conditions from keyword arguments (implicit AND).

        Args:
            model_class: The DB model class to filter
            stm: Optional existing SELECT statement (if None, creates new one)
            **kwargs: Filter conditions as keyword arguments
                    Key formats:
                    - 'field_name': eq (exact match)
                    - 'field_name__ci': equal with case-insensitive
                    - 'field_name__iexact': case-insensitive exact match
                    - 'field_name__neq': not equal
                    - 'field_name__contains': case-sensitive contains
                    - 'field_name__icontains': case-insensitive contains
                    - 'field_name__startswith' / 'field_name__istartswith'
                    - 'field_name__endswith' / 'field_name__iendswith'
                    - 'field_name__gt': greater than
                    - 'field_name__gte': greater than or equal
                    - 'field_name__lt': less than
                    - 'field_name__lte': less than or equal
                    - 'field_name__in': value in list
                    - 'field_name__nin': value not in list
                    - 'field_name__isnull': is null/not null (True/False)
                    - 'field_name__date': date comparison

        Returns:
            SQLAlchemy Select statement with filters applied (combined with AND)

        Example:
            query = QueryBuilder.build_filters(
                User, None,
                first_name='John',
                age__gte=18,
                status__in=['active', 'pending']
            )
        """

        if stm is None:
            stm = select(model_class)

        conditions = []

        for key, value in kwargs.items():
            if value is None:
                continue

            # Parse field name and operator
            if '__' in key:
                field_name, operator = key.split('__', 1)
            else:
                field_name, operator = key, 'eq'

            # Build condition
            condition = QueryBuilder._build_single_condition(
                model_class, field_name, operator, value
            )

            if condition is not None:
                conditions.append(condition)

        # Apply all conditions with AND
        if conditions:
            stm = stm.where(and_(*conditions))

        return stm

    @staticmethod
    def build_or_filters(
        model_class: type[OrmModelT], stm: Optional[Select], **kwargs
    ) -> Select:
        """
        Build SQLAlchemy filter conditions combined with OR.

        Args:
            model_class: The DB model class to filter
            stm: Optional existing SELECT statement (if None, creates new one)
            **kwargs: Filter conditions as keyword arguments (combined with OR)

        Returns:
            SQLAlchemy Select statement with filters applied (combined with OR)

        Example:
            # Returns users where first_name='John' OR last_name='Doe' OR email contains '@test.com'
            query = QueryBuilder.build_or_filters(
                User, None,
                first_name='John',
                last_name='Doe',
                email__contains='@test.com'
            )
        """

        if stm is None:
            stm = select(model_class)

        conditions = []

        for key, value in kwargs.items():
            if value is None:
                continue

            # Parse field name and operator
            if '__' in key:
                field_name, operator = key.split('__', 1)
            else:
                field_name, operator = key, 'eq'

            # Build condition
            condition = QueryBuilder._build_single_condition(
                model_class, field_name, operator, value
            )

            if condition is not None:
                conditions.append(condition)

        # Apply all conditions with OR
        if conditions:
            stm = stm.where(or_(*conditions))

        return stm

    @staticmethod
    def build_filters_advanced(
        model_class: type[OrmModelT],
        stm: Optional[Select] = None,
        and_filters: Optional[dict] = None,
        or_filters: Optional[dict] = None,
        or_groups: Optional[List[dict]] = None,
    ) -> Select:
        """
        Build complex queries with explicit AND/OR control.

        Args:
            model_class: The DB model class to filter
            stm: Optional existing SELECT statement (if None, creates new one)
            and_filters: Dict of filters combined with AND
            or_filters: Dict of filters combined with OR
            or_groups: List of filter dicts, each group combined with OR,
                      then all groups combined with AND

        Returns:
            SQLAlchemy Select statement with complex filters applied

        Examples:
            # Example 1: age >= 18 AND (first_name='John' OR last_name='Doe')
            query = QueryBuilder.build_filters_advanced(
                User, None,
                and_filters={'age__gte': 18},
                or_filters={'first_name': 'John', 'last_name': 'Doe'}
            )

            # Example 2: (first_name='John' OR first_name='Jane') AND (city='NYC' OR city='LA')
            query = QueryBuilder.build_filters_advanced(
                User, None,
                or_groups=[
                    {'first_name': 'John', 'first_name': 'Jane'},
                    {'city': 'NYC', 'city': 'LA'}
                ]
            )

            # Example 3: age >= 18 AND status='active' AND (first_name contains 'Jo' OR email contains '@test')
            query = QueryBuilder.build_filters_advanced(
                User, None,
                and_filters={'age__gte': 18, 'status': 'active'},
                or_filters={'first_name__contains': 'Jo', 'email__contains': '@test'}
            )
        """

        if stm is None:
            stm = select(model_class)

        all_conditions = []

        # Process AND filters
        if and_filters:
            and_conditions = []
            for key, value in and_filters.items():
                if value is None:
                    continue

                if '__' in key:
                    field_name, operator = key.split('__', 1)
                else:
                    field_name, operator = key, 'eq'

                condition = QueryBuilder._build_single_condition(
                    model_class, field_name, operator, value
                )
                if condition is not None:
                    and_conditions.append(condition)

            if and_conditions:
                all_conditions.append(and_(*and_conditions))

        # Process OR filters
        if or_filters:
            or_conditions = []
            for key, value in or_filters.items():
                if value is None:
                    continue

                if '__' in key:
                    field_name, operator = key.split('__', 1)
                else:
                    field_name, operator = key, 'eq'

                condition = QueryBuilder._build_single_condition(
                    model_class, field_name, operator, value
                )
                if condition is not None:
                    or_conditions.append(condition)

            if or_conditions:
                all_conditions.append(or_(*or_conditions))

        # Process OR groups (each group is OR'd internally, groups are AND'd together)
        if or_groups:
            for group in or_groups:
                group_conditions = []
                for key, value in group.items():
                    if value is None:
                        continue

                    if '__' in key:
                        field_name, operator = key.split('__', 1)
                    else:
                        field_name, operator = key, 'eq'

                    condition = QueryBuilder._build_single_condition(
                        model_class, field_name, operator, value
                    )
                    if condition is not None:
                        group_conditions.append(condition)

                if group_conditions:
                    all_conditions.append(or_(*group_conditions))

        # Combine all conditions with AND
        if all_conditions:
            stm = stm.where(and_(*all_conditions))

        return stm

    @staticmethod
    def order_query(
        model_class: type[OrmModelT], query: Select, order_by: str
    ) -> Select:
        """
        :order_by examples: 'timestamp' order by timestamp ascending,
                            'timestamp__asc' order by timestamp ascending,
                            'timestamp__desc' order by timestamp descending
        """
        try:
            # attr, order = order_by.split("__") if "__" in order_by else (order_by, "asc")

            if '__' in order_by:
                attr, order = order_by.split('__')
            else:
                attr, order = order_by, 'asc'
            if order == 'desc':
                query = query.order_by(getattr(model_class, attr).desc())
            else:
                query = query.order_by(getattr(model_class, attr).asc())
        except ValueError as e:
            # debug_exception(e)
            # query = query.order_by(lambda tx: getattr(tx, order_by))
            raise e

        return query

    @staticmethod
    def paginate_query(query: Select, opts: Union[PagingQueryParam, dict]) -> Select:
        """
        Apply pagination to a query.

        Args:
            query: The SELECT statement to paginate
            opts: Pagination options (PagingQueryParam or dict with 'offset' and 'limit')

        Returns:
            SELECT statement with pagination applied
        """
        if isinstance(opts, dict):
            paging_opts = PagingQueryParam(**opts)  # type: ignore
        else:
            paging_opts = opts

        return query.offset(paging_opts.offset).limit(paging_opts.limit)
