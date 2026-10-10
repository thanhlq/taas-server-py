"""Wire types of the work model V2 API (taas-specs/ppm/work-model/work-model-spec.md §7): item types, custom fields
+ bindings, checklist templates, approvals + policies, project templates."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from foundation.serialization import ApiRequest, ApiResponse

# --- item types ---------------------------------------------------------------------------------------


class PpmBehaviourOut(ApiResponse):
    key: str
    in_progress: bool = True
    single_date: bool = False
    no_effort: bool = False
    done_by_approval: bool = False


class PpmItemTypeOut(ApiResponse):
    id: str
    key: str
    term: str
    behaviour: str
    group: str
    origin: str
    translations: dict[str, str] = {}
    icon: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    default_checklist_template_id: Optional[str] = None
    archived: bool = False
    used: Optional[int] = None


class PpmItemTypeIn(ApiRequest):
    term: Optional[str] = None
    behaviour: Optional[str] = None
    group: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    translations: Optional[dict[str, str]] = None
    default_checklist_template_id: Optional[str] = None


# --- custom fields ------------------------------------------------------------------------------------


class PpmCustomFieldOut(ApiResponse):
    id: str
    key: str
    label: str
    type: str
    config: dict[str, Any] = {}
    description: Optional[str] = None
    project_id: Optional[str] = None
    archived: bool = False


class PpmCustomFieldIn(ApiRequest):
    label: Optional[str] = None
    type: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    description: Optional[str] = None
    project_id: Optional[str] = None
    position: Optional[float] = None


class PpmFieldBindingIo(ApiRequest):
    field_id: str
    item_type_key: Optional[str] = None
    project_id: Optional[str] = None
    required: str = 'never'
    default_value: Any = None
    section: Optional[str] = None
    position: float = 0
    on_create_form: bool = False
    on_card: bool = False


class PpmFieldBindingsIn(ApiRequest):
    bindings: list[PpmFieldBindingIo] = []


class PpmProjectFieldsOut(ApiResponse):
    """Fields usable in a project (organization + its own) and every binding that applies to it."""

    fields: list[PpmCustomFieldOut] = []
    bindings: list[PpmFieldBindingIo] = []


# --- checklist templates ------------------------------------------------------------------------------


class PpmChecklistTemplateItemIo(ApiRequest):
    name: str
    is_mandatory: bool = False
    category: Optional[str] = None


class PpmChecklistTemplateOut(ApiResponse):
    id: str
    name: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    items: list[PpmChecklistTemplateItemIo] = []


class PpmChecklistTemplateIn(ApiRequest):
    name: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[str] = None
    items: Optional[list[PpmChecklistTemplateItemIo]] = None


class PpmApplyChecklistTemplateIn(ApiRequest):
    checklist_template_id: str


class PpmSaveChecklistTemplateIn(ApiRequest):
    name: str
    # True: a template of the item's project; False: of the organization.
    project_scope: bool = False


# --- approvals ----------------------------------------------------------------------------------------


class PpmApproverSpec(ApiRequest):
    """``type``: ``user`` (ref = id / e-mail) · ``project_role`` (ref = role key) · ``item_owner``."""

    type: str = 'user'
    ref: str = ''


class PpmApprovalStepIn(ApiRequest):
    name: Optional[str] = None
    rule: str = 'any'
    approvers: list[PpmApproverSpec] = []


class PpmApprovalRequestIn(ApiRequest):
    subject_type: str
    subject_id: str
    steps: Optional[list[PpmApprovalStepIn]] = None
    policy_id: Optional[str] = None
    due_at: Optional[datetime] = None
    note: Optional[str] = None


class PpmApprovalDecisionIn(ApiRequest):
    decision: str
    comment: Optional[str] = None


class PpmApprovalDelegateIn(ApiRequest):
    user_id: str
    comment: Optional[str] = None


class PpmApprovalCommentIn(ApiRequest):
    comment: Optional[str] = None


class PpmApprovalApproverOut(ApiResponse):
    step: int
    user: str
    rule: str
    decision: str
    step_name: Optional[str] = None
    resolved_from: Optional[str] = None
    decided_at: Optional[datetime] = None
    comment: Optional[str] = None
    delegated_from: Optional[str] = None


class PpmApprovalEventOut(ApiResponse):
    action: str
    round: int
    occurred_at: datetime
    actor: Optional[str] = None
    step: Optional[int] = None
    comment: Optional[str] = None


class PpmApprovalOut(ApiResponse):
    id: str
    subject_type: str
    subject_id: str
    title: str
    status: str
    round: int
    current_step: int
    requested_by: str
    requested_at: datetime
    project_id: Optional[str] = None
    note: Optional[str] = None
    due_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    snapshot: dict[str, Any] = {}
    # Figures of the subject today when they differ from the snapshot (Ppm-0872).
    current: Optional[dict[str, Any]] = None
    approvers: list[PpmApprovalApproverOut] = []
    events: list[PpmApprovalEventOut] = []
    # The caller may decide now (named approver of the current step, pending).
    can_decide: bool = False
    can_cancel: bool = False


class PpmApprovalPolicyIo(ApiRequest):
    name: Optional[str] = None
    subject_type: Optional[str] = None
    project_id: Optional[str] = None
    conditions: Optional[dict[str, Any]] = None
    steps: Optional[list[PpmApprovalStepIn]] = None
    due_working_days: Optional[int] = None
    allow_self_approval: Optional[bool] = None
    archived: Optional[bool] = None
    id: Optional[str] = None


# --- project templates --------------------------------------------------------------------------------


class PpmTemplateRoleOut(ApiResponse):
    key: str
    name: str


class PpmProjectTemplateOut(ApiResponse):
    id: str
    name: str
    items: int = 0
    milestones: int = 0
    roles: list[PpmTemplateRoleOut] = []
    code: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    category: Optional[str] = None
    working_days: Optional[int] = None


class PpmSaveAsTemplateIn(ApiRequest):
    name: str
    category: Optional[str] = None
    keep_people: bool = False
    include_field_values: bool = False
    include_members: bool = False


class PpmInstantiateIn(ApiRequest):
    name: str
    start_date: date
    code: Optional[str] = None
    # Template role key → member (id / e-mail); missing or null = unassigned.
    role_map: dict[str, Optional[str]] = {}
    include_field_values: bool = False
    include_members: bool = False
    # Client (CRM account) and CRM contacts of the new project (Ppm-0112).
    client_id: Optional[str] = None
    contact_ids: Optional[list[str]] = None
    default_contact_id: Optional[str] = None


class PpmDuplicateIn(ApiRequest):
    name: str
    start_date: Optional[date] = None
    include_field_values: bool = True
    include_members: bool = True


class PpmCreatedProjectOut(ApiResponse):
    id: str
    name: str
    kind: str
    code: Optional[str] = None
