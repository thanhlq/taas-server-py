"""
IMPORTANT:
 - To enable migration of a model, you need to import it in this __init__.py so it registers with the metadata registry.
"""

from advanced_alchemy.base import AdvancedDeclarativeBase

from ._audit_log import AuditLog
from ._email_verification_token import EmailVerificationToken
from ._oauth_account import UserOAuthAccount
from ._password_reset_token import PasswordResetToken
from ._refresh_token import RefreshToken
from ._role import Role
from ._tag import Tag
from ._team import Team
from ._team_invitation import TeamInvitation
from ._team_member import TeamMember
from ._team_roles import TeamRoles
from ._team_tag import team_tag
from ._user import User
from ._user_role import UserRole

# from sqlalchemy.orm import DeclarativeBase

__all__ = [
    'AdvancedDeclarativeBase',
    'AuditLog',
    'EmailVerificationToken',
    'PasswordResetToken',
    'RefreshToken',
    'Role',
    'Tag',
    'Team',
    'TeamInvitation',
    'TeamMember',
    'TeamRoles',
    'User',
    'UserOAuthAccount',
    'UserRole',
    'team_tag',
]
