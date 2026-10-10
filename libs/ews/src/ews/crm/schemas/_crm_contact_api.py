"""Wire types of the CRM contact routes (taas-specs/crm/contacts/contacts-spec.md). Lists are validated by
``ews.crm._contacts`` (400 ``invalid_contact`` + ``extra.field``; 409 ``contact_exists`` + ``extra.contact_id``).
Clear a text / id with ``""`` and a list with ``[]``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from foundation.serialization import ApiRequest, ApiResponse


class CrmContactEmail(ApiResponse):
    value: str
    primary: bool = False
    # No marketing e-mails.
    opt_out: bool = False
    # Bounced / wrong.
    invalid: bool = False


class CrmContactPhone(ApiResponse):
    value: str
    # ``office`` · ``mobile`` · ``home`` · ``other``.
    kind: str = 'office'
    primary: bool = False


class CrmContactAddress(ApiResponse):
    # ``primary`` · ``other``.
    kind: str = 'primary'
    street: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None


class CrmContactListItem(ApiResponse):
    id: str
    # "First Last" (else the primary e-mail).
    name: str
    is_primary: bool = False
    labels: list[str] = []
    salutation: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    # User ref (e-mail) who owns the relationship.
    owner: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CrmContactOut(CrmContactListItem):
    emails: list[CrmContactEmail] = []
    phones: list[CrmContactPhone] = []
    addresses: list[CrmContactAddress] = []
    # See ``GET /crm/contacts/lead-sources``.
    lead_source: Optional[str] = None
    reports_to_id: Optional[str] = None
    reports_to_name: Optional[str] = None
    linkedin_url: Optional[str] = None
    description: Optional[str] = None
    created_by: Optional[str] = None


class _CrmContactFields(ApiRequest, kw_only=True):
    salutation: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    account_id: Optional[str] = None
    emails: Optional[list[dict[str, Any]]] = None
    phones: Optional[list[dict[str, Any]]] = None
    addresses: Optional[list[dict[str, Any]]] = None
    owner: Optional[str] = None
    lead_source: Optional[str] = None
    reports_to_id: Optional[str] = None
    labels: Optional[list[str]] = None
    linkedin_url: Optional[str] = None
    description: Optional[str] = None


class CrmContactIn(_CrmContactFields):
    # Make it the primary contact of its account.
    primary_for_account: Optional[bool] = None
    # Create even when another contact has the same primary e-mail.
    allow_duplicate: Optional[bool] = None


class CrmContactPatch(_CrmContactFields):
    pass


class CrmLeadSourceOut(ApiResponse):
    value: str
