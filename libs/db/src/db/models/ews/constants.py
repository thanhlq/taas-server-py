TABLE_PREFIX = 'taas_'


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
PROJECT_AUDIT_LOG_TABLE = f'{TABLE_PREFIX}projects_audit_log'
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
TIMELOG_TABLE = f'{TABLE_PREFIX}timelogs'
PAYRATE_TABLE = f'{TABLE_PREFIX}payrates'
PAYRATE_ADJUSTMENTS_TABLE = f'{TABLE_PREFIX}payrates_adjustments'
PAYROLL_TABLE = f'{TABLE_PREFIX}payrolls'
PAYRUN_TABLE = f'{TABLE_PREFIX}payruns'

# Tags and categories
TAG_TABLE = f'{TABLE_PREFIX}tags'
TAG_MAPPING_TABLE = f'{TABLE_PREFIX}tags_mapping'
CATEGORY_TABLE = f'{TABLE_PREFIX}categories'

# Auth and permissions
