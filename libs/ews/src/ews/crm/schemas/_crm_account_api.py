"""Request/response schemas for the CRM Account API.

Mapped to the ``db.models.ews.CrmAccount`` SQLAlchemy model in the controller.
Mirrors the Project API schema style (``ApiRequest``/``ApiResponse``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from foundation.serialization import ApiRequest, ApiResponse


class CrmAccountCreateRequest(ApiRequest):
    """Create a CRM account (client/customer)."""

    name: str
    code: Optional[str] = None
    commercial_name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    account_type: Optional[str] = None
    email: Optional[str] = None
    phone_office: Optional[str] = None
    website: Optional[str] = None
    industry_id: Optional[str] = None
    employees: Optional[int] = None
    annual_revenue: Optional[str] = None
    status: Optional[str] = None
    is_individual: Optional[bool] = None
    color: Optional[str] = None
    avatar_url: Optional[str] = None
    org_id: Optional[str] = None
    # Account owner: the user who manages this account (``CrmAccount.user_id``).
    user_id: Optional[str] = None


class CrmAccountUpdateRequest(ApiRequest):
    """Partial update; only provided fields are applied."""

    name: Optional[str] = None
    code: Optional[str] = None
    commercial_name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    account_type: Optional[str] = None
    email: Optional[str] = None
    phone_office: Optional[str] = None
    website: Optional[str] = None
    industry_id: Optional[str] = None
    employees: Optional[int] = None
    annual_revenue: Optional[str] = None
    status: Optional[str] = None
    is_individual: Optional[bool] = None
    starred: Optional[bool] = None
    color: Optional[str] = None
    avatar_url: Optional[str] = None
    # Account owner: the user who manages this account (``CrmAccount.user_id``).
    user_id: Optional[str] = None


class CrmAccountListItem(ApiResponse):
    """Lightweight account row for list/card views."""

    id: str
    name: Optional[str] = None
    code: Optional[str] = None
    display_name: Optional[str] = None
    account_type: Optional[str] = None
    email: Optional[str] = None
    phone_office: Optional[str] = None
    website: Optional[str] = None
    status: Optional[str] = None
    is_individual: Optional[bool] = None
    starred: Optional[bool] = None
    color: Optional[str] = None
    avatar_url: Optional[str] = None
    # Account owner (user id) — shown on cards/rows and used for permissions.
    user_id: Optional[str] = None
    # Key notes shown in the middle section of the account card.
    description: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CrmAccountResponse(CrmAccountListItem):
    """Full account detail."""

    commercial_name: Optional[str] = None
    industry_id: Optional[str] = None
    employees: Optional[int] = None
    annual_revenue: Optional[str] = None
    org_id: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    account_metadata: Optional[dict[str, Any]] = None
