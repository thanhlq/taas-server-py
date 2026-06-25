#  HTTP/1.1 200 OK
#   Content-Type: application/json

#   {
#    "sub": "248289761001",
#    "name": "Jane Doe",
#    "given_name": "Jane",
#    "family_name": "Doe",
#    "preferred_username": "j.doe",
#    "email": "janedoe@example.com",
#    "picture": "http://example.com/janedoe/me.jpg"
#   }

from datetime import datetime
from typing import Optional

from core.iam.domain.entities import OpenIDUserInfo
from pydantic import BaseModel
from starlette.authentication import BaseUser


class KeycloakAuthUser(OpenIDUserInfo):
    @property
    def is_authenticated(self) -> bool:
        raise NotImplementedError()  # pragma: no cover

    @property
    def display_name(self) -> str:
        return self.preferred_username

    @property
    def identity(self) -> str:
        return self.preferred_username


class KeycloakUser(BaseModel):
    """
    id
    email
    email_constraint
    email_verified
    enabled
    federation_link
    first_name
    last_name
    realm_id
    username
    created_timestamp
    service_account_client_link
    not_before
    """

    id: str
    email: Optional[str] = None
    email_constraint: Optional[str] = None
    email_verified: bool = False
    enabled: bool = False
    federation_link: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    realm_id: Optional[str] = None
    username: Optional[str]
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    created_timestamp: Optional[int] = None
    service_account_client_link: Optional[str] = None
    not_before: int = 0

    @property
    def created_on(self) -> datetime | None:
        # created_timestamp = timestamp in milliseconds instead of seconds
        if self.created_timestamp:
            return datetime.fromtimestamp(self.created_timestamp / 1000)
        return None

    attributes: dict = {}
