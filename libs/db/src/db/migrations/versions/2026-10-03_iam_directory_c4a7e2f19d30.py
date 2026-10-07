"""iam directory: uuid tenants, organization tree, memberships, join links

Implements taas-specs/platform/tenancy.md (Iam-0100..0170, Iam-0400) on the
shared tables. Node (@taas/iam-db) mirrors these tables; this revision is their DDL owner.

Dev data reset: tenant ids change from integer to UUID, so tenants, users and the IAM tables that
reference them are emptied first.

Revision ID: c4a7e2f19d30
Revises: bdb25317e822
Create Date: 2026-10-03 10:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from advanced_alchemy.types import GUID, DateTimeUTC
from alembic import op
from sqlalchemy.dialects import postgresql

__all__ = ['downgrade', 'upgrade']

revision = 'c4a7e2f19d30'
down_revision = 'bdb25317e822'
branch_labels = None
depends_on = None

TENANT_ID_TABLES = ('taas_tags', 'taas_projects')


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE tenantstatus ADD VALUE IF NOT EXISTS 'ONBOARDING'")

    # --- reset IAM dev data (ids change type) ---------------------------------------------
    op.execute('DELETE FROM taas_casbin_rule')
    op.execute('DELETE FROM taas_team')
    op.execute('DELETE FROM taas_organizations')
    op.execute('DELETE FROM taas_user_account')
    op.execute('DELETE FROM taas_tenants')

    # --- tenants ---------------------------------------------------------------------------
    op.execute('ALTER TABLE taas_tenants ALTER COLUMN id DROP DEFAULT')
    op.execute('ALTER TABLE taas_tenants ALTER COLUMN id TYPE uuid USING gen_random_uuid()')
    op.add_column('taas_tenants', sa.Column('tenant_code', sa.TEXT(), nullable=False))
    op.add_column(
        'taas_tenants',
        sa.Column('account_type', sa.String(length=20), nullable=False, server_default='organization'),
    )
    op.alter_column('taas_tenants', 'account_type', server_default=None)
    op.add_column(
        'taas_tenants', sa.Column('is_root', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )
    op.add_column(
        'taas_tenants',
        sa.Column(
            'sys_settings',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column('taas_tenants', sa.Column('country_code', sa.String(length=2), nullable=True))
    op.add_column('taas_tenants', sa.Column('onboarded_at', DateTimeUTC(timezone=True), nullable=True))
    op.alter_column('taas_tenants', 'root_account_id', existing_type=GUID(length=16), nullable=True)
    op.create_index('ux_taas_tenants_slug', 'taas_tenants', ['slug'], unique=True)
    op.create_index('ux_taas_tenants_tenant_code', 'taas_tenants', ['tenant_code'], unique=True)
    op.create_index(
        'ux_taas_tenants_is_root', 'taas_tenants', ['is_root'], unique=True, postgresql_where=sa.text('is_root')
    )
    op.create_check_constraint(
        'ck_taas_tenants_account_type', 'taas_tenants', "account_type in ('organization', 'personal')"
    )

    # --- users -----------------------------------------------------------------------------
    op.execute('ALTER TABLE taas_user_account ALTER COLUMN tenant_id TYPE uuid USING NULL')
    op.create_foreign_key(
        'fk_taas_user_account_tenant_id_taas_tenants',
        'taas_user_account',
        'taas_tenants',
        ['tenant_id'],
        ['id'],
        ondelete='set null',
    )
    op.alter_column(
        'taas_user_account', 'username', existing_type=sa.String(length=30), type_=sa.String(length=255)
    )
    op.add_column('taas_user_account', sa.Column('directory_id', sa.String(length=64), nullable=True))
    op.create_index('ux_taas_user_account_email_lower', 'taas_user_account', [sa.text('lower(email)')], unique=True)
    op.create_index(
        'ux_taas_user_account_directory_id',
        'taas_user_account',
        ['directory_id'],
        unique=True,
        postgresql_where=sa.text('directory_id IS NOT NULL'),
    )

    # --- organizations (tenant tree) -------------------------------------------------------
    op.add_column('taas_organizations', sa.Column('tenant_id', GUID(length=16), nullable=False))
    op.add_column('taas_organizations', sa.Column('parent_id', GUID(length=16), nullable=True))
    op.add_column('taas_organizations', sa.Column('path', sa.TEXT(), nullable=False))
    op.add_column(
        'taas_organizations', sa.Column('depth', sa.SmallInteger(), nullable=False, server_default=sa.text('0'))
    )
    op.add_column('taas_organizations', sa.Column('directory_id', sa.String(length=36), nullable=True))
    op.create_foreign_key(
        'fk_taas_organizations_tenant_id_taas_tenants',
        'taas_organizations',
        'taas_tenants',
        ['tenant_id'],
        ['id'],
        ondelete='cascade',
    )
    op.create_foreign_key(
        'fk_taas_organizations_parent_id',
        'taas_organizations',
        'taas_organizations',
        ['parent_id'],
        ['id'],
        ondelete='cascade',
    )
    op.create_index('ix_taas_organizations_tenant_id', 'taas_organizations', ['tenant_id'])
    op.create_index(
        'ux_taas_organizations_root',
        'taas_organizations',
        ['tenant_id'],
        unique=True,
        postgresql_where=sa.text('parent_id IS NULL'),
    )
    op.create_index(
        'ix_taas_organizations_path', 'taas_organizations', ['path'], postgresql_ops={'path': 'text_pattern_ops'}
    )
    op.create_check_constraint('ck_taas_organizations_depth', 'taas_organizations', 'depth BETWEEN 0 AND 5')
    op.create_check_constraint(
        'ck_taas_organizations_root_depth', 'taas_organizations', '(parent_id IS NULL) = (depth = 0)'
    )

    # --- organization members --------------------------------------------------------------
    op.add_column('taas_organization_members', sa.Column('tenant_id', GUID(length=16), nullable=False))
    op.add_column(
        'taas_organization_members',
        sa.Column('joined_via', sa.String(length=20), nullable=False, server_default='registration'),
    )
    op.alter_column('taas_organization_members', 'joined_via', server_default=None)
    op.add_column('taas_organization_members', sa.Column('invitation_id', GUID(length=16), nullable=True))
    op.create_foreign_key(
        'fk_taas_organization_members_tenant_id_taas_tenants',
        'taas_organization_members',
        'taas_tenants',
        ['tenant_id'],
        ['id'],
        ondelete='cascade',
    )
    op.create_index(
        'ix_taas_organization_members_tenant_user', 'taas_organization_members', ['tenant_id', 'user_id']
    )
    op.create_check_constraint(
        'ck_taas_organization_members_role',
        'taas_organization_members',
        "role in ('tenant_admin', 'org_admin', 'org_member')",
    )
    op.create_check_constraint(
        'ck_taas_organization_members_joined_via',
        'taas_organization_members',
        "joined_via in ('registration', 'admin', 'join_link', 'sso')",
    )

    # --- organization invitations (join links) ---------------------------------------------
    op.create_table(
        'taas_organization_invitations',
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('tenant_id', GUID(length=16), nullable=False),
        sa.Column('organization_id', GUID(length=16), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('used_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('expires_at', DateTimeUTC(timezone=True), nullable=False),
        sa.Column('revoked_at', DateTimeUTC(timezone=True), nullable=True),
        sa.Column('created_by', GUID(length=16), nullable=True),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        sa.Column('created_at', DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', DateTimeUTC(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name='fk_taas_org_invitations_tenant_id',
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['taas_organizations.id'],
            name='fk_taas_org_invitations_organization_id',
            ondelete='cascade',
        ),
        sa.ForeignKeyConstraint(
            ['created_by'],
            ['taas_user_account.id'],
            name='fk_taas_org_invitations_created_by',
            ondelete='set null',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_taas_organization_invitations'),
        sa.CheckConstraint("role in ('org_admin', 'org_member')", name='ck_taas_organization_invitations_role'),
        sa.CheckConstraint(
            'max_uses >= 1 AND used_count >= 0 AND used_count <= max_uses',
            name='ck_taas_organization_invitations_uses',
        ),
    )
    op.create_index(
        'ux_taas_organization_invitations_token_hash', 'taas_organization_invitations', ['token_hash'], unique=True
    )
    op.create_index('ix_taas_organization_invitations_org', 'taas_organization_invitations', ['organization_id'])

    # --- teams: groups inside an organization ----------------------------------------------
    op.add_column('taas_team', sa.Column('tenant_id', GUID(length=16), nullable=False))
    op.add_column('taas_team', sa.Column('organization_id', GUID(length=16), nullable=False))
    op.create_foreign_key(
        'fk_taas_team_tenant_id_taas_tenants', 'taas_team', 'taas_tenants', ['tenant_id'], ['id'], ondelete='cascade'
    )
    op.create_foreign_key(
        'fk_taas_team_organization_id',
        'taas_team',
        'taas_organizations',
        ['organization_id'],
        ['id'],
        ondelete='cascade',
    )
    op.create_index('ix_taas_team_tenant_id', 'taas_team', ['tenant_id'])
    op.create_index('ix_taas_team_organization_id', 'taas_team', ['organization_id'])

    # --- other tenant-scoped tables ----------------------------------------------------------
    for table in TENANT_ID_TABLES:
        op.execute(f'ALTER TABLE {table} ALTER COLUMN tenant_id TYPE uuid USING NULL')

    # --- casbin: look-ups by role grant ------------------------------------------------------
    op.create_index('ix_taas_casbin_rule_ptype_v0', 'taas_casbin_rule', ['ptype', 'v0'])


def downgrade() -> None:
    op.drop_index('ix_taas_casbin_rule_ptype_v0', table_name='taas_casbin_rule')
    for table in TENANT_ID_TABLES:
        op.execute(f'ALTER TABLE {table} ALTER COLUMN tenant_id TYPE integer USING NULL')

    op.drop_index('ix_taas_team_organization_id', table_name='taas_team')
    op.drop_index('ix_taas_team_tenant_id', table_name='taas_team')
    op.drop_constraint('fk_taas_team_organization_id', 'taas_team', type_='foreignkey')
    op.drop_constraint('fk_taas_team_tenant_id_taas_tenants', 'taas_team', type_='foreignkey')
    op.drop_column('taas_team', 'organization_id')
    op.drop_column('taas_team', 'tenant_id')

    op.drop_table('taas_organization_invitations')

    op.drop_constraint('ck_taas_organization_members_joined_via', 'taas_organization_members', type_='check')
    op.drop_constraint('ck_taas_organization_members_role', 'taas_organization_members', type_='check')
    op.drop_index('ix_taas_organization_members_tenant_user', table_name='taas_organization_members')
    op.drop_constraint(
        'fk_taas_organization_members_tenant_id', 'taas_organization_members', type_='foreignkey'
    )
    op.drop_column('taas_organization_members', 'invitation_id')
    op.drop_column('taas_organization_members', 'joined_via')
    op.drop_column('taas_organization_members', 'tenant_id')

    op.drop_constraint('ck_taas_organizations_root_depth', 'taas_organizations', type_='check')
    op.drop_constraint('ck_taas_organizations_depth', 'taas_organizations', type_='check')
    op.drop_index('ix_taas_organizations_path', table_name='taas_organizations')
    op.drop_index('ux_taas_organizations_root', table_name='taas_organizations')
    op.drop_index('ix_taas_organizations_tenant_id', table_name='taas_organizations')
    op.drop_constraint('fk_taas_organizations_parent_id', 'taas_organizations', type_='foreignkey')
    op.drop_constraint('fk_taas_organizations_tenant_id_taas_tenants', 'taas_organizations', type_='foreignkey')
    for column in ('directory_id', 'depth', 'path', 'parent_id', 'tenant_id'):
        op.drop_column('taas_organizations', column)

    op.drop_index('ux_taas_user_account_directory_id', table_name='taas_user_account')
    op.drop_index('ux_taas_user_account_email_lower', table_name='taas_user_account')
    op.drop_column('taas_user_account', 'directory_id')
    op.drop_constraint('fk_taas_user_account_tenant_id_taas_tenants', 'taas_user_account', type_='foreignkey')
    op.execute('DELETE FROM taas_user_account')
    op.execute('ALTER TABLE taas_user_account ALTER COLUMN tenant_id TYPE integer USING NULL')
    op.alter_column(
        'taas_user_account', 'username', existing_type=sa.String(length=255), type_=sa.String(length=30)
    )

    op.drop_constraint('ck_taas_tenants_account_type', 'taas_tenants', type_='check')
    op.drop_index('ux_taas_tenants_is_root', table_name='taas_tenants')
    op.drop_index('ux_taas_tenants_tenant_code', table_name='taas_tenants')
    op.drop_index('ux_taas_tenants_slug', table_name='taas_tenants')
    op.execute('DELETE FROM taas_tenants')
    for column in ('onboarded_at', 'country_code', 'sys_settings', 'is_root', 'account_type', 'tenant_code'):
        op.drop_column('taas_tenants', column)
    op.execute('ALTER TABLE taas_tenants ALTER COLUMN id TYPE integer USING 0')
    op.alter_column('taas_tenants', 'root_account_id', existing_type=GUID(length=16), nullable=False)
    # tenantstatus keeps the ONBOARDING value: Postgres cannot drop an enum value.
