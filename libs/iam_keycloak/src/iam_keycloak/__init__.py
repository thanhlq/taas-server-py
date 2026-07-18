"""The iam implementation using keycloak"""

__version__ = '0.1.0'

# Import main components here for easy access
# from .domain import *
# from .services import *

from .endpoints.kc_admin_endpoint import router as admin_router
from .endpoints.kc_auth_endpoint import router as auth_router
from .endpoints.kc_users_endpoint import router as users_router
from .factory import KeycloakIamServiceFactory

__all__ = ['admin_router', 'users_router', 'auth_router', 'KeycloakIamServiceFactory']
