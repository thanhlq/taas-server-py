from __future__ import annotations

from typing import Any

import db.models.core as core_models
from db import BaseAsyncRepository
from foundation.db.types import DBAsyncScopedSession, DBAsyncSession

from ._audit_log_repo import AuditLogRepository
from ._casbin_rule_repo import CasbinRuleRepository
from ._email_verification_token_repo import EmailVerificationTokenRepository
from ._password_reset_token_repo import PasswordResetTokenRepository
from ._refresh_token_repo import RefreshTokenRepository
from ._role_repo import RoleRepository
from ._tag_mapping_repo import TagMappingRepository
from ._tag_repo import TagRepository
from ._team_invitation_repo import TeamInvitationRepository
from ._team_member_repo import TeamMemberRepository
from ._team_repo import TeamRepository
from ._user_oauth_account_repo import UserOAuthAccountRepository
from ._user_repo import UserRepository
from ._user_role_repo import UserRoleRepository

try:
    from ._organization_repo import OrganizationTableRepository
except Exception:
    OrganizationTableRepository: type[BaseAsyncRepository[Any]] | None = None

try:
    from ._tenant_repo import TenantTableRepository
except Exception:
    TenantTableRepository: type[BaseAsyncRepository[Any]] | None = None


type SessionLike = DBAsyncSession | DBAsyncScopedSession


ALL_REPOSITORIES = {
    'audit_log': AuditLogRepository,
    'casbin_rule': CasbinRuleRepository,
    'email_verification_token': EmailVerificationTokenRepository,
    'password_reset_token': PasswordResetTokenRepository,
    'refresh_token': RefreshTokenRepository,
    'role': RoleRepository,
    'tag': TagRepository,
    'tag_mapping': TagMappingRepository,
    'team': TeamRepository,
    'team_invitation': TeamInvitationRepository,
    'team_member': TeamMemberRepository,
    'user': UserRepository,
    'user_oauth_account': UserOAuthAccountRepository,
    'user_role': UserRoleRepository,
}

if OrganizationTableRepository is not None:
    ALL_REPOSITORIES['organization'] = OrganizationTableRepository

if TenantTableRepository is not None:
    ALL_REPOSITORIES['tenant'] = TenantTableRepository


MODEL_TO_REPOSITORY = {
    core_models.AuditLog: AuditLogRepository,
    core_models.CasbinRule: CasbinRuleRepository,
    core_models.EmailVerificationToken: EmailVerificationTokenRepository,
    core_models.PasswordResetToken: PasswordResetTokenRepository,
    core_models.RefreshToken: RefreshTokenRepository,
    core_models.Role: RoleRepository,
    core_models.Tag: TagRepository,
    core_models.TagMapping: TagMappingRepository,
    core_models.Team: TeamRepository,
    core_models.TeamInvitation: TeamInvitationRepository,
    core_models.TeamMember: TeamMemberRepository,
    core_models.User: UserRepository,
    core_models.UserOAuthAccount: UserOAuthAccountRepository,
    core_models.UserRole: UserRoleRepository,
}


class RepoFactory:
    """Factory for core repository classes and instances."""

    @staticmethod
    def user_repo() -> type[UserRepository]:
        return UserRepository

    @staticmethod
    def get_user_repo(session: SessionLike) -> UserRepository:
        return UserRepository(session=session)

    @staticmethod
    def get_repo(
        repository_type: type[BaseAsyncRepository],
        session: SessionLike,
    ) -> BaseAsyncRepository:
        return repository_type(session=session)

    @staticmethod
    def get_repo_by_name(name: str, session: SessionLike) -> BaseAsyncRepository:
        repository_type = ALL_REPOSITORIES.get(name)
        if repository_type is None:
            raise KeyError(f'No repository found for name: {name}')
        return repository_type(session=session)

    @staticmethod
    def get_repo_by_model(model_type: type, session: SessionLike) -> BaseAsyncRepository:
        repository_type = MODEL_TO_REPOSITORY.get(model_type)
        if repository_type is None:
            raise KeyError(f'No repository found for model: {model_type}')
        return repository_type(session=session)


__all__ = [
    'SessionLike',
    'RepoFactory',
    'ALL_REPOSITORIES',
    'MODEL_TO_REPOSITORY',
    'AuditLogRepository',
    'CasbinRuleRepository',
    'EmailVerificationTokenRepository',
    'PasswordResetTokenRepository',
    'RefreshTokenRepository',
    'RoleRepository',
    'TagRepository',
    'TagMappingRepository',
    'TeamRepository',
    'TeamInvitationRepository',
    'TeamMemberRepository',
    'UserRepository',
    'UserOAuthAccountRepository',
    'UserRoleRepository',
]

if OrganizationTableRepository is not None:
    __all__.append('OrganizationTableRepository')

if TenantTableRepository is not None:
    __all__.append('TenantTableRepository')

