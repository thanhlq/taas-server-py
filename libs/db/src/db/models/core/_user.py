from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from advanced_alchemy.base import UUIDv7AuditBase
from platform_core.config import Settings, get_settings
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import ID_COLUMN_TYPE
from db.models.core.constants import USER_ACCOUNT_TABLE

if TYPE_CHECKING:
    # from app.db.models._email_verification_token import EmailVerificationToken
    # from app.db.models._oauth_account import UserOAuthAccount
    # from app.db.models._password_reset_token import PasswordResetToken
    # from app.db.models._refresh_token import RefreshToken
    # from app.db.models._team_member import TeamMember
    # from app.db.models._user_role import UserRole
    pass


settings: Settings = get_settings()


class User(UUIDv7AuditBase):
    __tablename__ = USER_ACCOUNT_TABLE
    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(nullable=True, default=None)
    username: Mapped[str | None] = mapped_column(
        String(length=30), unique=True, index=True, nullable=True, default=None
    )
    phone: Mapped[str | None] = mapped_column(
        String(length=20), nullable=True, default=None
    )
    hashed_password: Mapped[str | None] = mapped_column(
        String(length=255),
        nullable=True,
        default=None,
        deferred=True,
        deferred_group='security_sensitive',
    )
    avatar_url: Mapped[str | None] = mapped_column(
        String(length=500), nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    verified_at: Mapped[date] = mapped_column(nullable=True, default=None)
    joined_at: Mapped[date] = mapped_column(default=lambda: datetime.now(UTC).date())
    login_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str | None] = mapped_column(
        String(length=30), index=True, nullable=True, default=None
    )
    tenant_id: Mapped[ID_COLUMN_TYPE | None] = mapped_column(
        String(length=36), index=True, nullable=True, default=None
    )
    org_id: Mapped[ID_COLUMN_TYPE | None] = mapped_column(
        String(length=36), index=True, nullable=True, default=None
    )
