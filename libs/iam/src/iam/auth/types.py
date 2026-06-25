from iam.auth.schemas import SignupRequest
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from starlette.authentication import AuthenticationBackend


class IamDirectoryServiceT(ABC):

    # REQ-AUTH-001: User Registration
    @abstractmethod
    async def create_directory_user(
        self, registration_data: SignupRequest, **kwargs
    ) -> None:
        """
        REQ-AUTH-001: User Registration

        - 2.1.1.1: Email/password registration
        - 2.1.1.2: Social registration (Google, Microsoft)
        - 2.1.1.3: Email verification workflow (optional)
        - 2.1.1.4: User profile creation with custom attributes

        Register a new user, this user is normally inactive until email verified.
        The user will be assigned to a new tenant.
        """
        pass
