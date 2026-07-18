# filepath: /Users/tuanpham/learns/py_iam_keycloak/app/core/iam/db/models.py
from collections.abc import Set
from typing import List, Optional

from db.models.base import BaseDBModel, Uuid36DBGenerating
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

ID_LENGTH = 36
LENGTH_DEFAULT = 36

# Table name constants
TENANT_TABLE_NAME = 'realm'
USER_TABLE_NAME = 'user_entity'
USER_ATTRIBUTES_TABLE_NAME = 'user_attribute'
GROUP_TABLE_NAME = 'keycloak_group'
ROLE_TABLE_NAME = 'keycloak_role'
USER_GROUP_MAPPING_TABLE_NAME = 'user_group_membership'
GROUP_ROLE_MAPPING_TABLE_NAME = 'group_role_mapping'
USER_ROLE_MAPPING_TABLE_NAME = 'user_role_mapping'

# Define association tables for many-to-many relationships
role_group_mapping = Table(
    GROUP_ROLE_MAPPING_TABLE_NAME,
    BaseDBModel.metadata,
    Column('role_id', Text, ForeignKey(f'{ROLE_TABLE_NAME}.id'), primary_key=True),
    Column('group_id', Text, ForeignKey(f'{GROUP_TABLE_NAME}.id'), primary_key=True),
)

user_role_mapping = Table(
    USER_ROLE_MAPPING_TABLE_NAME,
    BaseDBModel.metadata,
    Column('role_id', Text, ForeignKey(f'{ROLE_TABLE_NAME}.id'), primary_key=True),
    Column('user_id', Text, ForeignKey(f'{USER_TABLE_NAME}.id'), primary_key=True),
)

user_group_mapping = Table(
    USER_GROUP_MAPPING_TABLE_NAME,
    BaseDBModel.metadata,
    Column('group_id', Text, ForeignKey(f'{GROUP_TABLE_NAME}.id'), primary_key=True),
    Column('user_id', Text, ForeignKey(f'{USER_TABLE_NAME}.id'), primary_key=True),
)


class RealmOrm(BaseDBModel, Uuid36DBGenerating):
    """Tenant model representing a Keycloak realm"""

    __tablename__ = TENANT_TABLE_NAME

    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=False, index=True)

    # Relationships
    users: Mapped[Set['UserOrm']] = relationship(
        back_populates='realm',
        collection_class=set,
    )


class RoleOrm(BaseDBModel, Uuid36DBGenerating):
    """Role model representing a Keycloak role"""

    __tablename__ = ROLE_TABLE_NAME

    client_realm_constraint: Mapped[Optional[str]] = mapped_column(
        String(LENGTH_DEFAULT), unique=True, index=True
    )
    client_role: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(
        String(LENGTH_DEFAULT), nullable=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(LENGTH_DEFAULT), nullable=True)
    client: Mapped[Optional[str]] = mapped_column(String(ID_LENGTH), nullable=True)
    realm: Mapped[Optional[str]] = mapped_column(String(ID_LENGTH), nullable=True)

    realm_id: Mapped[str] = mapped_column(
        String(LENGTH_DEFAULT),
        ForeignKey(f'{TENANT_TABLE_NAME}.id'),
        nullable=False,
        index=True,
    )

    # Relationships
    groups: Mapped[List['GroupOrm']] = relationship(
        secondary=role_group_mapping, back_populates='roles'
    )
    users: Mapped[List['UserOrm']] = relationship(
        secondary=user_role_mapping, back_populates='roles'
    )


class GroupOrm(BaseDBModel, Uuid36DBGenerating):
    """Group model representing a Keycloak group"""

    __tablename__ = GROUP_TABLE_NAME
    __idname__ = 'id'

    name: Mapped[str] = mapped_column(String(255), index=True)
    parent_group: Mapped[Optional[str]] = mapped_column(
        Text, ForeignKey(f'{GROUP_TABLE_NAME}.id', ondelete='CASCADE'), nullable=True
    )

    realm_id: Mapped[str] = mapped_column(
        String(LENGTH_DEFAULT),
        ForeignKey(f'{TENANT_TABLE_NAME}.id'),
        nullable=False,
        index=True,
    )

    # Relationships
    users: Mapped[List['UserOrm']] = relationship(
        secondary=user_group_mapping, back_populates='groups'
    )

    roles: Mapped[List['RoleOrm']] = relationship(
        secondary=role_group_mapping, back_populates='groups'
    )

    realm: Mapped[RealmOrm] = relationship(
        # back_populates="users",
        # foreign_keys=[DBTenantModel.realm_id]
    )


class UserAttributeOrm(BaseDBModel, Uuid36DBGenerating):
    __tablename__ = USER_ATTRIBUTES_TABLE_NAME

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f'{USER_TABLE_NAME}.id'), nullable=False
    )

    # Relationships
    user: Mapped['UserOrm'] = relationship(back_populates='attributes')


class UserOrm(BaseDBModel, Uuid36DBGenerating):
    __tablename__ = USER_TABLE_NAME
    __idname__ = 'id'

    email_constraint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    federation_link: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_timestamp: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    service_account_client_link: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=False
    )
    not_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    realm_id: Mapped[str] = mapped_column(
        String(ID_LENGTH),
        ForeignKey(f'{TENANT_TABLE_NAME}.id'),
        nullable=False,
        index=True,
    )

    attributes: Mapped[List['UserAttributeOrm']] = relationship(
        back_populates='user', cascade='all, delete-orphan'
    )

    # Relationships
    groups: Mapped[List[GroupOrm]] = relationship(
        secondary=user_group_mapping, back_populates='users'
    )
    roles: Mapped[List[RoleOrm]] = relationship(
        secondary=user_role_mapping, back_populates='users'
    )
    realm: Mapped[RealmOrm] = relationship(
        back_populates='users', foreign_keys=[realm_id]
    )

    @property
    def attributes_string(self) -> str:
        """Return concatenated attributes as string"""
        if not self.attributes:
            return ''
        return ';'.join([f'{attr.name}:{attr.value}' for attr in self.attributes])

    @property
    def full_name(self) -> str:
        """Return the user's full name"""
        return f'{self.first_name or ""} {self.last_name or ""}'.strip()
