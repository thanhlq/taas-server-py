"""Wire types of the automation routes (taas-specs/ppm/automation/automation-spec.md §7). Trigger, conditions and
actions are JSON validated by ``ews.ppm._automation_rules`` (400 ``invalid_rule`` with ``extra.issues``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from foundation.serialization import ApiRequest, ApiResponse


class PpmAutomationRuleOut(ApiResponse):
    id: str
    project_id: str
    name: str
    # ``active`` · ``paused`` · ``disabled``.
    status: str
    owner: str
    # ``event`` · ``relative`` · ``schedule``.
    trigger_type: str
    trigger: dict[str, Any]
    actions: list[dict[str, Any]]
    conditions: list[dict[str, Any]] = []
    item_types: Optional[list[str]] = None
    description: Optional[str] = None
    template_key: Optional[str] = None
    version: int = 1
    failures: int = 0
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PpmAutomationRuleIn(ApiRequest):
    project_id: str
    name: str
    trigger_type: str
    trigger: dict[str, Any]
    actions: list[dict[str, Any]]
    conditions: Optional[list[dict[str, Any]]] = None
    item_types: Optional[list[str]] = None
    description: Optional[str] = None
    # ``active`` starts it at once (default ``disabled``: review first).
    status: Optional[str] = None
    template_key: Optional[str] = None


class PpmAutomationRulePatch(ApiRequest):
    version: int
    name: Optional[str] = None
    description: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger: Optional[dict[str, Any]] = None
    conditions: Optional[list[dict[str, Any]]] = None
    actions: Optional[list[dict[str, Any]]] = None
    item_types: Optional[list[str]] = None


class PpmAutomationTestIn(ApiRequest):
    """Dry-run: a saved rule (``/rules/{id}/test``) or a draft (``/rules/test`` with ``rule``) on an item."""

    item_id: Optional[str] = None
    project_id: Optional[str] = None
    rule: Optional[dict[str, Any]] = None


class PpmAutomationTestOut(ApiResponse):
    matched: bool
    status: str
    conditions: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    failed: bool = False
    error: Optional[str] = None


class PpmAutomationRunOut(ApiResponse):
    id: str
    rule_id: str
    rule_version: int
    occurrence_key: str
    status: str
    created_at: datetime
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    project_id: Optional[str] = None
    depth: int = 0
    reason: Optional[str] = None
    conditions: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    duration_ms: Optional[int] = None
    undone_at: Optional[datetime] = None
    undone_by: Optional[str] = None


class PpmAutomationCatalogOut(ApiResponse):
    """What a rule may use (labels in the web): triggers, condition fields / operators, actions, recipients."""

    event_triggers: list[str]
    relative_triggers: list[str]
    schedules: list[str]
    for_each: list[str]
    fields: dict[str, str]
    operators: list[str]
    actions: list[str]
    set_fields: list[str]
    recipients: list[str]
    tokens: list[str]
    max_conditions: int
    max_actions: int


class PpmAutomationTemplateOut(ApiResponse):
    key: str
    trigger_type: str
    trigger: dict[str, Any]
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
