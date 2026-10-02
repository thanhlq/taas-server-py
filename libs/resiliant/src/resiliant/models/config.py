"""Table naming for the resiliant models (kept independent of ``libs/db``)."""

import os

RESILIANT_TABLE_PREFIX = os.environ.get('RESILIANT_TABLE_PREFIX', 'resiliant_')
"""Prefix of every resiliant table, e.g. ``resiliant_outbox_messages``."""

type TENANT_ID_COLUMN_TYPE = str
"""Tenant ids are text in the resiliant tables (shared with taas-server-js)."""
