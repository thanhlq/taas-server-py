from platform_core.serialization import BaseModel
from wrapt import T


class ValueObject(BaseModel):
    """
    Base Value Object:
        - frozen
        - immutable
        - validation on initialization
        - equality by value, not by identity
        - no side effects
        - can be used as dict keys or set members
    """


class Result[T](ValueObject):
    """
    Base Result type for operations that can succeed or fail, without exceptions.

    Subclasses should define fields for the successful data and error information.
    """

    data: T | None = None


class ListResult[T](ValueObject):
    """
    Base Result type for operations that can succeed or fail, without exceptions.

    Subclasses should define fields for the successful data and error information.
    """

    data: list[T]
    total_count: int
