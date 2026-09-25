"""Request/response schemas for the CRM Account API.

Mapped to the ``db.models.ews.CrmAccount`` SQLAlchemy model in the controller.
Mirrors the Project API schema style (``ApiRequest``/``ApiResponse``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from db.models.ews.ews_enums import CrmAccountStatus
from foundation.serialization import ApiRequest, ApiResponse


class CrmContact(ApiResponse):
    """A person at the account (primary contact)."""

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class CrmContactInput(ApiRequest):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class _CrmBusinessInput(ApiRequest, kw_only=True):
    """CRM business fields (stored in ``account_metadata`` / ``account_rank`` / address)."""

    # Priority tier, e.g. Enterprise, Mid-market, SMB (``account_rank``).
    tier: Optional[str] = None
    primary_contact: Optional[CrmContactInput] = None
    # Annual recurring revenue and open pipeline, in ``currency``.
    arr: Optional[float] = None
    open_pipeline: Optional[float] = None
    currency: Optional[str] = None
    # 0-100.
    health_score: Optional[int] = None
    renewal_date: Optional[date] = None
    # Default address.
    country: Optional[str] = None
    city: Optional[str] = None


class CrmAccountCreateRequest(_CrmBusinessInput):
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
    status: Optional[CrmAccountStatus] = None
    is_individual: Optional[bool] = None
    color: Optional[str] = None
    avatar_url: Optional[str] = None
    org_id: Optional[str] = None
    # Account owner: the user who manages this account (``CrmAccount.user_id``).
    user_id: Optional[str] = None


class CrmAccountUpdateRequest(_CrmBusinessInput):
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
    status: Optional[CrmAccountStatus] = None
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
    # Badge tone of ``status`` (see ``ews.crm._account_status``).
    status_color: Optional[str] = None
    industry_id: Optional[str] = None
    tier: Optional[str] = None
    primary_contact: Optional[CrmContact] = None
    arr: Optional[float] = None
    open_pipeline: Optional[float] = None
    currency: Optional[str] = None
    health_score: Optional[int] = None
    renewal_date: Optional[date] = None
    country: Optional[str] = None
    city: Optional[str] = None
    # Last change to the account (``updated_at``).
    last_activity_at: Optional[datetime] = None


class CrmAccountResponse(CrmAccountListItem):
    """Full account detail."""

    commercial_name: Optional[str] = None
    employees: Optional[int] = None
    annual_revenue: Optional[str] = None
    org_id: Optional[str] = None
    settings: Optional[dict[str, Any]] = None
    account_metadata: Optional[dict[str, Any]] = None


class CrmAccountStatusOption(ApiResponse):
    """One entry of the account status catalog (``GET /crm/accounts/statuses``)."""

    value: str
    color: str
