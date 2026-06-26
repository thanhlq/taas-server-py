"""Contains all common schemas used in the IAM module."""

from platform_core.serialization import ApiRequest, BaseModel


class Role(BaseModel):
    """Role properties to use for a request."""

    name: str
    description: str


class Group(BaseModel):
    """Group properties to use for a request."""

    name: str
    description: str
