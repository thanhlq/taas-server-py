
# ═══════════════════════════════════════════════════════════════════════════════
# 🗄️  DATABASE COLUMN NAMES
# ═══════════════════════════════════════════════════════════════════════════════
"""
Standard column names used across database tables.
These ensure consistency in schema design and query building.
"""

ID_COLUMN_NAME = 'id'
"""Primary key column name (usually UUID)"""

USER_ID_COLUMN_NAME = 'user_id'
"""Column name for user who created/owns the entity"""

CREATED_AT_COLUMN_NAME = 'created_at'
"""Column name for entity creation timestamp"""

UPDATED_AT_COLUMN_NAME = 'updated_at'
"""Column name for entity last update timestamp"""

DELETED_COLUMN_NAME = 'deleted_at'
"""Column name for soft delete timestamp (NULL = not deleted)"""

SEQUENCE_COLUMN_NAME = 'sq_number'
"""
Sequential integer ID for human-readable ordering.
Unique within a specific scope (e.g., project, organization, tenant).
Example: Task #1, Task #2, Task #3 within a project.
Easier to remember and reference than UUIDs.
"""
