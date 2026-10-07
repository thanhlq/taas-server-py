"""ppm + crm tenant scope: organization_id (+ tenant_id on CRM accounts), backfill, fixed text defaults

- ``taas_projects.organization_id`` and ``taas_crm_accounts.tenant_id`` / ``organization_id``: every PPM / CRM
  request is scoped to the caller's tenant and organization (taas-specs/ppm/ppm-app-spec.md Ppm-0001,
  taas-specs/crm/crm-app-spec.md). Rows without a tenant (created before the scoping) move to the development
  organization (slug ``demo``, else the oldest root organization) — the organization of the development sign-in.
- Text defaults written as ``'md'::character`` were ``character(1)`` casts: the database default was ``'m'``.
  Defaults are fixed and the truncated values written by them repaired.

Revision ID: 9b3e61d4a7c2
Revises: f52cd8075cbe
Create Date: 2026-10-07 21:00:00.000000

"""

import warnings

import sqlalchemy as sa
from advanced_alchemy.types import GUID
from alembic import op

# revision identifiers, used by Alembic.
revision = '9b3e61d4a7c2'
down_revision = 'f52cd8075cbe'
branch_labels = None
depends_on = None

# (table, column, default) of every text default that was cast to character(1).
_TEXT_DEFAULTS = [
    ('taas_categories', 'content_type', 'md'),
    ('taas_checklist_templates', 'scope', 'task'),
    ('taas_payrolls', 'pay_status', 'NA'),
    ('taas_projects', 'content_type', 'md'),
    ('taas_projects', 'status', 'New'),
    ('taas_projects_comments', 'content_type', 'md'),
    ('taas_projects_comments', 'object_type', 'project'),
    ('taas_projects_comments', 'privacy', 'object'),
    ('taas_projects_risks', 'risk_status', 'new'),
    ('taas_projects_updates', 'content_type', 'md'),
    ('taas_projects_workflows', 'content_type', 'md'),
    ('taas_projects_workflows', 'privacy', 'project'),
    ('taas_projects_workflows', 'scope', 'project'),
    ('taas_projects_workflows', 'workflow_type', 'kanban'),
    ('taas_projects_workflows_stages', 'sort_by', 'manual'),
    ('taas_projects_workflows_stages', 'sort_order', 'asc'),
    ('taas_tasks', 'content_type', 'md'),
]

_DEV_ORGANIZATION = """
    (select id, tenant_id from taas_organizations
      where deleted_at is null
      order by (slug = 'demo') desc, (depth = 0) desc, created_at
      limit 1)
"""


def _columns(table: str) -> set[str]:
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        schema_upgrades()
        data_upgrades()


def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        data_downgrades()
        schema_downgrades()


def schema_upgrades() -> None:
    op.add_column('taas_projects', sa.Column('organization_id', GUID(length=16), nullable=True))
    op.create_index('ix_taas_projects_organization_id', 'taas_projects', ['organization_id'])
    op.create_index('ix_taas_projects_tenant_organization', 'taas_projects', ['tenant_id', 'organization_id'])

    op.add_column('taas_crm_accounts', sa.Column('tenant_id', GUID(length=16), nullable=True))
    op.add_column('taas_crm_accounts', sa.Column('organization_id', GUID(length=16), nullable=True))
    op.create_index('ix_taas_crm_accounts_tenant_id', 'taas_crm_accounts', ['tenant_id'])
    op.create_index('ix_taas_crm_accounts_organization_id', 'taas_crm_accounts', ['organization_id'])
    op.create_index(
        'ix_taas_crm_accounts_tenant_organization', 'taas_crm_accounts', ['tenant_id', 'organization_id']
    )

    for table, column, default in _TEXT_DEFAULTS:
        if column in _columns(table):
            op.alter_column(table, column, server_default=sa.text(f"'{default}'"))


def schema_downgrades() -> None:
    op.drop_index('ix_taas_crm_accounts_tenant_organization', table_name='taas_crm_accounts')
    op.drop_index('ix_taas_crm_accounts_organization_id', table_name='taas_crm_accounts')
    op.drop_index('ix_taas_crm_accounts_tenant_id', table_name='taas_crm_accounts')
    op.drop_column('taas_crm_accounts', 'organization_id')
    op.drop_column('taas_crm_accounts', 'tenant_id')
    op.drop_index('ix_taas_projects_tenant_organization', table_name='taas_projects')
    op.drop_index('ix_taas_projects_organization_id', table_name='taas_projects')
    op.drop_column('taas_projects', 'organization_id')
    # The character(1) defaults are not restored: they were a bug.


def data_upgrades() -> None:
    # Values truncated by the old defaults ('m' for 'md', 'N' for 'New', …).
    for table, column, default in _TEXT_DEFAULTS:
        if len(default) > 1 and column in _columns(table):
            op.execute(
                sa.text(f'update {table} set {column} = :full where {column} = :cut').bindparams(
                    full=default, cut=default[0]
                )
            )

    # Rows created before tenant scoping → the development organization.
    for table in ('taas_projects', 'taas_crm_accounts'):
        op.execute(
            f"""
            update {table} t
               set tenant_id = o.tenant_id, organization_id = o.id
              from {_DEV_ORGANIZATION} o
             where t.tenant_id is null
            """
        )
    op.execute(
        f"""
        update taas_projects t
           set organization_id = o.id
          from {_DEV_ORGANIZATION} o
         where t.organization_id is null and t.tenant_id = o.tenant_id
        """
    )


def data_downgrades() -> None:
    """Scoping and repaired values are kept on downgrade (the columns are dropped)."""
