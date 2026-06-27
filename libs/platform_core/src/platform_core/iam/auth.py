"""Authentication models"""

from typing import List, Optional

from platform_core.serialization import BaseModel


class AuthUser(BaseModel):
    """Represents an authenticated user."""

    id: str
    name: Optional[str] = None
    username: Optional[str] = None
    # family_name: str  # last_name
    # given_name: str  # first_name
    last_name: str = ''
    first_name: str = ''
    # preferred_username: str
    sub: str = ''
    email_verified: bool = False
    roles: List[str] = []
