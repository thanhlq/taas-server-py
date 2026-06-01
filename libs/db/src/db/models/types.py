from sqlalchemy.dialects.postgresql import JSONB

TABLE_PREFIX = 'taas_'

# Core tables
TENANTS_TABLE = f'{TABLE_PREFIX}tenants'
CRM_ACCOUNTS_TABLE = f'{TABLE_PREFIX}crm_accounts'
CRM_ACCOUNTS_ADDRESSES_TABLE = f'{TABLE_PREFIX}crm_accounts_addresses'
# USERS_TABLE = f"{TABLE_PREFIX}users"
# GROUPS_TABLE = f"{TABLE_PREFIX}groups"
# GROUPS_USERS_TABLE = f"{TABLE_PREFIX}groups_users"

# Project management tables
PROJECTS_TABLE = f'{TABLE_PREFIX}projects'
PROJECTS_ACTIONS_TABLE = f'{TABLE_PREFIX}projects_actions'
PROJECTS_COMMENTS_TABLE = f'{TABLE_PREFIX}projects_comments'
PROJECTS_RESOURCES_TABLE = f'{TABLE_PREFIX}projects_resources'
PROJECTS_RISKS_TABLE = f'{TABLE_PREFIX}projects_risks'
PROJECTS_UPDATES_TABLE = f'{TABLE_PREFIX}projects_updates'
PROJECTS_USERS_TABLE = f'{TABLE_PREFIX}projects_users'

# Workflow tables
WORKFLOWS_TABLE = f'{TABLE_PREFIX}projects_workflows'
WORKFLOWS_STAGES_TABLE = f'{TABLE_PREFIX}projects_workflows_stages'
PROJECTS_WORKFLOWS_STAGES_ITEMS_TABLE = f'{TABLE_PREFIX}projects_workflows_stages_items'
PROJECTS_WORKFLOWS_ASSIGNMENTS_TABLE = f'{TABLE_PREFIX}projects_workflows_assignments'
PROJECTS_TEAMS_TABLE = f'{TABLE_PREFIX}projects_teams'

# Task tables
TASKS_TABLE = f'{TABLE_PREFIX}tasks'
TASKS_USERS_TABLE = f'{TABLE_PREFIX}tasks_users'

# Checklist
CHECKLIST_TEMPLATES_TABLE = f'{TABLE_PREFIX}checklist_templates'
CHECKLIST_ITEMS_TABLE = f'{TABLE_PREFIX}checklist_items'
TASK_CHECKLIST_ITEMS_TABLE = f'{TABLE_PREFIX}task_checklist_items'

# Time tracking tables
TIMELOGS_TABLE = f'{TABLE_PREFIX}timelogs'
PAYRATES_TABLE = f'{TABLE_PREFIX}payrates'
PAYRATES_ADJUSTMENTS_TABLE = f'{TABLE_PREFIX}payrates_adjustments'
PAYROLLS_TABLE = f'{TABLE_PREFIX}payrolls'
PAYRUNS_TABLE = f'{TABLE_PREFIX}payruns'

# Tags and categories
TAGS_TABLE = f'{TABLE_PREFIX}tags'
TAGS_MAPPING_TABLE = f'{TABLE_PREFIX}tags_mapping'
CATEGORIES_TABLE = f'{TABLE_PREFIX}categories'

# Auth and permissions
AUTH_TOKENS_TABLE = f'{TABLE_PREFIX}auth_tokens'
PERMISSIONS_TABLE = f'{TABLE_PREFIX}permissions'
ROLES_TABLE = f'{TABLE_PREFIX}roles'
POLICIES_TABLE = f'{TABLE_PREFIX}policies'


__all__ = [
    'JSONB',
]
