import msgspec


class BaseEntity(msgspec.Struct):
    """
    - For entities that are stored in the database.
    - Normally this is 1-1 mapping with the database table,
    """

    pass
