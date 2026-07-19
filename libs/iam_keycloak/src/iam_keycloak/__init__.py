"""The iam implementation using keycloak"""

__version__ = '0.1.0'

from .factory import KeycloakIamServiceFactory as IamServiceFactory

""" Export the central factory to create Keycloak IAM related service and components. """

__all__ = ['IamServiceFactory']
