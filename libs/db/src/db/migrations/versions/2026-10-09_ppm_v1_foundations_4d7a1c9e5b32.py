"""ppm: V1 foundations — capability levels, audit store, mentions, links, My Work, notifications, work model columns

- ``taas_projects``: ``kind`` (``project`` · ``template`` · ``personal``, ADR-29 / ADR-30), ``created_from_template_id``.
- ``taas_tasks``: ``tenant_id`` (backfilled from the project), ``progress_mode``, roll-up counters
  (``child_count`` · ``done_child_count`` · ``checklist_total`` · ``checklist_done``), roll-up dates, ``previous_stage_id``.
- ``taas_tasks_users`` (owner + collaborators, Ppm-0825), ``taas_task_checklist_items`` (assignee, due, mandatory —
  Ppm-0830), ``taas_projects_comments`` (``tenant_id``, ``edited_at`` — Ppm-0504).
- ``taas_file_drives``: kind ``project`` + ``source_id`` (a project's files, File-0101).
- New ``taas_ppm_settings`` (Ppm-0009), ``taas_ppm_audit_events`` (Ppm-0011, ADR-26), ``taas_ppm_mentions``,
  ``taas_ppm_attachments``, ``taas_ppm_my_work_plans``, ``taas_ppm_user_settings`` and the platform notification
  tables ``taas_notifications`` · ``taas_notification_deliveries`` · ``taas_notification_preferences`` ·
  ``taas_notification_user_settings`` (ADR-24).

Spec: taas-specs/ppm/ (ppm-app-spec.md §9, work-model, my-work, collaboration, automation Part A). Written by hand;
mirrors ``db.models.ppm``, ``db.models.notifications`` and the ``db.models.ews`` columns.

Revision ID: 4d7a1c9e5b32
Revises: 8c4f2d6b1a95
Create Date: 2026-10-09 12:00:00.000000

"""

import warnings

import sqlalchemy as sa
from advanced_alchemy.types import GUID, DateTimeUTC
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '4d7a1c9e5b32'
down_revision = '8c4f2d6b1a95'
branch_labels = None
depends_on = None

JSON = postgresql.JSONB(astext_type=sa.Text())
EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        schema_upgrades()
        data_upgrades()


def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        schema_downgrades()


def _tenant(table: str) -> list[sa.SchemaItem]:
    return [
        sa.Column('tenant_id', GUID(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ['tenant_id'],
            ['taas_tenants.id'],
            name=f'fk_{table}_tenant_id_taas_tenants',
            ondelete='cascade',
        ),
    ]


def _audit() -> list[sa.Column]:
    return [
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('created_at', DateTimeUTC(timezone=True), nullable=False),
        sa.Column('updated_at', DateTimeUTC(timezone=True), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
    ]


def _drive_kinds(kinds: str) -> None:
    # The naming convention doubled the prefix when the files revision created it.
    op.execute(
        'ALTER TABLE taas_file_drives DROP CONSTRAINT IF EXISTS ck_taas_file_drives_ck_taas_file_drives_kind'
    )
    op.execute(
        'ALTER TABLE taas_file_drives ADD CONSTRAINT ck_taas_file_drives_ck_taas_file_drives_kind '
        f'CHECK (kind in ({kinds}))'
    )


def schema_upgrades() -> None:
    # --- existing PPM tables -------------------------------------------------------------------------
    op.add_column(
        'taas_projects',
        sa.Column(
            'kind', sa.Text(), nullable=False, server_default=sa.text("'project'")
        ),
    )
    op.create_index('ix_taas_projects_kind', 'taas_projects', ['kind'])
    op.add_column(
        'taas_projects',
        sa.Column('created_from_template_id', GUID(length=16), nullable=True),
    )

    op.add_column('taas_tasks', sa.Column('tenant_id', GUID(length=16), nullable=True))
    op.create_index('ix_taas_tasks_tenant_id', 'taas_tasks', ['tenant_id'])
    op.add_column('taas_tasks', sa.Column('progress_mode', sa.Text(), nullable=True))
    for column in (
        'child_count',
        'done_child_count',
        'checklist_total',
        'checklist_done',
    ):
        op.add_column(
            'taas_tasks',
            sa.Column(column, sa.Integer(), nullable=False, server_default='0'),
        )
    op.add_column(
        'taas_tasks',
        sa.Column('rollup_start_date', postgresql.TIMESTAMP(), nullable=True),
    )
    op.add_column(
        'taas_tasks',
        sa.Column('rollup_due_date', postgresql.TIMESTAMP(), nullable=True),
    )
    op.add_column(
        'taas_tasks', sa.Column('previous_stage_id', GUID(length=16), nullable=True)
    )
    op.create_index(
        'ix_taas_tasks_open_owner',
        'taas_tasks',
        ['user_id'],
        postgresql_where=sa.text('deleted_at IS NULL AND completed_at IS NULL'),
    )

    op.add_column(
        'taas_tasks_users', sa.Column('tenant_id', GUID(length=16), nullable=True)
    )
    op.add_column(
        'taas_tasks_users',
        sa.Column(
            'role', sa.Text(), nullable=False, server_default=sa.text("'collaborator'")
        ),
    )
    op.add_column(
        'taas_tasks_users',
        sa.Column(
            'created_at',
            DateTimeUTC(timezone=True),
            nullable=True,
            server_default=sa.text('now()'),
        ),
    )
    op.add_column('taas_tasks_users', sa.Column('created_by', sa.Text(), nullable=True))
    op.create_index(
        'ix_taas_tasks_users_user', 'taas_tasks_users', ['user_id', 'task_id']
    )
    op.create_index(
        'ux_taas_tasks_users_live',
        'taas_tasks_users',
        ['task_id', 'user_id'],
        unique=True,
        postgresql_where=sa.text('deleted_at IS NULL'),
    )

    op.add_column(
        'taas_task_checklist_items',
        sa.Column('tenant_id', GUID(length=16), nullable=True),
    )
    op.add_column(
        'taas_task_checklist_items',
        sa.Column('assignee_user_id', sa.Text(), nullable=True),
    )
    op.add_column(
        'taas_task_checklist_items',
        sa.Column('due_date', postgresql.TIMESTAMP(), nullable=True),
    )
    op.add_column(
        'taas_task_checklist_items',
        sa.Column(
            'is_mandatory',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    op.create_index(
        'ix_taas_task_checklist_items_task',
        'taas_task_checklist_items',
        ['task_id', 'display_order'],
    )
    op.create_index(
        'ix_taas_task_checklist_items_assignee',
        'taas_task_checklist_items',
        ['assignee_user_id'],
        postgresql_where=sa.text('is_completed = false'),
    )

    op.add_column(
        'taas_projects_comments', sa.Column('tenant_id', GUID(length=16), nullable=True)
    )
    op.add_column(
        'taas_projects_comments',
        sa.Column('edited_at', DateTimeUTC(timezone=True), nullable=True),
    )

    # --- File Manager: project source drives (File-0101) --------------------------------------------
    _drive_kinds("'organization', 'shared', 'personal', 'project'")
    op.add_column(
        'taas_file_drives', sa.Column('source_id', GUID(length=16), nullable=True)
    )
    op.create_index(
        'ux_taas_file_drives_source',
        'taas_file_drives',
        ['source_id'],
        unique=True,
        postgresql_where=sa.text("kind = 'project' AND deleted_at IS NULL"),
    )

    # --- new PPM tables ------------------------------------------------------------------------------
    op.create_table(
        'taas_ppm_settings',
        *_audit(),
        *_tenant('taas_ppm_settings'),
        sa.Column('organization_id', GUID(length=16), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('capabilities', JSON, nullable=False, server_default=EMPTY),
        sa.Column('settings', JSON, nullable=False, server_default=EMPTY),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('updated_by', sa.String(320), nullable=True),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['taas_organizations.id'],
            name='fk_taas_ppm_settings_organization_id_taas_organizations',
            ondelete='cascade',
        ),
        sa.CheckConstraint('level between 1 and 4', name='level'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_ppm_settings'),
    )
    op.create_index(
        'ix_taas_ppm_settings_tenant_id', 'taas_ppm_settings', ['tenant_id']
    )
    op.create_index(
        'ux_taas_ppm_settings_organization',
        'taas_ppm_settings',
        ['organization_id'],
        unique=True,
    )

    op.create_table(
        'taas_ppm_audit_events',
        sa.Column('id', GUID(length=16), nullable=False),
        sa.Column('sa_orm_sentinel', sa.Integer(), nullable=True),
        *_tenant('taas_ppm_audit_events'),
        sa.Column('organization_id', GUID(length=16), nullable=True),
        sa.Column('project_id', GUID(length=16), nullable=True),
        sa.Column('event', sa.String(80), nullable=False),
        sa.Column('subject_type', sa.String(32), nullable=False),
        sa.Column('subject_id', sa.String(64), nullable=False),
        sa.Column(
            'actor_type',
            sa.String(16),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
        sa.Column('actor_ref', sa.String(320), nullable=True),
        sa.Column('actor_name', sa.String(200), nullable=True),
        sa.Column(
            'cause', sa.String(16), nullable=False, server_default=sa.text("'ui'")
        ),
        sa.Column('changes', JSON, nullable=True),
        sa.Column('data', JSON, nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('event_id', sa.String(64), nullable=False),
        sa.Column(
            'occurred_at',
            DateTimeUTC(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_taas_ppm_audit_events'),
    )
    op.create_index(
        'ix_taas_ppm_audit_events_tenant_id', 'taas_ppm_audit_events', ['tenant_id']
    )
    op.create_index(
        'ix_taas_ppm_audit_events_project',
        'taas_ppm_audit_events',
        ['project_id', sa.text('occurred_at DESC')],
    )
    op.create_index(
        'ix_taas_ppm_audit_events_subject',
        'taas_ppm_audit_events',
        ['subject_type', 'subject_id', sa.text('occurred_at DESC')],
    )

    op.create_table(
        'taas_ppm_mentions',
        *_audit(),
        *_tenant('taas_ppm_mentions'),
        sa.Column('project_id', GUID(length=16), nullable=True),
        sa.Column('subject_type', sa.String(32), nullable=False),
        sa.Column('subject_id', sa.String(64), nullable=False),
        sa.Column('comment_id', GUID(length=16), nullable=True),
        sa.Column('user_ref', sa.String(320), nullable=False),
        sa.Column('created_by', sa.String(320), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_taas_ppm_mentions'),
    )
    op.create_index(
        'ix_taas_ppm_mentions_tenant_id', 'taas_ppm_mentions', ['tenant_id']
    )
    op.create_index('ix_taas_ppm_mentions_user', 'taas_ppm_mentions', ['user_ref'])
    op.create_index(
        'ix_taas_ppm_mentions_subject',
        'taas_ppm_mentions',
        ['subject_type', 'subject_id'],
    )

    op.create_table(
        'taas_ppm_attachments',
        *_audit(),
        *_tenant('taas_ppm_attachments'),
        sa.Column('project_id', GUID(length=16), nullable=False),
        sa.Column('task_id', GUID(length=16), nullable=True),
        sa.Column(
            'kind', sa.String(8), nullable=False, server_default=sa.text("'link'")
        ),
        sa.Column('file_id', GUID(length=16), nullable=True),
        sa.Column('url', sa.String(2048), nullable=True),
        sa.Column('title', sa.String(300), nullable=False),
        sa.Column('mime', sa.String(128), nullable=True),
        sa.Column('size', sa.BigInteger(), nullable=True),
        sa.Column('position', sa.Float(), nullable=False, server_default='0'),
        sa.Column('added_by', sa.String(320), nullable=True),
        sa.Column('deleted_at', DateTimeUTC(timezone=True), nullable=True),
        sa.CheckConstraint("kind in ('link', 'file')", name='kind'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_ppm_attachments'),
    )
    op.create_index(
        'ix_taas_ppm_attachments_tenant_id', 'taas_ppm_attachments', ['tenant_id']
    )
    op.create_index(
        'ix_taas_ppm_attachments_project',
        'taas_ppm_attachments',
        ['project_id', 'task_id'],
    )

    op.create_table(
        'taas_ppm_my_work_plans',
        *_audit(),
        *_tenant('taas_ppm_my_work_plans'),
        sa.Column('user_id', GUID(length=16), nullable=False),
        sa.Column('source_type', sa.String(16), nullable=False),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('planned_date', sa.Date(), nullable=True),
        sa.Column('sort_key', sa.Float(), nullable=True),
        sa.Column('snoozed_until', DateTimeUTC(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_taas_ppm_my_work_plans'),
    )
    op.create_index(
        'ix_taas_ppm_my_work_plans_tenant_id', 'taas_ppm_my_work_plans', ['tenant_id']
    )
    op.create_index(
        'ux_taas_ppm_my_work_plans_source',
        'taas_ppm_my_work_plans',
        ['user_id', 'source_type', 'source_id'],
        unique=True,
    )

    op.create_table(
        'taas_ppm_user_settings',
        *_audit(),
        *_tenant('taas_ppm_user_settings'),
        sa.Column('user_id', GUID(length=16), nullable=False),
        sa.Column('settings', JSON, nullable=False, server_default=EMPTY),
        sa.PrimaryKeyConstraint('id', name='pk_taas_ppm_user_settings'),
    )
    op.create_index(
        'ix_taas_ppm_user_settings_tenant_id', 'taas_ppm_user_settings', ['tenant_id']
    )
    op.create_index(
        'ux_taas_ppm_user_settings_user',
        'taas_ppm_user_settings',
        ['user_id'],
        unique=True,
    )

    # --- platform notifications (ADR-24) ------------------------------------------------------------
    op.create_table(
        'taas_notifications',
        *_audit(),
        *_tenant('taas_notifications'),
        sa.Column('organization_id', GUID(length=16), nullable=True),
        sa.Column('recipient_user_id', GUID(length=16), nullable=True),
        sa.Column('recipient_email', sa.String(320), nullable=True),
        sa.Column('app', sa.String(32), nullable=False),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('subject_type', sa.String(32), nullable=True),
        sa.Column('subject_id', sa.String(64), nullable=True),
        sa.Column('project_id', GUID(length=16), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('link', sa.String(1000), nullable=True),
        sa.Column('actor_ref', sa.String(320), nullable=True),
        sa.Column('actor_name', sa.String(200), nullable=True),
        sa.Column(
            'via', sa.String(16), nullable=False, server_default=sa.text("'user'")
        ),
        sa.Column('group_key', sa.String(400), nullable=True),
        sa.Column('count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('dedup_key', sa.String(400), nullable=False),
        sa.Column('data', JSON, nullable=True),
        sa.Column('read_at', DateTimeUTC(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_taas_notifications'),
    )
    op.create_index(
        'ix_taas_notifications_tenant_id', 'taas_notifications', ['tenant_id']
    )
    op.create_index(
        'ux_taas_notifications_dedup', 'taas_notifications', ['dedup_key'], unique=True
    )
    op.create_index(
        'ix_taas_notifications_recipient',
        'taas_notifications',
        ['recipient_user_id', 'read_at', sa.text('created_at DESC')],
    )
    op.create_index(
        'ix_taas_notifications_recipient_email',
        'taas_notifications',
        ['recipient_email', 'read_at', sa.text('created_at DESC')],
    )
    op.create_index(
        'ix_taas_notifications_group',
        'taas_notifications',
        ['group_key', sa.text('created_at DESC')],
    )

    op.create_table(
        'taas_notification_deliveries',
        *_audit(),
        *_tenant('taas_notification_deliveries'),
        sa.Column('notification_id', GUID(length=16), nullable=False),
        sa.Column('channel', sa.String(16), nullable=False),
        sa.Column('recipient_email', sa.String(320), nullable=True),
        sa.Column(
            'status', sa.String(16), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column(
            'scheduled_for',
            DateTimeUTC(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('sent_at', DateTimeUTC(timezone=True), nullable=True),
        sa.Column('error', sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(
            ['notification_id'],
            ['taas_notifications.id'],
            name='fk_taas_notification_deliveries_notification',
            ondelete='cascade',
        ),
        sa.CheckConstraint(
            "status in ('pending', 'deferred', 'sent', 'failed', 'bounced', 'suppressed')",
            name='status',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_taas_notification_deliveries'),
    )
    op.create_index(
        'ix_taas_notification_deliveries_tenant_id',
        'taas_notification_deliveries',
        ['tenant_id'],
    )
    op.create_index(
        'ix_taas_notification_deliveries_notification_id',
        'taas_notification_deliveries',
        ['notification_id'],
    )
    op.create_index(
        'ix_taas_notification_deliveries_due',
        'taas_notification_deliveries',
        ['scheduled_for'],
        postgresql_where=sa.text("status in ('pending', 'deferred')"),
    )

    op.create_table(
        'taas_notification_preferences',
        *_audit(),
        *_tenant('taas_notification_preferences'),
        sa.Column('user_id', GUID(length=16), nullable=False),
        sa.Column('app', sa.String(32), nullable=False),
        sa.Column('kind', sa.String(64), nullable=False),
        sa.Column('channel', sa.String(16), nullable=False),
        sa.Column('mode', sa.String(8), nullable=False),
        sa.CheckConstraint("mode in ('instant', 'digest', 'off')", name='mode'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_notification_preferences'),
    )
    op.create_index(
        'ix_taas_notification_preferences_tenant_id',
        'taas_notification_preferences',
        ['tenant_id'],
    )
    op.create_index(
        'ux_taas_notification_preferences_user',
        'taas_notification_preferences',
        ['user_id', 'app', 'kind', 'channel'],
        unique=True,
    )

    op.create_table(
        'taas_notification_user_settings',
        *_audit(),
        *_tenant('taas_notification_user_settings'),
        sa.Column('user_id', GUID(length=16), nullable=False),
        sa.Column('email', sa.String(320), nullable=True),
        sa.Column(
            'time_zone', sa.String(64), nullable=False, server_default=sa.text("'UTC'")
        ),
        sa.Column(
            'digest', sa.String(8), nullable=False, server_default=sa.text("'daily'")
        ),
        sa.Column('digest_hour', sa.Integer(), nullable=False, server_default='8'),
        sa.Column('quiet_from', sa.Integer(), nullable=True),
        sa.Column('quiet_to', sa.Integer(), nullable=True),
        sa.Column(
            'quiet_weekends',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
        sa.Column('next_digest_at', DateTimeUTC(timezone=True), nullable=True),
        sa.CheckConstraint("digest in ('daily', 'weekly', 'off')", name='digest'),
        sa.PrimaryKeyConstraint('id', name='pk_taas_notification_user_settings'),
    )
    op.create_index(
        'ix_taas_notification_user_settings_tenant_id',
        'taas_notification_user_settings',
        ['tenant_id'],
    )
    op.create_index(
        'ux_taas_notification_user_settings_user',
        'taas_notification_user_settings',
        ['user_id'],
        unique=True,
    )


def data_upgrades() -> None:
    # Items get the tenant of their project (Ppm-0001); roll-up counters start from the live data.
    op.execute(
        """
        UPDATE taas_tasks t SET tenant_id = p.tenant_id
          FROM taas_projects p WHERE p.id = t.project_id AND t.tenant_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE taas_tasks p SET child_count = c.n
          FROM (SELECT parent_id, count(*) AS n FROM taas_tasks
                 WHERE parent_id IS NOT NULL AND deleted_at IS NULL GROUP BY parent_id) c
         WHERE c.parent_id = p.id
        """
    )
    # Projects whose status was the legacy "Template" become project templates (work model §11 #4).
    op.execute("UPDATE taas_projects SET kind = 'template' WHERE status = 'Template'")


def schema_downgrades() -> None:
    for table in (
        'taas_notification_user_settings',
        'taas_notification_preferences',
        'taas_notification_deliveries',
        'taas_notifications',
        'taas_ppm_user_settings',
        'taas_ppm_my_work_plans',
        'taas_ppm_attachments',
        'taas_ppm_mentions',
        'taas_ppm_audit_events',
        'taas_ppm_settings',
    ):
        op.drop_table(table)
    op.drop_index('ux_taas_file_drives_source', table_name='taas_file_drives')
    op.drop_column('taas_file_drives', 'source_id')
    _drive_kinds("'organization', 'shared', 'personal'")
    for column in ('edited_at', 'tenant_id'):
        op.drop_column('taas_projects_comments', column)
    op.drop_index(
        'ix_taas_task_checklist_items_assignee', table_name='taas_task_checklist_items'
    )
    op.drop_index(
        'ix_taas_task_checklist_items_task', table_name='taas_task_checklist_items'
    )
    for column in ('is_mandatory', 'due_date', 'assignee_user_id', 'tenant_id'):
        op.drop_column('taas_task_checklist_items', column)
    op.drop_index('ux_taas_tasks_users_live', table_name='taas_tasks_users')
    op.drop_index('ix_taas_tasks_users_user', table_name='taas_tasks_users')
    for column in ('created_by', 'created_at', 'role', 'tenant_id'):
        op.drop_column('taas_tasks_users', column)
    op.drop_index('ix_taas_tasks_open_owner', table_name='taas_tasks')
    op.drop_index('ix_taas_tasks_tenant_id', table_name='taas_tasks')
    for column in (
        'previous_stage_id',
        'rollup_due_date',
        'rollup_start_date',
        'checklist_done',
        'checklist_total',
        'done_child_count',
        'child_count',
        'progress_mode',
        'tenant_id',
    ):
        op.drop_column('taas_tasks', column)
    op.drop_column('taas_projects', 'created_from_template_id')
    op.drop_index('ix_taas_projects_kind', table_name='taas_projects')
    op.drop_column('taas_projects', 'kind')
