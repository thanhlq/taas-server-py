"""Automation routes (taas-specs/ppm/automation/automation-spec.md §7, Part B): catalog, templates, project rules
(create, change on ``version``, enable / disable, delete), dry-run, run log and undo. Rules and engine in
``ews.ppm._automation`` (pure part ``_automation_rules``); capability ``automation`` (Ppm-1756)."""

from __future__ import annotations

from typing import Optional

from db.models.ppm import PpmAutomationRule, PpmAutomationRun
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post
from foundation.http import status as http_status

from ews.security import RequestScope, current_scope

from .. import _access as access
from .. import _automation as automation
from .. import _automation_rules as rules
from .. import _settings
from ..schemas._automation_api import (
    PpmAutomationCatalogOut,
    PpmAutomationRuleIn,
    PpmAutomationRuleOut,
    PpmAutomationRulePatch,
    PpmAutomationRunOut,
    PpmAutomationTemplateOut,
    PpmAutomationTestIn,
    PpmAutomationTestOut,
)


async def _scope(session: DBAsyncScopedSession) -> RequestScope:
    scope = await current_scope()
    await _settings.require_capability(session, scope, 'automation')
    return scope


def _rule_out(r: PpmAutomationRule) -> PpmAutomationRuleOut:
    return PpmAutomationRuleOut(
        id=str(r.id),
        project_id=str(r.project_id),
        name=r.name,
        status=r.status,
        owner=r.owner,
        trigger_type=r.trigger_type,
        trigger=r.trigger,
        actions=r.actions,
        conditions=r.conditions or [],
        item_types=r.item_types,
        description=r.description,
        template_key=r.template_key,
        version=r.version,
        failures=r.failures,
        next_run_at=r.next_run_at,
        last_run_at=r.last_run_at,
        last_status=r.last_status,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _run_out(r: PpmAutomationRun) -> PpmAutomationRunOut:
    return PpmAutomationRunOut(
        id=str(r.id),
        rule_id=str(r.rule_id),
        rule_version=r.rule_version,
        occurrence_key=r.occurrence_key,
        status=r.status,
        created_at=r.created_at,
        subject_type=r.subject_type,
        subject_id=r.subject_id,
        project_id=str(r.project_id) if r.project_id else None,
        depth=r.depth,
        reason=r.reason,
        conditions=r.conditions or [],
        actions=r.actions or [],
        duration_ms=r.duration_ms,
        undone_at=r.undone_at,
        undone_by=r.undone_by,
    )


class PpmAutomationController(BaseController):
    """Catalog, templates, rules, dry-run, run log, undo."""

    api_prefix = '/api/v1/ppm'
    tags = ('PPM automation',)

    @get(
        '/automation-catalog',
        summary='Triggers, condition fields / operators, actions, recipients, tokens',
    )
    @db_context_session
    async def catalog(self, session: DBAsyncScopedSession) -> PpmAutomationCatalogOut:
        await _scope(session)
        return PpmAutomationCatalogOut(
            event_triggers=list(rules.EVENT_TRIGGERS),
            relative_triggers=list(rules.RELATIVE_TRIGGERS),
            schedules=list(rules.SCHEDULES),
            for_each=list(rules.FOR_EACH),
            fields=rules.FIELDS,
            operators=list(rules.OPERATORS),
            actions=list(rules.ACTIONS),
            set_fields=list(rules.SET_FIELDS),
            recipients=list(rules.RECIPIENTS),
            tokens=list(rules.TOKENS),
            max_conditions=rules.MAX_CONDITIONS,
            max_actions=rules.MAX_ACTIONS,
        )

    @get('/automation-templates', summary='Template gallery (labels in the web)')
    @db_context_session
    async def templates(
        self, session: DBAsyncScopedSession
    ) -> list[PpmAutomationTemplateOut]:
        await _scope(session)
        return [
            PpmAutomationTemplateOut(
                key=t['key'],
                trigger_type=t['trigger_type'],
                trigger=t['trigger'],
                conditions=t['conditions'],
                actions=t['actions'],
            )
            for t in rules.TEMPLATES
        ]

    @get(
        '/automation-rules', summary='Rules of a project (or of every readable project)'
    )
    @db_context_session
    async def list_rules(
        self,
        session: DBAsyncScopedSession,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[PpmAutomationRuleOut]:
        scope = await _scope(session)
        pid = access.parse_uuid(project_id, 'project') if project_id else None
        return [
            _rule_out(r) for r in await automation.rules_of(session, scope, pid, status)
        ]

    @post(
        '/automation-rules',
        summary='Create a project rule (disabled unless status = active)',
        status_code=201,
    )
    @db_context_session(auto_commit=True)
    async def create_rule(
        self, data: PpmAutomationRuleIn, session: DBAsyncScopedSession
    ) -> PpmAutomationRuleOut:
        scope = await _scope(session)
        project = await access.load_project(session, scope, data.project_id)
        return _rule_out(
            await automation.create_rule(session, scope, project, data.as_dict())
        )

    @post(
        '/automation-rules/test',
        summary='Dry-run a draft rule on an item (nothing is saved)',
        status_code=200,
    )
    @db_context_session
    async def test_draft(
        self, data: PpmAutomationTestIn, session: DBAsyncScopedSession
    ) -> PpmAutomationTestOut:
        scope = await _scope(session)
        if data.item_id:
            task, project = await access.load_task(session, scope, data.item_id)
        else:
            task, project = (
                None,
                await access.load_project(session, scope, data.project_id),
            )
        await access.require(scope, project.id, automation.AUTOMATION, 'read')
        return PpmAutomationTestOut(
            **await automation.test_rule(session, scope, project, data.rule or {}, task)
        )

    @get('/automation-rules/{rule_id}', summary='A rule')
    @db_context_session
    async def get_rule(
        self, rule_id: str, session: DBAsyncScopedSession
    ) -> PpmAutomationRuleOut:
        scope = await _scope(session)
        rule, _ = await automation.load_rule(session, scope, rule_id)
        return _rule_out(rule)

    @patch(
        '/automation-rules/{rule_id}',
        summary='Change a rule on version (409 stale_rule)',
    )
    @db_context_session(auto_commit=True)
    async def update_rule(
        self, rule_id: str, data: PpmAutomationRulePatch, session: DBAsyncScopedSession
    ) -> PpmAutomationRuleOut:
        scope = await _scope(session)
        rule, _ = await automation.load_rule(session, scope, rule_id, 'update')
        patch_ = {k: v for k, v in data.as_dict().items() if k != 'version'}
        return _rule_out(
            await automation.update_rule(session, scope, rule, patch_, data.version)
        )

    @post(
        '/automation-rules/{rule_id}/enable',
        summary='Turn a rule on (409 rule_limit)',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def enable(
        self, rule_id: str, session: DBAsyncScopedSession
    ) -> PpmAutomationRuleOut:
        scope = await _scope(session)
        rule, _ = await automation.load_rule(session, scope, rule_id, 'update')
        return _rule_out(await automation.set_status(session, scope, rule, 'active'))

    @post(
        '/automation-rules/{rule_id}/disable',
        summary='Turn a rule off',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def disable(
        self, rule_id: str, session: DBAsyncScopedSession
    ) -> PpmAutomationRuleOut:
        scope = await _scope(session)
        rule, _ = await automation.load_rule(session, scope, rule_id, 'update')
        return _rule_out(await automation.set_status(session, scope, rule, 'disabled'))

    @delete(
        '/automation-rules/{rule_id}',
        summary='Delete a rule',
        status_code=http_status.HTTP_204_NO_CONTENT,
    )
    @db_context_session(auto_commit=True)
    async def delete_rule(self, rule_id: str, session: DBAsyncScopedSession) -> None:
        scope = await _scope(session)
        rule, _ = await automation.load_rule(session, scope, rule_id, 'delete')
        await automation.delete_rule(session, scope, rule)

    @post(
        '/automation-rules/{rule_id}/test',
        summary='Dry-run a saved rule on an item',
        status_code=200,
    )
    @db_context_session
    async def test_rule(
        self, rule_id: str, data: PpmAutomationTestIn, session: DBAsyncScopedSession
    ) -> PpmAutomationTestOut:
        scope = await _scope(session)
        rule, project = await automation.load_rule(session, scope, rule_id)
        task = None
        if data.item_id:
            task, _ = await access.load_task(session, scope, data.item_id)
        definition = {**automation._snapshot(rule), 'name': rule.name}
        return PpmAutomationTestOut(
            **await automation.test_rule(session, scope, project, definition, task)
        )

    @get('/automation-rules/{rule_id}/runs', summary='Run log of a rule (newest first)')
    @db_context_session
    async def rule_runs(
        self, rule_id: str, session: DBAsyncScopedSession, limit: int = 50
    ) -> list[PpmAutomationRunOut]:
        scope = await _scope(session)
        rule, _ = await automation.load_rule(session, scope, rule_id)
        return [
            _run_out(r)
            for r in await automation.runs_of(session, rule_id=rule.id, limit=limit)
        ]

    @get('/automation-runs', summary='Runs on an item (its Activity tab)')
    @db_context_session
    async def subject_runs(
        self, session: DBAsyncScopedSession, subject_id: str, limit: int = 50
    ) -> list[PpmAutomationRunOut]:
        scope = await _scope(session)
        task, _ = await access.load_task(session, scope, subject_id)
        return [
            _run_out(r)
            for r in await automation.runs_of(
                session, subject_id=str(task.id), limit=limit
            )
        ]

    @post(
        '/automation-runs/{run_id}/undo',
        summary='Undo a run (409 undo_conflict lists changed targets)',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def undo(
        self, run_id: str, session: DBAsyncScopedSession
    ) -> PpmAutomationRunOut:
        scope = await _scope(session)
        run = await automation.load_run(session, scope, run_id)
        return _run_out(await automation.undo(session, scope, run))
