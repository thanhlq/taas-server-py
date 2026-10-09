"""Wire types of the intake routes (taas-specs/ppm/intake/intake-spec.md §7). Form definitions are JSON validated by
``ews.ppm._intake_forms`` (publish: 400 ``invalid_form`` with ``extra.issues``; submit: 400 ``invalid_answers`` with
``extra.errors``). Clear an optional text / id with ``""``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from foundation.serialization import ApiRequest, ApiResponse


class PpmFormOut(ApiResponse):
    id: str
    name: str
    # ``internal`` · ``public``.
    audience: str
    # ``draft`` · ``published`` · ``closed``.
    status: str
    current_version: int
    owner: str
    version: int
    total_requests: int
    open_requests: int
    can_manage: bool
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    description: Optional[str] = None
    queue_project_id: Optional[str] = None
    queue_project_name: Optional[str] = None
    request_type_key: Optional[str] = None
    # Managers of a public form only.
    public_id: Optional[str] = None
    last_submitted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Detail only: ``{schema_version, title_template, fields, routing}``.
    draft: Optional[dict[str, Any]] = None
    # Detail only: ``confirmation``, ``redirect_url``, ``triagers``, ``notify_requester``.
    settings: Optional[dict[str, Any]] = None
    # Detail only: what blocks publishing ``[{path, message}]``.
    issues: Optional[list[dict[str, Any]]] = None
    has_changes: Optional[bool] = None


class PpmFormIn(ApiRequest):
    name: str
    # Null = an organization form.
    project_id: Optional[str] = None
    audience: Optional[str] = None
    description: Optional[str] = None
    # ``blank`` (default) · ``general`` (the *General request* starter).
    starter: Optional[str] = None
    # Copy the draft and settings of another form.
    copy_of: Optional[str] = None


class PpmFormPatch(ApiRequest):
    version: int
    name: Optional[str] = None
    description: Optional[str] = None
    audience: Optional[str] = None
    draft: Optional[dict[str, Any]] = None
    queue_project_id: Optional[str] = None
    request_type_key: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


class PpmFormVersionOut(ApiResponse):
    version: int
    published_by: str
    published_at: datetime
    definition: Optional[dict[str, Any]] = None


class PpmFormFillOut(ApiResponse):
    """A published form to fill (in the app or on the public page)."""

    name: str
    status: str
    id: Optional[str] = None
    description: Optional[str] = None
    version: Optional[int] = None
    # ``{schema_version, fields}`` — no routing, no mapping.
    definition: Optional[dict[str, Any]] = None
    confirmation: Optional[str] = None
    redirect_url: Optional[str] = None
    # Public page: ``{name}``.
    organization: Optional[dict[str, Any]] = None


class PpmRoutingTestIn(ApiRequest):
    answers: Optional[dict[str, Any]] = None
    requester_email: Optional[str] = None
    is_member: Optional[bool] = None


class PpmRoutingTestOut(ApiResponse):
    answers: dict[str, Any]
    errors: list[dict[str, Any]]
    item: dict[str, Any]
    title: str
    actions: list[dict[str, Any]]
    trace: list[dict[str, Any]]


class PpmSubmissionIn(ApiRequest):
    answers: dict[str, Any]
    form_version: Optional[int] = None
    # Public forms: who asks (required) and the honeypot (must stay empty).
    requester_name: Optional[str] = None
    requester_email: Optional[str] = None
    website: Optional[str] = None
    locale: Optional[str] = None


class PpmSubmissionOut(ApiResponse):
    request_id: str
    code: str
    status: str
    # Public forms: the tracking page (the token is shown once).
    tracking_url: Optional[str] = None
    confirmation: Optional[str] = None
    redirect_url: Optional[str] = None


class PpmRequesterOut(ApiResponse):
    is_member: bool
    ref: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None


class PpmRequestOut(ApiResponse):
    id: str
    form_id: str
    form_name: str
    # See ``GET /requests/statuses``.
    status: str
    requester: PpmRequesterOut
    submitted_at: datetime
    code: Optional[str] = None
    title: Optional[str] = None
    priority: Optional[int] = None
    updated_at: Optional[datetime] = None
    # ``accepted_item`` · ``accepted_in_place`` · ``accepted_project`` · ``rejected`` · ``merged`` · ``withdrawn``.
    decision: Optional[str] = None
    closed_at: Optional[datetime] = None
    # Triagers only.
    queue_project_id: Optional[str] = None
    queue_project_name: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[datetime] = None
    result_project_id: Optional[str] = None
    result_task_id: Optional[str] = None


class PpmRequestAnswerOut(ApiResponse):
    key: str
    label: str
    text: str
    type: Optional[str] = None
    value: Any = None


class PpmRequestMessageOut(ApiResponse):
    id: str
    # ``requester`` (seen by the requester) · ``internal`` (note).
    visibility: str
    from_requester: bool
    text: str
    author: Optional[str] = None
    created_at: Optional[datetime] = None


class PpmRequestStepOut(ApiResponse):
    status: str
    at: datetime


class PpmRequestDetailOut(PpmRequestOut):
    form_version: int = 1
    answers: list[PpmRequestAnswerOut] = []
    conversation: list[PpmRequestMessageOut] = []
    timeline: list[PpmRequestStepOut] = []
    can_triage: bool = False
    is_requester: bool = False
    can_withdraw: bool = False
    description: Optional[str] = None
    routing_trace: Optional[list[dict[str, Any]]] = None
    decision_reason: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    duplicate_of: Optional[str] = None
    # Project of the result item (accepted as item).
    result_item_project_id: Optional[str] = None


class PpmRequestStatusOut(ApiResponse):
    key: str
    open: bool


class PpmAcceptIn(ApiRequest):
    # ``item`` · ``in_place`` · ``project``.
    mode: str
    project_id: Optional[str] = None
    item_type: Optional[str] = None
    stage_id: Optional[str] = None
    owner: Optional[str] = None
    name: Optional[str] = None
    workflow_template_id: Optional[str] = None
    project_template_id: Optional[str] = None
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    add_requester: Optional[bool] = None


class PpmRejectIn(ApiRequest):
    reason: str


class PpmMergeIn(ApiRequest):
    original_id: str


class PpmRequestInfoIn(ApiRequest):
    question: str


class PpmReplyIn(ApiRequest):
    text: str
    # ``requester`` (default) · ``internal`` (triagers only).
    visibility: Optional[str] = None


class PpmTrackingOut(ApiResponse):
    """The public tracking page (Ppm-1173): no internal data."""

    title: str
    form_name: str
    status: str
    submitted_at: datetime
    can_withdraw: bool
    can_reply: bool
    code: Optional[str] = None
    organization: Optional[dict[str, Any]] = None
    decision_reason: Optional[str] = None
    timeline: list[PpmRequestStepOut] = []
    conversation: list[PpmRequestMessageOut] = []
